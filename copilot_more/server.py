import asyncio
import json
import os
import signal
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta

from aiohttp import ClientSession, ClientTimeout, TCPConnector
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from rich import print
from rich.console import Console
from rich.table import Table

from copilot_more.access_token import get_cached_copilot_token, refresh_token
from copilot_more.logger import logger
from copilot_more.proxy import RECORD_TRAFFIC, get_proxy_url, initialize_proxy
from copilot_more.rate_limiter import (RateLimiter, RateLimitError,
                                       RateLimitRule)
from copilot_more.settings import settings
from copilot_more.token_counter import TokenUsage
from copilot_more.utils import StringSanitizer

console = Console()

sanitizer = StringSanitizer()

initialize_proxy()

# Global trackers
token_usage = None
rate_limiter = None


def handle_signal():
    logger.info("Received termination signal. Ctrl+C again to force exit.")
    # Set a short timeout and then force exit
    loop = asyncio.get_running_loop()
    loop.call_later(2.0, os._exit, 0)
    # For a second signal, exit immediately
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda s, f: os._exit(1))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global token_usage, rate_limiter
    # Initialize token usage tracker
    token_usage = TokenUsage()
    logger.info("Initialized token usage tracker")

    # Initialize rate limiter with settings
    rate_limiter = RateLimiter(token_usage)
    for model, limits in settings.rate_limits.items():
        for limit in limits:
            rule = RateLimitRule(
                window_minutes=limit.window_minutes,
                input_tokens=limit.input_tokens,
                output_tokens=limit.output_tokens,
                total_tokens=limit.total_tokens,
                requests=limit.requests,
                behavior=limit.behavior,
            )
            rate_limiter.add_rule(model, rule)
    logger.info("Initialized rate limiter with configured rules")

    await initialize_settings()
    print(
        "[green]Rate limiting is enabled[/green] with the following models configured:"
    )
    for model, limits in settings.rate_limits.items():
        print(f"[yellow]Model: {model}[/yellow]")
        for limit in limits:
            print(
                f"  - {limit.window_minutes}min window: "
                f"{'tokens: ' + str(limit.total_tokens) if limit.total_tokens else ''}"
                f"{' requests: ' + str(limit.requests) if limit.requests else ''} "
                f"({limit.behavior.value})"
            )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    yield

    logger.info("Application shutting down normally")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def initialize_settings():
    resp = await refresh_token()
    endpoints = resp["endpoints"]
    logger.debug(f"Endpoints: {json.dumps(endpoints, indent=2)}")
    settings.chat_completions_api_endpoint = endpoints["api"] + "/chat/completions"
    settings.models_api_endpoint = endpoints["api"] + "/models"


def extract_usage_from_response(data_list: list[dict]) -> dict:
    """
    Extract usage statistics from a list of response data objects.
    Combines usage data from multiple events if present.
    """
    combined_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for data in data_list:
        usage = data.get("usage", {})
        if usage:
            combined_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
            combined_usage["completion_tokens"] += usage.get("completion_tokens", 0)
            combined_usage["total_tokens"] += usage.get("total_tokens", 0)

    return combined_usage


def print_model_usage_statistics(model: str):
    """
    Print model usage statistics for different time periods using Rich formatting.
    """
    if not token_usage:
        logger.warning("Token usage tracker is not initialized")
        return

    now = datetime.now()
    time_periods = [
        ("Last minute", now - timedelta(minutes=1), now),
        ("Last hour", now - timedelta(hours=1), now),
        ("Last 2 hours", now - timedelta(hours=2), now),
        ("Last 5 hours", now - timedelta(hours=5), now),
        ("Last day", now - timedelta(days=1), now),
    ]

    # Create a Rich table
    table = Table(title=f"Usage Statistics for Model: [bold blue]{model}[/bold blue]")
    table.add_column("Time Period", style="cyan")
    table.add_column("Input Tokens", justify="right", style="green")
    table.add_column("Output Tokens", justify="right", style="yellow")
    table.add_column("Total Tokens", justify="right", style="bold red")

    # Add rows for each time period
    for period_name, start_time, end_time in time_periods:
        usage = token_usage.query_usage(start_time, end_time, model)
        table.add_row(
            period_name,
            f"{usage['total_input_tokens']:,}",
            f"{usage['total_output_tokens']:,}",
            f"{usage['total_tokens']:,}",
        )

    # Print the table
    console.print(table)

    # Still log to logger for records
    logger.info(f"Printed usage statistics for model: {model}")


