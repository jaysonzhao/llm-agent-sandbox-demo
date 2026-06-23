import asyncio
import json
import logging
import os
import time
import uuid

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from sandbox_executor import create_client, execute_code

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Sandbox Agent")

VERTEX_PROJECT = os.environ.get("VERTEX_PROJECT", "")
VERTEX_REGION = os.environ.get("VERTEX_REGION", "us-east5")
MODEL_NAME = os.environ.get("MODEL_NAME", "claude-sonnet-4@20250514")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "4096"))
GCP_CREDENTIALS_PATH = os.environ.get(
    "GOOGLE_APPLICATION_CREDENTIALS",
    "/etc/gcp/application_default_credentials.json",
)

SYSTEM_PROMPT = (
    "You are a helpful coding assistant. When asked to write code, always show it "
    "in a fenced markdown code block with the language tag (e.g. ```python). "
    "Available languages: Python (with numpy, pandas, scipy, sympy, matplotlib, "
    "scikit-learn), Bash, JavaScript."
)

sandbox_client = None
_access_token = None
_token_expiry = 0


@app.on_event("startup")
async def startup():
    global sandbox_client
    try:
        sandbox_client = create_client()
        logger.info("Sandbox client initialized")
    except Exception:
        logger.warning("Sandbox client init failed - will retry on first request", exc_info=True)


def get_sandbox_client():
    global sandbox_client
    if sandbox_client is None:
        sandbox_client = create_client()
    return sandbox_client


def _refresh_access_token():
    global _access_token, _token_expiry
    if _access_token and time.time() < _token_expiry - 60:
        return _access_token

    with open(GCP_CREDENTIALS_PATH) as f:
        creds = json.load(f)

    resp = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "grant_type": "refresh_token",
            "client_id": creds["client_id"],
            "client_secret": creds["client_secret"],
            "refresh_token": creds["refresh_token"],
        },
    )
    resp.raise_for_status()
    token_data = resp.json()
    _access_token = token_data["access_token"]
    _token_expiry = time.time() + token_data.get("expires_in", 3600)
    logger.info("Refreshed GCP access token (expires in %ds)", token_data.get("expires_in", 3600))
    return _access_token


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "vertex-ai",
            }
        ],
    }


@app.get("/v1/models/{model_id}")
async def get_model(model_id: str):
    return {
        "id": MODEL_NAME,
        "object": "model",
        "created": int(time.time()),
        "owned_by": "vertex-ai",
    }


def _openai_tools_to_anthropic(openai_tools: list) -> list:
    anthropic_tools = []
    for tool in openai_tools:
        if tool.get("type") == "function":
            fn = tool["function"]
            anthropic_tools.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        elif "name" in tool and "parameters" in tool:
            anthropic_tools.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool["parameters"],
            })
    return anthropic_tools


def _openai_messages_to_anthropic(messages: list) -> tuple:
    system = SYSTEM_PROMPT
    anthropic_messages = []

    for msg in messages:
        role = msg.get("role", "")

        if role == "system":
            system = msg.get("content", "")
            continue

        if role == "user":
            anthropic_messages.append({"role": "user", "content": msg.get("content", "")})

        elif role == "assistant":
            tool_calls = msg.get("tool_calls")
            if tool_calls:
                content_blocks = []
                text = msg.get("content")
                if text:
                    content_blocks.append({"type": "text", "text": text})
                for tc in tool_calls:
                    fn = tc["function"]
                    try:
                        inp = json.loads(fn["arguments"])
                    except (json.JSONDecodeError, TypeError):
                        inp = {"code": fn.get("arguments", ""), "language": "python"}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": fn["name"],
                        "input": inp,
                    })
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            else:
                anthropic_messages.append({
                    "role": "assistant",
                    "content": msg.get("content") or "",
                })

        elif role == "tool":
            tool_result_block = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id", ""),
                "content": msg.get("content", ""),
            }
            if anthropic_messages and anthropic_messages[-1]["role"] == "user":
                last = anthropic_messages[-1]
                if isinstance(last["content"], str):
                    last["content"] = [{"type": "text", "text": last["content"]}, tool_result_block]
                else:
                    last["content"].append(tool_result_block)
            else:
                anthropic_messages.append({"role": "user", "content": [tool_result_block]})

    return system, anthropic_messages


