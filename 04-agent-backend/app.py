import json
import logging
import os
import time
import uuid

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from sandbox_executor import create_client, execute_code

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM Sandbox Agent")

VLLM_BASE_URL = os.environ.get(
    "VLLM_BASE_URL", "http://code-llm-predictor:8080"
)
MODEL_NAME = os.environ.get("MODEL_NAME", "code-llm")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "2048"))

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_code",
            "description": (
                "Execute code in a secure sandbox environment. "
                "Use this whenever the user asks you to run, execute, or test code. "
                "The sandbox has Python (with numpy, pandas, scipy, sympy, matplotlib), "
                "Bash, and Node.js available."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "enum": ["python", "bash", "javascript"],
                        "description": "Programming language of the code",
                    },
                    "code": {
                        "type": "string",
                        "description": "The code to execute",
                    },
                },
                "required": ["language", "code"],
            },
        },
    }
]

SYSTEM_PROMPT = (
    "You are a helpful coding assistant with the ability to execute code in a "
    "secure sandbox. When the user asks you to write code, generate it and then "
    "use the execute_code tool to run it so you can show the results. "
    "Always run the code after generating it, unless the user explicitly says not to. "
    "If the code produces an error, analyze the error, fix the code, and try again. "
    "Available languages: Python (with numpy, pandas, scipy, sympy, matplotlib), Bash, JavaScript."
)

sandbox_client = None


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


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "openshift-ai",
            }
        ],
    }


@app.get("/v1/models/{model_id}")
async def get_model(model_id: str):
    return {
        "id": MODEL_NAME,
        "object": "model",
        "created": int(time.time()),
        "owned_by": "openshift-ai",
    }


def build_vllm_payload(messages: list, stream: bool) -> dict:
    has_system = any(m.get("role") == "system" for m in messages)
    if not has_system:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages

    return {
        "model": MODEL_NAME,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_tokens": MAX_TOKENS,
        "temperature": 0.1,
        "stream": stream,
    }


async def call_vllm(payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{VLLM_BASE_URL}/v1/chat/completions", json=payload
        )
        resp.raise_for_status()
        return resp.json()


def handle_tool_calls(tool_calls: list, messages: list) -> list:
    messages = list(messages)
    for tc in tool_calls:
        fn = tc["function"]
        try:
            args = json.loads(fn["arguments"])
        except (json.JSONDecodeError, TypeError):
            args = {"language": "python", "code": fn.get("arguments", "")}

        logger.info(
            "Executing %s code in sandbox (%d chars)",
            args.get("language", "python"),
            len(args.get("code", "")),
        )

        result = execute_code(
            get_sandbox_client(),
            args.get("language", "python"),
            args.get("code", ""),
        )

        output_parts = []
        if result["stdout"]:
            output_parts.append(f"Output:\n{result['stdout']}")
        if result["stderr"]:
            output_parts.append(f"Errors:\n{result['stderr']}")
        if result["exit_code"] != 0:
            output_parts.append(f"Exit code: {result['exit_code']}")
        if not output_parts:
            output_parts.append("Code executed successfully (no output).")

        tool_result = "\n\n".join(output_parts)

        messages.append(
            {
                "role": "assistant",
                "tool_calls": [tc],
                "content": None,
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": tool_result,
            }
        )
    return messages


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    max_tool_rounds = 5
    for _ in range(max_tool_rounds):
        payload = build_vllm_payload(messages, stream=False)
        result = await call_vllm(payload)

        choice = result["choices"][0]
        msg = choice["message"]

        if msg.get("tool_calls"):
            messages = handle_tool_calls(msg["tool_calls"], messages)
            continue

        if stream:
            return StreamingResponse(
                stream_final_response(msg.get("content", ""), body),
                media_type="text/event-stream",
            )
        return JSONResponse(wrap_response(msg.get("content", ""), body))

    if stream:
        return StreamingResponse(
            stream_final_response(messages[-1].get("content", ""), body),
            media_type="text/event-stream",
        )
    return JSONResponse(wrap_response(messages[-1].get("content", ""), body))


def wrap_response(content: str, original_body: dict) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": original_body.get("model", MODEL_NAME),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


async def stream_final_response(content: str, original_body: dict):
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    model = original_body.get("model", MODEL_NAME)

    chunk_start = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
        ],
    }
    yield f"data: {json.dumps(chunk_start)}\n\n"

    chunk_size = 20
    for i in range(0, len(content), chunk_size):
        chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content[i : i + chunk_size]},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk)}\n\n"

    chunk_end = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    }
    yield f"data: {json.dumps(chunk_end)}\n\n"
    yield "data: [DONE]\n\n"


@app.get("/health")
async def health():
    return {"status": "ok"}
