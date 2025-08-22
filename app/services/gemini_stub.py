import asyncio
import time
import random
import string
from .reverse_base import ReverseBase

class GeminiReverse(ReverseBase):
    """Gemini 2.5 Pro 的占位实现（用于快速切换和测试）。

    目前为轻量模拟：支持 stream 与非 stream 两种模式，行为类似 MockCopilotProxy。
    """

    def __init__(self, *args, **kwargs):
        self.data = {}
        self.question = ""
        self.model = "gemini-2.5pro"

    async def set_dynamic_data(self, data: dict):
        self.data = data or {}
        self.model = self.data.get("model", self.model)

    async def prepare_send_conversation(self):
        messages = self.data.get("messages", [])
        system = None
        user = None
        for m in messages:
            if m.get("role") == "system" and system is None:
                system = m.get("content")
            if m.get("role") == "user":
                user = m.get("content")
        if user is None:
            user = ""
        if system:
            self.question = f"[System]\n{system}\n\n[User]\n{user}"
        else:
            self.question = user
        return self.question

    async def send_conversation(self):
        stream = bool(self.data.get("stream", False))
        if stream:
            async def gen():
                text = self.data.get("mock_text") or "这是 Gemini 2.5 Pro 的模拟流式回复。"
                for ch in text:
                    await asyncio.sleep(0.01)
                    base = {
                        "id": f"chatcmpl-{''.join(random.choices(string.ascii_letters + string.digits, k=29))}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": self.model,
                        "choices": [{"index": 0, "delta": {"content": ch}, "logprobs": None, "finish_reason": None}]
                    }
                    yield f"data: {__import__('json').dumps(base)}\n\n"
                base = {
                    "id": f"chatcmpl-{''.join(random.choices(string.ascii_letters + string.digits, k=29))}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": self.model,
                    "choices": [{"index": 0, "delta": {}, "logprobs": None, "finish_reason": "stop"}]
                }
                yield f"data: {__import__('json').dumps(base)}\n\n"
                yield "data: [DONE]\n\n"
            return gen()
        else:
            answer = self.data.get("mock_text") or "这是 Gemini 2.5 Pro 的模拟非流式回复。"
            return {"question": self.question, "answer": answer, "id": "gemini-mock-1"}

    async def close_client(self):
        return
