import asyncio
from typing import Optional

# 使用仓库内模块化的 core 实现，彻底移除对根目录 copilot.py 的依赖
from app.services import copilot_reverse as RootCopilotReverse
from app.services.reverse_factory import get_reverser
from app.services.reverse_base import ReverseBase


# module-level shared proxy and lock (保留以便其他模块复用)
_shared_proxy: Optional[RootCopilotReverse.CopilotReverse] = None
_shared_lock = asyncio.Lock()


async def get_shared_proxy() -> RootCopilotReverse.CopilotReverse:
    """返回或创建一个共享的 CopilotReverse 实例（异步安全）。"""
    global _shared_proxy
    if _shared_proxy is None:
        async with _shared_lock:
            if _shared_proxy is None:
                _shared_proxy = RootCopilotReverse.CopilotReverse()
    return _shared_proxy


class AsyncCopilotAdapter:
    """
    将根目录的 CopilotReverse 包装为一个异步适配器，提供如下接口：
    - set_dynamic_data(data)
    - prepare_send_conversation()
    - send_conversation() -> 如果是 stream 返回 async generator，否则返回 dict
    此适配器会复用模块级共享的 CopilotReverse 实例，避免每次请求重复初始化浏览器。
    """

    def __init__(self, *args, **kwargs):
        # 不在这里创建浏览器实例；适配器会在 set_dynamic_data 时选择或创建具体 reverser
        self._reverser: Optional[ReverseBase] = None
        self._args = args
        self._kwargs = kwargs

    async def _ensure_reverser(self, data: dict | None = None):
        if self._reverser is None:
            # 根据请求数据选择实现（可能是 Mock/Gemini/共享 Copilot core）
            self._reverser = await get_reverser(data or {})

    async def set_dynamic_data(self, data: dict):
        # 在这里根据 data 选择 reverser
        await self._ensure_reverser(data)
        return await self._reverser.set_dynamic_data(data)

    async def prepare_send_conversation(self):
        await self._ensure_reverser({})
        return await self._reverser.prepare_send_conversation()

    async def send_conversation(self):
        await self._ensure_reverser({})
        return await self._reverser.send_conversation()

    async def close(self):
        # 关闭具体 reverser（如果有的话）
        if self._reverser and hasattr(self._reverser, "close_client"):
            try:
                await self._reverser.close_client()
            except Exception:
                pass
        return

