import os
import queue
import threading
import time
from typing import Optional

from aiohttp import ClientSession

from copilot_more.logger import logger

# Global variables for token caching
# {"token": "xxx", "expires_at": 1732767035}
CACHED_COPILOT_TOKEN: Optional[dict] = None
TOKEN_LOCK = threading.Lock()
TOKEN_CACHE_QUEUE: queue.Queue = queue.Queue(maxsize=1)


def cache_copilot_token(token_data: dict) -> None:
    logger.info("Caching token")
    global CACHED_COPILOT_TOKEN
    with TOKEN_LOCK:
        logger.debug(
            f"Caching new token that expires at {token_data.get('expires_at')}"
        )
        CACHED_COPILOT_TOKEN = token_data
        try:
            TOKEN_CACHE_QUEUE.get_nowait()
        except queue.Empty:
            pass
        TOKEN_CACHE_QUEUE.put(token_data)
        logger.debug("Token cached successfully")


async def get_cached_copilot_token() -> dict:
    global CACHED_COPILOT_TOKEN
    with TOKEN_LOCK:
        current_time = time.time()
        if CACHED_COPILOT_TOKEN:
            expires_at = CACHED_COPILOT_TOKEN.get("expires_at", 0)
            logger.info(
                f"Current token expires at {expires_at}, current time is {current_time}"
            )

        if (
            CACHED_COPILOT_TOKEN
            and CACHED_COPILOT_TOKEN.get("expires_at", 0) > time.time() + 300
        ):
            logger.info("Using cached token")
            return CACHED_COPILOT_TOKEN

    logger.info("Token expired or not found, refreshing...")
    new_token = await refresh_token()
    cache_copilot_token(new_token)
    return new_token


async def refresh_token() -> dict:
    logger.info("Attempting to refresh token")
    if os.getenv("REFRESH_TOKEN") is None:
        logger.error("REFRESH_TOKEN environment variable is not set")
        raise ValueError("REFRESH_TOKEN environment variable is not set.")

    async with ClientSession() as session:
        async with session.get(
            url="https://api.github.com/copilot_internal/v2/token",
            headers={
                "Authorization": "token " + (os.getenv("REFRESH_TOKEN") or ""),
                "editor-version": "vscode/1.95.3",
            },
        ) as response:
            if response.status == 200:
                token_data = await response.json()
                logger.info(
                    f"Token refreshed successfully, expires at {token_data.get('expires_at')}"
                )
                return token_data
            error_msg = (
                f"Failed to refresh token: {response.status} {await response.text()}"
            )
            logger.error(error_msg)
            raise ValueError(error_msg)