def _anthropic_response_to_openai(response: dict) -> dict:
    content_blocks = response.get("content", [])
    text_parts = []
    tool_calls = []

    for block in content_blocks:
        if block["type"] == "text":
            text_parts.append(block["text"])
        elif block["type"] == "tool_use":
            tool_calls.append({
                "id": block["id"],
                "type": "function",
                "function": {
                    "name": block["name"],
                    "arguments": json.dumps(block["input"]),
                },
            })

    message = {"role": "assistant", "content": "\n".join(text_parts) if text_parts else None}
    if tool_calls:
        message["tool_calls"] = tool_calls

    stop_reason = response.get("stop_reason", "end_turn")
    finish_reason = "tool_calls" if stop_reason == "tool_use" else "stop"

    return {
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": response.get("usage", {}),
    }


async def call_llm(messages: list, tools: list = None) -> dict:
    system, anthropic_messages = _openai_messages_to_anthropic(messages)
    token = _refresh_access_token()

    url = (
        f"https://{VERTEX_REGION}-aiplatform.googleapis.com/v1/"
        f"projects/{VERTEX_PROJECT}/locations/{VERTEX_REGION}/"
        f"publishers/anthropic/models/{MODEL_NAME}:rawPredict"
    )

    body = {
        "anthropic_version": "vertex-2023-10-16",
        "system": system,
        "messages": anthropic_messages,
        "max_tokens": MAX_TOKENS,
        "temperature": 0.1,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = {"type": "auto"}

    max_retries = 3
    for attempt in range(max_retries):
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code in (429, 503, 529):
                wait = 2 ** attempt * 5
                logger.warning("Vertex AI returned %d, retrying in %ds (attempt %d/%d)",
                               resp.status_code, wait, attempt + 1, max_retries)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return _anthropic_response_to_openai(resp.json())

    raise Exception(f"Vertex AI API failed after {max_retries} retries")


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    has_system = any(m.get("role") == "system" for m in messages)
    if not has_system:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    openai_tools = body.get("tools", [])
    anthropic_tools = _openai_tools_to_anthropic(openai_tools) if openai_tools else []

    try:
        result = await call_llm(messages, anthropic_tools or None)
        choice = result["choices"][0]
        msg = choice["message"]
        finish_reason = choice.get("finish_reason", "stop")

        logger.info(
            "finish_reason=%s | tool_calls=%s | content_preview=%.200s",
            finish_reason, bool(msg.get("tool_calls")),
            msg.get("content", "") or "",
        )

        if stream:
            return StreamingResponse(
                stream_response(msg, finish_reason, body),
                media_type="text/event-stream",
            )
        return JSONResponse(format_response(msg, finish_reason, result.get("usage", {}), body))

    except Exception as e:
        logger.exception("Chat completion failed")
        error_msg = f"Error: {e}"
        if stream:
            return StreamingResponse(
                stream_response({"role": "assistant", "content": error_msg}, "stop", body),
                media_type="text/event-stream",
            )
        return JSONResponse(format_response(
            {"role": "assistant", "content": error_msg}, "stop", {}, body))


def format_response(message: dict, finish_reason: str, usage: dict, original_body: dict) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": original_body.get("model", MODEL_NAME),
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


async def stream_response(message: dict, finish_reason: str, original_body: dict):
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    model = original_body.get("model", MODEL_NAME)
    content = message.get("content") or ""
    tool_calls = message.get("tool_calls") or []

    chunk_start = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
    }
    yield f"data: {json.dumps(chunk_start)}\n\n"

    if content:
        chunk_size = 20
        for i in range(0, len(content), chunk_size):
            chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": content[i:i + chunk_size]},
                    "finish_reason": None,
                }],
            }
            yield f"data: {json.dumps(chunk)}\n\n"

    for i, tc in enumerate(tool_calls):
        tc_chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {
                    "tool_calls": [{
                        "index": i,
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }]
                },
                "finish_reason": None,
            }],
        }
        yield f"data: {json.dumps(tc_chunk)}\n\n"

    chunk_end = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
    }
    yield f"data: {json.dumps(chunk_end)}\n\n"
    yield "data: [DONE]\n\n"


@app.post("/v1/sandbox/execute")
async def sandbox_execute(request: Request):
    body = await request.json()
    language = body.get("language", "python")
    code = body.get("code", "")

    logger.info("Direct sandbox execute: %s (%d chars)", language, len(code))
    result = execute_code(get_sandbox_client(), language, code)
    return JSONResponse(result)


@app.get("/health")
async def health():
    return {"status": "ok"}
