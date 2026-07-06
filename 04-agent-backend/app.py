import asyncio
import json
import logging
import os
import time
import uuid

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from sandbox_executor import create_client, execute_code, verify_warmpool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Sandbox Agent")

# Inference endpoint configuration
INFERENCE_URL = os.environ.get("INFERENCE_URL", "https://maas-rhdp.apps.maas.redhatworkshops.io/v1/chat/completions")
API_KEY = os.environ.get("API_KEY", "sk-xxxxxxxxxxxx")
MODEL_NAME = os.environ.get("MODEL_NAME", "gpt-oss-120b")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "4096"))

SYSTEM_PROMPT = (
    "You are a helpful coding assistant. When asked to write code, always show it "
    "in a fenced markdown code block with the language tag (e.g. ```python). "
    "Available languages: Python (with numpy, pandas, scipy, sympy, matplotlib, "
    "scikit-learn), Bash, JavaScript."
)

sandbox_client = None


@app.on_event("startup")
async def startup():
    global sandbox_client
    verify_warmpool()
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


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "inference-endpoint",
            }
        ],
    }


@app.get("/v1/models/{model_id}")
async def get_model(model_id: str):
    return {
        "id": MODEL_NAME,
        "object": "model",
        "created": int(time.time()),
        "owned_by": "inference-endpoint",
    }


def _sse_chunk(chat_id, model, delta, finish_reason):
    return "data: {}\n\n".format(json.dumps({
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }))


async def call_llm(messages: list, tools: list = None) -> dict:
    body = {
        "model": MODEL_NAME,
        "messages": messages,
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
                INFERENCE_URL,
                json=body,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code in (429, 503, 529):
                wait = 2 ** attempt * 5
                logger.warning("Inference endpoint returned %d, retrying in %ds (attempt %d/%d)",
                               resp.status_code, wait, attempt + 1, max_retries)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()

    raise Exception(f"Inference API failed after {max_retries} retries")


async def _stream_from_inference(messages, tools=None, original_body=None):
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    model = (original_body or {}).get("model", MODEL_NAME)

    yield _sse_chunk(chat_id, model, {"role": "assistant"}, None)

    body = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "temperature": 0.1,
        "stream": True,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = {"type": "auto"}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
            async with client.stream(
                "POST", INFERENCE_URL, json=body,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json",
                },
            ) as resp:
                if resp.status_code in (429, 503, 529):
                    yield _sse_chunk(chat_id, model,
                        {"content": f"Error: Inference endpoint returned {resp.status_code}. Please try again."}, None)
                    yield _sse_chunk(chat_id, model, {}, "stop")
                    yield "data: [DONE]\n\n"
                    return
                resp.raise_for_status()

                tool_index = -1
                finish_reason = "stop"

                async for line in resp.aiter_lines():
                    if not line:
                        continue

                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break

                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # delta is nested inside choices[0]
                        choice = data.get("choices", [{}])[0]
                        delta = choice.get("delta", {})
                        # Handle content from inference endpoint (may be in "content" or "reasoning_content")
                        content = delta.get("content") or delta.get("reasoning_content")
                        if content:
                            yield _sse_chunk(chat_id, model, {"content": content}, None)

                        if "tool_calls" in delta:
                            for tc in delta["tool_calls"]:
                                tool_index += 1
                                yield _sse_chunk(chat_id, model, {
                                    "tool_calls": [{
                                        "index": tool_index,
                                        "id": tc.get("id", f"tool_{tool_index}"),
                                        "type": "function",
                                        "function": {"name": tc.get("function", {}).get("name", ""), "arguments": tc.get("function", {}).get("arguments", "")},
                                    }]
                                }, None)

                        if "finish_reason" in choice:
                            finish_reason = choice["finish_reason"]

                yield _sse_chunk(chat_id, model, {}, finish_reason)
                yield "data: [DONE]\n\n"

    except Exception as e:
        logger.exception("Streaming from inference endpoint failed")
        yield _sse_chunk(chat_id, model, {"content": f"\n\nError: {e}"}, None)
        yield _sse_chunk(chat_id, model, {}, "stop")
        yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    has_system = any(m.get("role") == "system" for m in messages)
    if not has_system:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    openai_tools = body.get("tools", [])

    if stream:
        return StreamingResponse(
            _stream_from_inference(messages, openai_tools or None, body),
            media_type="text/event-stream",
        )

    try:
        result = await call_llm(messages, openai_tools or None)
        choice = result["choices"][0]
        msg = choice["message"]
        finish_reason = choice.get("finish_reason", "stop")

        logger.info(
            "finish_reason=%s | tool_calls=%s | content_preview=%.200s",
            finish_reason, bool(msg.get("tool_calls")),
            msg.get("content", "") or "",
        )

        return JSONResponse({
            "id": result.get("id", f"chatcmpl-{uuid.uuid4().hex[:12]}"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", MODEL_NAME),
            "choices": [{"index": 0, "message": msg, "finish_reason": finish_reason}],
            "usage": result.get("usage", {}),
        })

    except Exception as e:
        logger.exception("Chat completion failed")
        return JSONResponse({
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body.get("model", MODEL_NAME),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": f"Error: {e}"}, "finish_reason": "stop"}],
            "usage": {},
        })


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
