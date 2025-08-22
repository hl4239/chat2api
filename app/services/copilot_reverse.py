import asyncio
import os
import json
import random
import string
import time
from typing import Optional
from .reverse_base import ReverseBase
from playwright.async_api import expect
from app.config.settings import get_user_data_dir
from .browser_manager import BrowserManager
try:
    from app.config.model_mode_map import get_mode_title_for_model
except Exception:
    # optional module; fallback will use built-in mapping
    get_mode_title_for_model = None


class CopilotReverse(ReverseBase):
    """精简并模块化的 Copilot 逆向代理核心。

    注意：本类保留原有异步方法签名，实际运行会启动 Playwright/Chrome。
    在测试时可以替换或模拟此类。
    """

    def __init__(
        self,

    ):

        # 使用与原始实现相同的默认聊天路径以确保页面结构一致
        self.TARGET_URL = "https://copilot.microsoft.com/chats/JLDP8MzTohjW4As65Vv9W"

        self.data = None
        self.model = None
        self.question = None

        # Playwright related state (page only; browser lifecycle is managed by BrowserManager)
        self.page = None
        self._browser_manager = None

        # streaming buffer
        self.ws_message_buffer = {"text": ""}
        self.answer_event: Optional[asyncio.Event] = None
        self._initialized = False
        self._stream_mode = False

    async def set_dynamic_data(self, data: dict):
        self.data = data or {}
        await self.set_model()
        if not self._initialized:
            # initialize shared browser (singleton) and create a page for this Copilot instance
            self._browser_manager = await BrowserManager.get_instance()
            # create a page and navigate to target url
            self.page = await self._browser_manager.new_page(self.TARGET_URL)
            # attach websocket listener on the new page
            self._attach_ws_listener()
            self._initialized = True
        # 尝试根据传入数据自动切换聊天模式（优先使用显式提供的 mode_title）
        try:
            mode_title = self.data.get("mode_title") if isinstance(self.data, dict) else None
            if mode_title:
                await self._select_mode_by_title(mode_title)
            else:
                mapped = self._map_model_to_title(self.model)
                if mapped:
                    await self._select_mode_by_title(mapped)
        except Exception:
            pass

    async def set_model(self):
        self.model = (self.data or {}).get("model", "copilot-chat")

    async def prepare_send_conversation(self):
        # 按 OpenAI 风格消息构造最终问题
        messages = self.data.get("messages", []) if isinstance(self.data, dict) else []
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

    async def send_conversation(self, text: Optional[any] = None,payload:Optional[dict] = None):
        await  self.set_dynamic_data(payload)
        await self.prepare_send_conversation()
        self._stream_mode = bool(self.data.get("stream", False))

        if self._stream_mode:
            async def stream_gen():
                await self._send_and_start_streaming()
                while True:
                    chunk = await self._stream_queue.get()
                    if chunk == "__DONE__":
                        break
                    # yield SSE formatted chunks
                    async for s in self._convert_to_openai_stream_copilot_single(chunk):
                        yield s
                async for s in self._convert_to_openai_stream_copilot_single(None, done=True):
                    yield s

            return stream_gen()

        else:
            await self._send_and_wait_queue()
            return {"question": self.question, "answer": self.ws_message_buffer.get("text", "")}

    async def _init_browser_and_page(self):
        # 浏览器初始化现在由 BrowserManager 管理；保留此方法以兼容历史调用
        return

    def _attach_ws_listener(self):
        """Attach websocket frame listener to self.page (extracted from previous implementation)."""
        if not self.page:
            return

        def on_ws(ws):
            def handle_frame(frame):
                try:
                    data = json.loads(frame)
                    if data.get("event") == "appendText":
                        chunk = data.get("text", "")
                        self.ws_message_buffer["text"] += chunk
                        if hasattr(self, "_stream_queue") and self._stream_mode:
                            try:
                                self._stream_queue.put_nowait(chunk)
                            except Exception:
                                pass
                    if data.get("event") == "done":
                        if hasattr(self, "_stream_queue") and self._stream_mode:
                            try:
                                self._stream_queue.put_nowait("__DONE__")
                            except Exception:
                                pass
                        if self.answer_event:
                            self.answer_event.set()
                except Exception:
                    pass

            ws.on("framereceived", handle_frame)

        try:
            self.page.on("websocket", on_ws)
        except Exception:
            pass
        # try to ensure page has navigated to target
        try:
            asyncio.create_task(self.page.goto(self.TARGET_URL))
        except Exception:
            pass

    async def _send_and_start_streaming(self):
        self.answer_event = asyncio.Event()
        self._stream_queue = asyncio.Queue()
        self.ws_message_buffer["text"] = ""

        await self.page.fill('textarea#userInput', self.question)
        await self.page.click('button[data-testid="submit-button"]')

    async def _send_and_wait_queue(self):
        self.answer_event = asyncio.Event()
        self._stream_queue = asyncio.Queue()
        self.ws_message_buffer["text"] = ""

        await self.page.fill('textarea#userInput', self.question)
        await self.page.click('button[data-testid="submit-button"]')
        await self.answer_event.wait()

    async def _convert_to_openai_stream_copilot_single(self, text=None, done=False, model: str = "copilot-chat", default_id: Optional[str] = None, default_created: Optional[int] = None):
        chat_id = default_id or f"chatcmpl-{''.join(random.choices(string.ascii_letters + string.digits, k=29))}"
        created_time = default_created or int(time.time())
        base = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created_time,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "logprobs": None, "finish_reason": None}],
        }
        if text:
            base["choices"][0]["delta"] = {"content": text}
            yield f"data: {json.dumps(base)}\n\n"
        if done:
            base["choices"][0]["delta"] = {}
            base["choices"][0]["finish_reason"] = "stop"
            yield f"data: {json.dumps(base)}\n\n"
            yield "data: [DONE]\n\n"

    def _map_model_to_title(self, model_name: str):
        # 委托到配置模块进行映射
        return get_mode_title_for_model(model_name)

    async def _select_mode_by_title(self, title: str, timeout: int = 5000) -> bool:
        """
        在页面中根据 title 切换聊天模式。
        返回 True 表示成功（或已处于目标模式），False 表示失败。
        """
        if not title or not hasattr(self, "page") or self.page is None:
            return False

        try:
            print(f"[mode] try select mode: {title}")
            switcher_button = self.page.locator('button[data-testid="chat-mode-switcher"]')
            await switcher_button.wait_for(state="visible", timeout=timeout)

            aria_expanded = await switcher_button.get_attribute("aria-expanded")
            print(f"[mode] switcher aria-expanded={aria_expanded}")
            if aria_expanded == "false":
                await switcher_button.click()
                await expect(switcher_button).to_have_attribute("aria-expanded", "true", timeout=timeout)

            menu_container = self.page.locator('div[data-testid="composer-mode-menu"]')
            await menu_container.wait_for(state="visible", timeout=2000)

            testid_map = {
                "快速响应": "chat-mode-option",
                "Think Deeper": "reasoning-mode-option",
                "Smart (GPT-5)": "smart-mode-option",
            }

            target_testid = testid_map.get(title)
            if not target_testid:
                print(f"[mode] no mapping for title: {title}")
                return False

            mode_button = self.page.locator(f'button[data-testid="{target_testid}"]')
            await mode_button.wait_for(state="visible", timeout=2000)

            aria_checked = await mode_button.get_attribute("aria-checked")
            print(f"[mode] mode button aria-checked={aria_checked}")
            if aria_checked == "true":
                print(f"[mode] already selected: {title}")
                return True

            await mode_button.click()
            print(f"[mode] clicked mode button: {title}")

            try:
                await expect(switcher_button).to_have_attribute("aria-expanded", "false", timeout=2000)
            except Exception:
                pass

            return True

        except Exception as e:
            print(f"[mode] select error: {e}")
            return False

    async def close_client(self):
        # 关闭由 BrowserManager 管理的资源时建议调用 manager.close()（可选）
        try:
            if self._browser_manager:
                # Do not force-close shared browser here unless intended. If you want to close shared browser,
                # uncomment the next line. For now we simply clear references.
                # await self._browser_manager.close()
                self._browser_manager = None
        except Exception:
            pass

