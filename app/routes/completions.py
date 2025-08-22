# app/routes/completions.py
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
import asyncio
import time

from app.services.reverse_factory import get_reverser
router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI Chat Completions compatible endpoint.

    Accepts JSON with at least `model` and `messages` (list of {role, content}).
    Supports `stream: true` to return SSE of delta chunks.
    """
    payload = await request.json()
    reverser = await get_reverser(payload)


    if payload.get("stream"):
        async def gen():
            stream = await reverser.send_conversation(payload=payload)
            async for chunk in stream:
                # chunk already in SSE data: ... but ensure OpenAI-style deltas if needed
                yield chunk

        return StreamingResponse(gen(), media_type="text/event-stream")
    else:
        result = await reverser.send_conversation(payload=payload)
        # Map to OpenAI chat completion schema
        # 封装为 OpenAI Chat Completions 响应
        resp = {
            "id": result.get("id",'chatcmpl-unknown') or "chatcmpl-unknown",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model", "copilot-chat"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": result.get("answer", "")},
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": result.get("prompt_tokens", 10),
                "completion_tokens": result.get("completion_tokens", 10),
                "total_tokens": result.get("total_tokens", 1110)
            }
        }

        return JSONResponse(resp)

@router.get("/v1/models")
async def models():
    return {
    "object": "list",
    "data": [
        {
                "id": "gemini-2.5-pro",
                "object": "model",
                "owned_by": "custom",
                "permission": [
                    {
                        "id": "perm-gemini-pro",
                        "object": "model_permission",
                        "allow_create_engine": True,
                        "allow_sampling": True,
                        "allow_logprobs": True,
                        "allow_search_indices": False,
                        "allow_view": True,
                        "allow_fine_tuning": False,
                        "organization": "*",
                        "group": None,
                        "is_blocking": False
                    }
                ],
                "root": "gemini-2.5-pro",
                "parent": None
            },
            {
                "id": "gemini-2.5-flash",
                "object": "model",
                "owned_by": "custom",
                "permission": [
                    {
                        "id": "perm-gemini-flash",
                        "object": "model_permission",
                        "allow_create_engine": True,
                        "allow_sampling": True,
                        "allow_logprobs": True,
                        "allow_search_indices": False,
                        "allow_view": True,
                        "allow_fine_tuning": False,
                        "organization": "*",
                        "group": None,
                        "is_blocking": False
                    }
                ],
                "root": "gemini-2.5-flash",
                "parent": None
            }
        ]
    }

