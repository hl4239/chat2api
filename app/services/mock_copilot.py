import asyncio
import json
import time
import random
import string
from .reverse_base import ReverseBase


class MockCopilotProxy(ReverseBase):
    """一个轻量的模拟 Copilot 实现，用于开发和测试，不启动浏览器。"""

    def __init__(self, *args, **kwargs):
        self.data = {}
        self.question = ""

    async def set_dynamic_data(self, data: dict):
        self.data = data or {}
        self.model = self.data.get("model", "copilot-chat")

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
                text = self.data.get("mock_text") or "这是模拟流式回复。"
                # 按词或字符切分更自然
                for ch in text:
                    await asyncio.sleep(0.01)
                    # 构造与 core 相同的 SSE data 块
                    base = {
                        "id": f"chatcmpl-{''.join(random.choices(string.ascii_letters + string.digits, k=29))}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": self.model,
                        "choices": [{"index": 0, "delta": {"content": ch}, "logprobs": None, "finish_reason": None}]
                    }
                    yield f"data: {json.dumps(base)}\n\n"
                # done
                base = {
                    "id": f"chatcmpl-{''.join(random.choices(string.ascii_letters + string.digits, k=29))}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": self.model,
                    "choices": [{"index": 0, "delta": {}, "logprobs": None, "finish_reason": "stop"}]
                }
                yield f"data: {json.dumps(base)}\n\n"
                yield "data: [DONE]\n\n"
            return gen()
        else:
            answer = self.data.get("mock_text") or "这是模拟非流式回复。"
            return {"question": self.question, "answer": answer, "id": "cmpl-mock-1"}

    async def close_client(self):
        return
