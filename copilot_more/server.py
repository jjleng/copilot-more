from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from aiohttp import ClientSession, ClientTimeout, TCPConnector
import json

from copilot_more.token import get_cached_copilot_token
from copilot_more.logger import logger
from copilot_more.proxy import initialize_proxy, get_proxy_url, RECORD_TRAFFIC

initialize_proxy()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


CHAT_COMPLETIONS_API_ENDPOINT = "https://api.individual.githubcopilot.com/chat/completions"
MODELS_API_ENDPOINT = "https://api.individual.githubcopilot.com/models"
TIMEOUT = ClientTimeout(total=300)
MAX_TOKENS = 10240

def preprocess_request_body(request_body: dict) -> dict:
    """
    Preprocess the request body to handle array content in messages.
    """
    if not request_body.get("messages"):
        return request_body

    processed_messages = []

    for message in request_body["messages"]:
        if not isinstance(message.get("content"), list):
            processed_messages.append(message)
            continue

        for content_item in message["content"]:
            if content_item.get("type") != "text":
                raise HTTPException(400, "Only text type is supported in content array")

            processed_messages.append({
                "role": message["role"],
                "content": content_item["text"]
            })

    # o1 models don't support system messages
    model: str = request_body.get("model", "")
    if model and model.startswith("o1"):
        for message in processed_messages:
            if message["role"] == "system":
                message["role"] = "user"

    max_tokens = request_body.get("max_tokens", MAX_TOKENS)
    return {
        **request_body,
        "messages": processed_messages,
        "max_tokens": max_tokens
    }

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
                "delta": {
                    "content": choice["message"]["content"]
                }
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
                "id": data.get('id', ''),
                "created": data.get("created", 0),
                "model": data.get("model", ""),
                "choices": [choice]
            }
            events.append(f"data: {json.dumps(event_data)}\n\n")
    events.append("data: [DONE]\n\n")
    return events

async def create_client_session() -> ClientSession:
    connector = TCPConnector(ssl=False) if get_proxy_url() else TCPConnector()
    return ClientSession(timeout=TIMEOUT, connector=connector)

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
                    "editor-version": "vscode/1.95.3"
                }
            }
            if RECORD_TRAFFIC:
                kwargs["proxy"] = get_proxy_url()
            async with s.get(MODELS_API_ENDPOINT, **kwargs) as response:
                if response.status != 200:
                    error_message = await response.text()
                    logger.error(f"Models API error: {error_message}")
                    raise HTTPException(
                        response.status,
                        f"Models API error: {error_message}"
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

    logger.info(f"Received request: {json.dumps(request_body, indent=2)}")

    try:
        request_body = preprocess_request_body(request_body)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(400, f"Error preprocessing request: {str(e)}")

    async def stream_response():
        try:
            token = await get_cached_copilot_token()
            model = request_body.get("model", "")
            is_streaming = request_body.get("stream", False)

            session = await create_client_session()
            async with session as s:
                kwargs = {
                    "json": request_body,
                    "headers": {
                        "Authorization": f"Bearer {token['token']}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream",
                        "editor-version": "vscode/1.95.3"
                    }
                }
                if RECORD_TRAFFIC:
                    kwargs["proxy"] = get_proxy_url()
                async with s.post(CHAT_COMPLETIONS_API_ENDPOINT, **kwargs) as response:
                    if response.status != 200:
                        error_message = await response.text()
                        logger.error(f"API error: {error_message}")
                        raise HTTPException(
                            response.status,
                            f"API error: {error_message}"
                        )

                    if model.startswith("o1") and is_streaming:
                        # For o1 models with streaming, read entire response and convert to SSE
                        data = await response.json()
                        converted_data = convert_o1_response(data)
                        for event in convert_to_sse_events(converted_data):
                            yield event.encode('utf-8')
                    else:
                        # For other cases, stream chunks directly
                        async for chunk in response.content.iter_chunks():
                            if chunk:
                                yield chunk[0]

        except Exception as e:
            logger.error(f"Error in stream_response: {str(e)}")
            yield json.dumps({"error": str(e)}).encode("utf-8")

    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
    )