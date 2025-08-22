import hashlib
import json

import aiohttp
import httpx
import sys
import asyncio
from app.services.browser_manager import BrowserManager
from app.services.gemini_reverse import GeminiReverse
from typing import List, Optional, Union

from app.utils.JSObfuscatedProcessor import JSObfuscatedProcessor


class ConversationBuilder:
    def __init__(
            self,
            model: str,
            conversations: List[dict],
            system_prompt: str,
            checksum: Optional[Union[str, int]] = None
    ):
        """
        :param model: 模型名，比如 "models/gemini-2.5-pro"
        :param conversations: 对话列表，例如：
            [
                {"role": "user", "content": "你好"},
                {"role": "model", "content": "回复：你好"},
                {"role": "user", "content": "你好1"}
            ]
        :param system_prompt: 系统提示词，例如 "系统prompt"
        :param checksum: 对话list的校验值，可以是 None / str / int
        """
        self.model = model
        self.conversations = conversations
        self.system_prompt = system_prompt
        self.checksum = checksum

    def build(self):
        """构造最终的 data 结构"""
        return [
            f'models/{self.model}',
            [  # 对话 list
                [
                    [[None, c["content"]]],
                    c["role"]
                ] for c in self.conversations
            ],
            [  # 未知，留存（固定值）
                [None, None, 7, 5],
                [None, None, 8, 5],
                [None, None, 9, 5],
                [None, None, 10, 5]
            ],
            [  # ai 生成的配置 list（固定值）
                None,
                None,
                None,
                65536,
                1,
                0.95,
                64,
                None,
                None,
                None,
                None,
                None,
                None,
                1,
                None,
                None,
                [1, -1]
            ],
            self.checksum,  # 对话 list 的校验值

            [  # 系统提示词
                [
                    [None, self.system_prompt if self.system_prompt is not None else ""]
                ],
                "user"
            ],
            [  # 未知，留存（固定值）
                [None, None, None, []]
            ],
            None,
            None,
            None,
            1

        ]


