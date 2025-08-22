import asyncio
import json
import random
import string
import time
from typing import Optional, AsyncGenerator

from app.services.browser_manager import BrowserManager
from app.services.reverse_base import ReverseBase


class GeminiReverse(ReverseBase):
    """Complete Gemini reverse implementation following the same pattern as CopilotReverse."""

    def __init__(self):
        self.TARGET_URL = "https://aistudio.google.com/app/prompts/new_chat"

        # Data and model state
        self.data = None
        self.model = None
        self.question = None

        # Browser management
        self.page = None
        self._browser_manager = None
        self._initialized = False

        # Response handling
        self.response_buffer = {"text": ""}
        self.answer_event: Optional[asyncio.Event] = None
        self._stream_mode = False
        self._stream_queue: Optional[asyncio.Queue] = None
        self.headers=None
        self.cookies = None
        # Request monitoring
        self.TARGET_REQUEST_URL = "https://alkalimakersuite-pa.clients6.google.com/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService/GenerateContent"

    async def set_dynamic_data(self, data: dict):
        """Set dynamic data and initialize browser if needed."""
        self.data = data or {}
        await self.set_model()

        if not self._initialized:
            # 初始化 shared browser 和 context
            self._browser_manager = await BrowserManager.get_instance()
            context = await self._browser_manager.new_context()
            # 新建 page 并访问目标 URL
            self.page = await context.new_page()
            await self.page.goto(self.TARGET_URL)
            # Set up response monitoring
            await self._setup_response_monitoring()
            self._initialized = True


    async def set_model(self):
        """Extract model from data."""
        self.model = (self.data or {}).get("model", "gemini-pro")

    async def prepare_send_conversation(self):
        """Prepare conversation question from messages in OpenAI format."""
        messages = self.data.get("messages", []) if isinstance(self.data, dict) else []
        system = None
        user = None

        # Extract system and user messages
        for m in messages:
            if m.get("role") == "system" and system is None:
                system = m.get("content")
            if m.get("role") == "user":
                user = m.get("content")

        if user is None:
            user = ""

        # Combine system and user messages
        if system:
            self.question = f"[System]\n{system}\n\n[User]\n{user}"
        else:
            self.question = user

        return self.question

    async def send_conversation(self, text: Optional[any] = None,payload:Optional[dict] = None):
        """Send conversation and return response based on streaming mode."""
        if not self.page:
            raise RuntimeError("Page not initialized. Call set_dynamic_data first.")

        # Determine streaming mode
        if self.data :
            self._stream_mode = bool(self.data.get("stream", False))
        else:self._stream_mode = False
        # Use provided text or prepared question
        message_text = text or self.question or "Hello Gemini!"

        if self._stream_mode:
            # Return async generator for streaming
            return self._create_stream_generator(message_text)
        else:
            # Send message and wait for complete response
            await self._send_message_and_wait(message_text)
            return {
                "question": message_text,
                "answer": self.response_buffer.get("text", "")
            }

    async def _create_stream_generator(self, message_text: str) -> AsyncGenerator[str, None]:
        """Create async generator for streaming responses."""
        await self._send_message_and_start_streaming(message_text)

        while True:
            try:
                chunk = await asyncio.wait_for(self._stream_queue.get(), timeout=30.0)
                if chunk == "__DONE__":
                    break
                # Convert to OpenAI streaming format
                async for stream_chunk in self._convert_to_openai_stream(chunk):
                    yield stream_chunk
            except asyncio.TimeoutError:
                break
            except Exception as e:
                print(f"[gemini_reverse] Stream error: {e}")
                break

        # Send final done chunk
        async for stream_chunk in self._convert_to_openai_stream(None, done=True):
            yield stream_chunk

    async def _send_message_and_wait(self, message_text: str):
        """Send message and wait for complete response."""
        self.answer_event = asyncio.Event()
        self.response_buffer["text"] = ""

        # Send the message
        success = await self._send_message(message_text)
        if not success:
            raise RuntimeError("Failed to send message")

        # Wait for response with timeout
        try:
            await asyncio.wait_for(self.answer_event.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            print("[gemini_reverse] Response timeout")

    async def _send_message_and_start_streaming(self, message_text: str):
        """Send message and prepare for streaming."""
        self.answer_event = asyncio.Event()
        self._stream_queue = asyncio.Queue()
        self.response_buffer["text"] = ""

        # Send the message
        success = await self._send_message(message_text)
        if not success:
            raise RuntimeError("Failed to send message")

    async def _send_message(self, message_text: str) -> bool:
        """Send message to Gemini interface (with aria-disabled check)."""
        try:
            # Wait for page to be ready
            await self.page.wait_for_load_state("networkidle", timeout=10000)

            # Locate textarea container and textarea
            textarea_container = self.page.locator("ms-autosize-textarea")
            await textarea_container.wait_for(state="visible", timeout=10000)

            textarea = textarea_container.locator("textarea")
            await textarea.wait_for(state="visible", timeout=5000)

            # Clear and fill textarea
            await textarea.clear()
            await textarea.fill(message_text)

            # Set data-value attribute if needed
            try:
                el_handle = await textarea_container.element_handle()
                if el_handle:
                    await el_handle.evaluate(
                        "(el, val) => el.setAttribute('data-value', val)", message_text
                    )
            except Exception as e:
                print(f"[gemini_reverse] Warning: Could not set data-value: {e}")

            # Wait briefly for UI to update
            await asyncio.sleep(1)

            # ---- 尝试用 JS evaluate 提交，检查 aria-disabled ----
            try:
                submit_result = await self.page.evaluate("""
                    () => {
                        const submitButton = document.querySelector('button[type="submit"]');
                        if (submitButton) {
                            const ariaDisabled = submitButton.getAttribute("aria-disabled");
                            if (ariaDisabled === "false") {
                                submitButton.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                if submit_result:
                    print("[gemini_reverse] Message submitted successfully via JS (aria-disabled)")
                    return True
                else:
                    print("[gemini_reverse] Submit button not found or aria-disabled != false")
            except Exception as e:
                print(f"[gemini_reverse] JS submit failed: {e}")

            # ---- fallback: Playwright locator 点击 aria-disabled="false" 的按钮 ----
            try:
                submit_button = self.page.locator('button[type="submit"][aria-disabled="false"]')
                if await submit_button.is_visible():
                    await submit_button.click()
                    print("[gemini_reverse] Message submitted via locator (aria-disabled check)")
                    return True
            except Exception as e:
                print(f"[gemini_reverse] Direct click submit failed: {e}")

            return False

        except Exception as e:
            print(f"[gemini_reverse] Error sending message: {e}")
            return False


    async def _setup_response_monitoring(self):
        """Set up monitoring for Gemini API responses."""
        if not self.page:
            return

        async def handle_response(response):
            if response.url == self.TARGET_REQUEST_URL:
                try:
                    # 获取请求对象
                    request = response.request

                    # 请求头
                    headers = request.headers
                    print("[gemini_reverse] Request headers:", headers)
                    self.headers=headers
                    # Cookie（Playwright 会把 Cookie 放在 header 中或者用 cookies API）
                    cookies = await self.page.context.cookies(request.url)
                    print("[gemini_reverse] Cookies:", cookies)
                    self.cookies = cookies
                    # 获取响应内容
                    body = await response.text()
                    response_data = json.loads(body)

                    # Extract final answer
                    answer_text = self.extract_final_answer(response_data)

                    if answer_text:
                        if self._stream_mode and hasattr(self, "_stream_queue") and self._stream_queue:
                            chunks = self._split_into_chunks(answer_text)
                            for chunk in chunks:
                                try:
                                    await self._stream_queue.put(chunk)
                                    await asyncio.sleep(0.05)
                                except Exception:
                                    pass
                            try:
                                await self._stream_queue.put("__DONE__")
                            except Exception:
                                pass

                        self.response_buffer["text"] = answer_text
                        if self.answer_event:
                            self.answer_event.set()

                        print(f"[gemini_reverse] Response received: {answer_text[:100]}...")

                except Exception as e:
                    print(f"[gemini_reverse] Error processing response: {e}")

        # Attach response listener
        self.page.on("response", handle_response)

    def _split_into_chunks(self, text: str, chunk_size: int = 10) -> list:
        """Split text into chunks for streaming simulation."""
        if not text:
            return []

        words = text.split()
        chunks = []
        current_chunk = []

        for word in words:
            current_chunk.append(word)
            if len(current_chunk) >= chunk_size:
                chunks.append(" " + " ".join(current_chunk))
                current_chunk = []

        if current_chunk:
            chunks.append(" " + " ".join(current_chunk))

        return chunks

    async def _convert_to_openai_stream(self, text: Optional[str] = None, done: bool = False,
                                        model: str = None, default_id: Optional[str] = None,
                                        default_created: Optional[int] = None) -> AsyncGenerator[str, None]:
        """Convert response to OpenAI streaming format."""
        chat_id = default_id or f"chatcmpl-{''.join(random.choices(string.ascii_letters + string.digits, k=29))}"
        created_time = default_created or int(time.time())
        model_name = model or self.model or "gemini-2.5-pro"

        base = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": created_time,
            "model": model_name,
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

    def extract_final_answer(self, data_structure):
        """
        递归地从复杂的嵌套列表中提取与 "model" 标签相关的文本片段，
        并拼接成最终的回答。

        Args:
            data_structure: 包含模型响应的嵌套列表 (已经是Python对象)。

        Returns:
            一个包含最终回答的字符串。
        """
        text_fragments = []

        def find_string_in_blob(blob):
            """在一个数据块中找到第一个出现的字符串。"""
            if isinstance(blob, str):
                return blob
            if isinstance(blob, list):
                for item in blob:
                    result = find_string_in_blob(item)
                    if result is not None:
                        return result
            return None

        def recursive_search(data):
            """递归遍历数据结构。"""
            if not isinstance(data, list):
                return

            is_model_container = "model" in data

            if is_model_container:
                for element in data:
                    if element == "model":
                        continue

                    found_text = find_string_in_blob(element)
                    if found_text:
                        text_fragments.append(found_text)
                        return
            else:
                for item in data:
                    recursive_search(item)

        recursive_search(data_structure)

        # Filter out fragments that start with ** (likely formatting)
        final_answer_fragments = [
            frag for frag in text_fragments if not frag.strip().startswith("**")
        ]

        return "".join(final_answer_fragments)



    async def close_client(self):
        """Clean up resources."""
        try:
            # Clear references without closing shared browser
            self.page = None
            self._browser_manager = None
            self._initialized = False

            # Clear event objects
            if self.answer_event:
                self.answer_event = None
            if self._stream_queue:
                self._stream_queue = None

        except Exception as e:
            print(f"[gemini_reverse] Error during cleanup: {e}")


# Test/demo code
if __name__ == "__main__":
    import sys
    import asyncio


    async def _main():
        url = sys.argv[1] if len(sys.argv) > 1 else None
        gr = GeminiReverse()

        if url:
            gr.TARGET_URL = url

        print(f"[gemini_reverse] opening: {gr.TARGET_URL}")

        try:
            # Test with sample data
            test_data = {
                "model": "gemini-pro",
                "messages": [
                    {"role": "user", "content": "请用C++实现快速排序算法"}
                ],
                "stream": False
            }

            await gr.set_dynamic_data(test_data)
            await gr.prepare_send_conversation()

            print(f"[gemini_reverse] sending question: {gr.question}")
            result = await gr.send_conversation()

            if isinstance(result, dict):
                print(f"[gemini_reverse] answer: {result.get('answer', 'No answer')}")

            else:
                print("[gemini_reverse] Got streaming generator")

        except Exception as e:
            print(f"[gemini_reverse] error during execution: {e}")
        finally:
            await asyncio.sleep(51111)  # Wait a bit before cleanup
            await gr.close_client()


    asyncio.run(_main())