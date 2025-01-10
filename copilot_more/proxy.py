from __future__ import annotations

import asyncio
import atexit
import logging
import os
import socket
import threading
import time
from datetime import datetime
from typing import Optional

from mitmproxy import ctx, http
from mitmproxy.io import FlowWriter
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

# Configure logging
logger = logging.getLogger(__name__)

# Global state
RECORD_TRAFFIC = os.getenv("RECORD_TRAFFIC", "").lower() in ("true", "1", "yes")
proxy_thread: Optional[threading.Thread] = None
proxy_url: Optional[str] = None
proxy_controller: Optional[ProxyController] = None
proxy_shutdown_complete = threading.Event()


class CopilotProxy:
    def __init__(self, dump_file: str | None = None):
        self.dump_file = (
            dump_file
            or f"copilot_traffic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mitm"
        )
        self.f = open(self.dump_file, "wb")
        self.w = FlowWriter(self.f)
        self.copilot_urls = (
            "https://api.githubcopilot.com",
            "https://api.individual.githubcopilot.com",
        )

    def _is_copilot_request(self, url: str) -> bool:
        return url.startswith(self.copilot_urls)

    def _sanitize_headers(self, flow: http.HTTPFlow) -> None:
        if "Authorization" in flow.request.headers:
            flow.request.headers["Authorization"] = "[REDACTED]"

    def request(self, flow: http.HTTPFlow) -> None:
        if self._is_copilot_request(flow.request.pretty_url):
            ctx.log.info(f"Captured request to: {flow.request.pretty_url}")

    def response(self, flow: http.HTTPFlow) -> None:
        if self._is_copilot_request(flow.request.pretty_url):
            self._sanitize_headers(flow)  # Sanitize before saving
            self.w.add(flow)

    def done(self):
        self.f.close()


class ProxyController:
    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self.host = host
        self.port = port
        self.loop = asyncio.new_event_loop()
        self.master_shutdown_complete = asyncio.Event()
        self._shutting_down = False

        opts = Options(listen_host=host, listen_port=port)
        self.master = DumpMaster(
            opts, with_termlog=False, with_dumper=False, loop=self.loop
        )
        self.master.addons.add(CopilotProxy())

    async def start(self):
        """Start the proxy server and handle its lifecycle"""
        try:
            await self.master.run()
        except Exception as e:
            logger.error(f"Proxy error: {e}")
        finally:
            self.master_shutdown_complete.set()
            proxy_shutdown_complete.set()  # Signal global shutdown completion

    async def _cleanup(self):
        if self._shutting_down:
            return
        self._shutting_down = True

        try:
            # Shutdown sequence: master first, then handle event loop
            self.master.shutdown()

            try:
                await asyncio.wait_for(
                    self.master_shutdown_complete.wait(), timeout=5.0
                )
            except asyncio.TimeoutError:
                logger.warning("Master shutdown wait timed out")
                # Emergency stop if graceful shutdown fails
                if self.loop and self.loop.is_running():
                    self.loop.stop()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def run(self):
        """Run the proxy server in the current thread"""
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self.start())
        finally:
            try:
                if not self._shutting_down:
                    self.loop.run_until_complete(self._cleanup())
                self.loop.close()
            except Exception as e:
                logger.error(f"Error during final cleanup: {e}")

    def stop(self):
        if self._shutting_down:
            return

        # Schedule cleanup in the event loop
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self._cleanup(), self.loop)
        else:
            logger.warning("Event loop not running, cannot initiate cleanup")


def find_available_port(start_port: int = 8080) -> int:
    port = start_port
    while port < 65535:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            port += 1
    raise RuntimeError("No available ports found")


def get_proxy_url() -> Optional[str]:
    return proxy_url


def cleanup_proxy():
    global proxy_url, proxy_controller
    if proxy_controller:
        logger.info("Shutting down proxy...")
        proxy_controller.stop()

        # Use Event's built-in wait with timeout
        if not proxy_shutdown_complete.wait(timeout=5.0):
            logger.warning("Proxy shutdown timed out")

        proxy_url = None
        proxy_controller = None
        logger.info("Proxy shutdown complete")


# Register cleanup on normal program exit if we're recording traffic
if RECORD_TRAFFIC:
    atexit.register(cleanup_proxy)


def start_proxy():
    global proxy_url, proxy_controller
    try:
        host, port = "127.0.0.1", find_available_port()
        proxy_controller = ProxyController(host, port)
        proxy_url = f"http://{host}:{port}"
        proxy_controller.run()
    except Exception as e:
        logger.error(f"Error starting proxy: {e}")
        proxy_url = None
        proxy_controller = None


def initialize_proxy() -> None:
    global proxy_thread, proxy_url, proxy_controller

    if not RECORD_TRAFFIC:
        return

    proxy_thread = threading.Thread(target=start_proxy, daemon=True)
    proxy_thread.start()

    # Wait for proxy to start
    start_time = time.time()
    while proxy_url is None and time.time() - start_time < 5:
        time.sleep(0.1)

    if proxy_url is None:
        logger.warning("Failed to start proxy server")