class GeminiReverse2(GeminiReverse):
    """Complete Gemini reverse implementation following the same pattern as CopilotReverse."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TARGET_URL = "https://aistudio.google.com/app/prompts/new_chat"
        self.request_url = "https://alkalimakersuite-pa.clients6.google.com/$rpc/google.internal.alkali.applications.makersuite.v1.MakerSuiteService/GenerateContent"
        # Data and model state
        self.system_prompt = None
        self.conversations = None
        self.digest = None
        self.captured_js_vars = None
        self.lock= asyncio.Lock()

    async def init(self):
        if not self._initialized:
            self._browser_manager = await BrowserManager.get_instance()
            context = await self._browser_manager.new_context()

            # ******************* 核心修改部分 *******************
            async def handle_route(route, request):
                url = request.url

                try:
                    # 我们只关心目标JS文件
                    if "gstatic.com/_/mss/boq-makersuite/_/js" in url and url.endswith("m=_b"):
                        print(f"[DEBUG] Matched target JS for modification: {url}")

                        # 1. 继续原始请求，获取真实的响应
                        response = await route.fetch()
                        original_js_code = await response.text()
                        print(f"[DEBUG] Fetched original JS, size: {len(original_js_code)} bytes.")

                        # 2. 使用处理器在内存中修改JS代码
                        js_processor = JSObfuscatedProcessor()
                        modified_code, captured_data = js_processor.process_and_get_modified_string(
                            original_js_code)

                        # 3. 如果修改成功...
                        if modified_code and captured_data:
                            print(f"[SUCCESS] JS code modified. Captured vars: {captured_data}")
                            # 将捕获的变量名存储在类实例中，供后续使用
                            self.captured_js_vars = captured_data

                            # 用修改后的代码完成请求
                            await route.fulfill(
                                status=response.status,
                                headers=response.headers,  # 保持原始头信息
                                body=modified_code,
                            )
                            return  # 处理完成，退出

                        # 4. 如果修改失败...
                        else:
                            print(
                                "[WARNING] JS processing failed. Serving original content to avoid breaking the page.")
                            # 仍然用原始代码完成请求，确保页面能加载
                            await route.fulfill(
                                status=response.status,
                                headers=response.headers,
                                body=original_js_code,
                            )
                            return

                except Exception as e:
                    print(f"[ERROR] handle_route exception: {e}")

                # 对于所有其他不匹配的请求，正常继续
                await route.continue_()

            # ******************* 修改结束 *******************

            await context.route("**://www.gstatic.com/**", handle_route)

            self.page = await context.new_page()
            await self.page.goto(self.TARGET_URL)

            await self._setup_response_monitoring()
            await super().send_conversation('你好')
            self._initialized = True

            # 示例：检查捕获到的变量
            if self.captured_js_vars:
                print("\n--- 动态捕获的JS变量可供使用 ---")
                print(self.captured_js_vars)
                # 在这里，您可以构建并执行您的eval脚本
            else:
                print("\n--- 未能捕获JS变量 ---")

    async def set_dynamic_data(self, data: dict):
        self.data = data or {}
        await self.set_model()
        if not self._initialized:
            await self.init()


    async def set_model(self):
        """Extract model from data."""
        self.model = (self.data or {}).get("model", "gemini-2.5-pro")

    async def prepare_send_conversation(self):
        """Prepare conversation question from messages in OpenAI format."""
        messages = self.data.get("messages", []) if isinstance(self.data, dict) else []

        conversations = []
        system_prompt = None

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                # 系统提示词
                system_prompt = content
                continue

            if role == "user":
                conversations.append({
                    'role': 'user',
                    'content': content,
                })
            elif role == "assistant":
                conversations.append({
                    'role': 'model',
                    'content': content,
                })
            # else:
            #     # 兼容 tool / function 等情况
            #     conversations.append([
            #         [[None, f"[{role}] {content}"]],
            #         "user"
            #     ])

        self.conversations = conversations
        self.system_prompt = system_prompt

        await self.crypto_conversation()

    async def send_conversation(self, text: Optional[any] = None,payload:Optional[dict] = None):
        print(f'send_conversation| payload:{json.dumps(payload,indent=2)}')
        async with self.lock:
            await self.set_dynamic_data(payload)
            await self.prepare_send_conversation()
            body = ConversationBuilder(self.model, self.conversations, self.system_prompt, self.digest).build()
            stream=bool(self.data.get("stream", False))
        print(json.dumps(body, indent=4))
        cookie_dict = {c["name"]: c["value"] for c in self.cookies}
        self.headers.update({
            "x-browser-channel": "stable",
            "x-browser-year": "2025",
            "x-browser-validation": "XPdmRdCCj2OkELQ2uovjJFk6aKA=",
            "x-browser-copyright": "Copyright 2025 Google LLC. All rights reserved."
        })
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(
                    self.request_url,
                    json=body,  # 把 list/dict 转成 JSON 字符串
                    headers=self.headers,

                    timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                text = await response.text()
                print(text)
                try:
                    json_result= await response.json()
                    str_result= self.extract_final_answer(json_result)

                    if stream==False:
                        return {
                            "id":'1',
                            "question": '',
                            "answer": str_result
                        }
                    else:
                        return self.mock_stream(str_result)
                except Exception as e:
                    print(e)
                    return None

    async def mock_stream(self,text):
        for chunk in self._split_into_chunks(text):
            async for stream_chunk in self._convert_to_openai_stream(chunk):
                yield stream_chunk
        async for stream_chunk in self._convert_to_openai_stream(None, done=True):
            yield stream_chunk


    async def crypto_conversation(self):
        # 计算 SHA-256 hash
        chat_text = []
        for conv in self.conversations:
            chat_text.append(conv['content'])
        conversation_text = " ".join(chat_text)
        sha256_hash = hashlib.sha256(conversation_text.encode("utf-8")).hexdigest()
        print("计算后的 SHA-256:", sha256_hash)

        # 放入 evaluate 的 JS 脚本中
        js_script = f"""
            async () => {{
                let y = await {f"MY_{self.captured_js_vars['func_name'].upper()}"}({f"MY_{self.captured_js_vars['prop_name'].upper()}"}, "{sha256_hash}");
                return y;
            }}
        """

        result = await self.page.evaluate(js_script)
        print("Python拿到的结果:", result)
        self.digest = result
        return result


# Test/demo code
if __name__ == "__main__":



    async def _main():
        url = sys.argv[1] if len(sys.argv) > 1 else None
        gr = GeminiReverse2()

        if url:
            gr.TARGET_URL = url

        print(f"[gemini_reverse] opening: {gr.TARGET_URL}")

        test_data = {
            "model": "gemini-2.5-pro",
            "messages": [
                {"role": "user", "content": "hello!"}
            ],
            "stream": False
        }


        result = await gr.send_conversation()

        await asyncio.sleep(51111)  # Wait a bit before cleanup
        await gr.close_client()


    asyncio.run(_main())
