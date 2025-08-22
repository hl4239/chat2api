import asyncio
from typing import Optional

from aiohttp import payload

from .gemini_reverse_2 import GeminiReverse2
from .reverse_base import ReverseBase
from . import mock_copilot
from app.services import copilot_reverse
# Shared singletons for Copilot and Gemini
_shared_copilot: Optional[copilot_reverse.CopilotReverse] = None
_shared_gemini: Optional[GeminiReverse2] = None

# separate locks to avoid contention
_shared_copilot_lock = asyncio.Lock()
_shared_gemini_lock = asyncio.Lock()

async def _get_shared_copilot() -> ReverseBase:
    """Return a shared CopilotReverse singleton (async-safe)."""
    global _shared_copilot
    if _shared_copilot is None:
        async with _shared_copilot_lock:
            if _shared_copilot is None:
                _shared_copilot = copilot_reverse.CopilotReverse()
    return _shared_copilot

async def _get_shared_gemini() -> ReverseBase:
    """Return a shared GeminiReverse singleton (async-safe)."""
    global _shared_gemini
    if _shared_gemini is None:
        async with _shared_gemini_lock:
            if _shared_gemini is None:
                _shared_gemini = GeminiReverse2()
                await _shared_gemini.init()
    return _shared_gemini


async def get_reverser(data: dict) -> ReverseBase:
    """根据请求数据选择并返回合适的逆向实现实例。

    选择逻辑（优先级）:
    - 如果 data 中显式 use_mock 为 True -> 返回 MockCopilotProxy
    - 如果 data 中显式 use_gemini 为 True 或 model 名含 gemini -> 返回 GeminiReverse
    - 否则返回共享的 CopilotProxy 实例
    """
    if not isinstance(data, dict):
        data = {}

    if data.get("use_mock"):
        return mock_copilot.MockCopilotProxy()

    model = (data.get("model") or "").lower()
    # If Gemini is requested, return the shared Gemini singleton
    if data.get("use_gemini") or "gemini"  in model:
        return await _get_shared_gemini()

    # 默认使用共享 Copilot core
    return await _get_shared_copilot()