def parse_accumulated_sse_data(accumulated_text: str) -> list[dict]:
    """
    Parse accumulated SSE text data into a list of JSON objects.

    Args:
        accumulated_text: String containing all SSE data

    Returns:
        List of parsed JSON objects from the SSE data
    """
    parsed_events = []
    parts = accumulated_text.split("\n\n")

    for part in parts:
        part = part.strip()
        if part and part.startswith("data: ") and part != "data: [DONE]":
            try:
                json_str = part.replace("data: ", "", 1)
                parsed_data = json.loads(json_str)
                parsed_events.append(parsed_data)
            except json.JSONDecodeError:
                # Skip invalid JSON
                logger.error(f"Failed to parse event JSON from part: {part[:100]}...")

    return parsed_events


def process_usage_and_show_statistics(model: str, parsed_events: list[dict]):
    """
    Process usage data from parsed events and display statistics.

    Args:
        model: The model name
        parsed_events: List of parsed SSE events
    """
    if not parsed_events:
        return

    usage_data = extract_usage_from_response(parsed_events)

    # Record the token usage if available
    if token_usage and usage_data:
        token_usage.record_usage_from_response(model, usage_data)
        logger.info(f"Recorded token usage from API stats: {json.dumps(usage_data)}")

        # Print usage statistics for different time periods
        print_model_usage_statistics(model)


def preprocess_request_body(request_body: dict) -> dict:
    """
    Preprocess the request body to handle array content in messages.
    """
    if not request_body.get("messages"):
        return request_body

    processed_messages = []

    for message in request_body["messages"]:
        if not isinstance(message.get("content"), list):
            content = message["content"]
            if isinstance(content, str):
                result = sanitizer.sanitize(content)
                if not result.success:
                    logger.warning(f"String sanitization warnings: {result.warnings}")
                content = result.text
            message["content"] = content
            processed_messages.append(message)
            continue

        for content_item in message["content"]:
            if content_item.get("type") != "text":
                raise HTTPException(400, "Only text type is supported in content array")

            text = content_item["text"]
            if isinstance(text, str):
                result = sanitizer.sanitize(text)
                if not result.success:
                    logger.warning(f"String sanitization warnings: {result.warnings}")
                text = result.text

            processed_messages.append({"role": message["role"], "content": text})

    # o1 models don't support system messages
    model: str = request_body.get("model", "")
    if model and model.startswith("o1"):
        for message in processed_messages:
            if message["role"] == "system":
                message["role"] = "user"

    max_tokens = request_body.get("max_tokens", settings.max_tokens)
    return {**request_body, "messages": processed_messages, "max_tokens": max_tokens}


# o1 models only support non-streaming responses, we need to convert them to standard streaming format
def convert_o1_response(data: dict) -> dict:
    """Convert o1 model response format to standard format"""
    if "choices" not in data:
        return data

    choices = data["choices"]
    if not choices:
        return data

    converted_choices = []
    for choice in choices:
        if "message" in choice:
            converted_choice = {
                "index": choice["index"],
                "delta": {"content": choice["message"]["content"]},
            }
            if "finish_reason" in choice:
                converted_choice["finish_reason"] = choice["finish_reason"]
            converted_choices.append(converted_choice)

    return {**data, "choices": converted_choices}


def convert_to_sse_events(data: dict) -> list[str]:
    """Convert response data to SSE events"""
    events = []
    if "choices" in data:
        for choice in data["choices"]:
            event_data = {
                "id": data.get("id", ""),
                "created": data.get("created", 0),
                "model": data.get("model", ""),
                "choices": [choice],
            }
            events.append(f"data: {json.dumps(event_data)}\n\n")
    events.append("data: [DONE]\n\n")
    return events


async def create_client_session() -> ClientSession:
    connector = TCPConnector(ssl=False) if get_proxy_url() else TCPConnector()
    return ClientSession(
        timeout=ClientTimeout(total=settings.timeout_seconds), connector=connector
    )


async def execute_rate_limit_sleep(delay: float, reason: str = "Rate limit") -> None:
    if delay <= 0:
        return

    logger.info(f"{reason} delay: waiting {delay:.2f} seconds")

    try:
        with suppress(asyncio.CancelledError):
            await asyncio.sleep(delay)
    except asyncio.CancelledError:
        logger.info(f"{reason} delay interrupted")
        raise HTTPException(499, "Request cancelled by client")


@app.get("/models")
async def list_models():
    """
    Proxies models request.
    """
    try:
        token = await get_cached_copilot_token()
        session = await create_client_session()
        async with session as s:
            kwargs = {
                "headers": {
                    "Authorization": f"Bearer {token['token']}",
                    "Content-Type": "application/json",
                    "editor-version": settings.editor_version,
                }
            }
            if RECORD_TRAFFIC:
                kwargs["proxy"] = get_proxy_url()
            async with s.get(settings.models_api_endpoint, **kwargs) as response:
                if response.status != 200:
                    error_message = await response.text()
                    logger.error(f"Models API error: {error_message}")
                    raise HTTPException(
                        response.status, f"Models API error: {error_message}"
                    )
                return await response.json()
    except Exception as e:
        logger.error(f"Error fetching models: {str(e)}")
        raise HTTPException(500, f"Error fetching models: {str(e)}")


@app.post("/chat/completions")
async def proxy_chat_completions(request: Request):
    """
    Proxies chat completion requests with SSE support.
    """
    request_body = await request.json()
    logger.debug(f"Received request: {json.dumps(request_body, indent=2)}")

    try:
        request_body = preprocess_request_body(request_body)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(400, f"Error preprocessing request: {str(e)}")

    # Get model
    model = request_body.get("model", "")

    # Check request rate limits only
    if not rate_limiter:
        raise HTTPException(500, "Rate limiter is not initialized")

    assert rate_limiter is not None  # Help mypy understand the type
    current_time = datetime.now()
    try:
        delay = await rate_limiter.check_request_limit(model, current_time)
        if delay:
            await execute_rate_limit_sleep(delay, "Request rate limit")
    except RateLimitError as e:
        raise HTTPException(429, str(e))

    async def stream_response():
        try:
            token = await get_cached_copilot_token()
            is_streaming = request_body.get("stream", False)

            # Storage for accumulated chunks for both model types
            all_text_chunks = ""

            # Apply configured sleep between API calls
            if settings.sleep_between_calls > 0:
                await execute_rate_limit_sleep(
                    settings.sleep_between_calls, "API call spacing"
                )

            session = await create_client_session()
            async with session as s:
                kwargs = {
                    "json": request_body,
                    "headers": {
                        "Authorization": f"Bearer {token['token']}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                        "editor-version": settings.editor_version,
                    },
                }
                if RECORD_TRAFFIC:
                    kwargs["proxy"] = get_proxy_url()
                async with s.post(
                    settings.chat_completions_api_endpoint, **kwargs
                ) as response:
                    if response.status != 200:
                        error_message = await response.text()
                        logger.error(f"API error: {error_message}")
                        raise HTTPException(
                            response.status, f"API error: {error_message}"
                        )

                    if model.startswith("o1") and is_streaming:
                        # For o1 models with streaming, read entire response and convert to SSE
                        data = await response.json()
                        converted_data = convert_o1_response(data)
                        for event in convert_to_sse_events(converted_data):
                            encoded_event = event.encode("utf-8")
                            yield encoded_event

                            # Accumulate text representations of events
                            if isinstance(encoded_event, bytes):
                                all_text_chunks += encoded_event.decode("utf-8")
                            else:
                                all_text_chunks += encoded_event
                    else:
                        # For other cases, stream chunks directly
                        async for chunk in response.content.iter_chunks():
                            if chunk:
                                chunk_data = chunk[0]
                                yield chunk_data

                                # Accumulate text representations of chunks
                                if isinstance(chunk_data, bytes):
                                    all_text_chunks += chunk_data.decode("utf-8")
                                else:
                                    all_text_chunks += chunk_data

                    parsed_events = parse_accumulated_sse_data(all_text_chunks)

                    # Process usage data, check token limits, record the request, and show statistics
                    process_usage_and_show_statistics(model, parsed_events)
                    if rate_limiter:
                        current_time = datetime.now()
                        # Check token limits first as it may affect future requests
                        token_delay = rate_limiter.check_token_limits(
                            model, current_time
                        )
                        if token_delay and token_delay > 0:
                            await execute_rate_limit_sleep(
                                token_delay, "Token rate limit"
                            )
                        rate_limiter.record_request(model, current_time)

        except Exception as e:
            logger.error(f"Error in stream_response: {str(e)}")
            yield json.dumps({"error": str(e)}).encode("utf-8")

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
    )
