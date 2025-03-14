import json
import random
import string
import time



from api.models import model_proxy
from chatgpt.ChatService import ChatService

from chatgpt.fp import get_fp
from utils.Client import Client
from utils.Logger import logger
from utils.configs import oai_language


class TencentProxy(ChatService):
    def __init__(self,cookie,dynamic_data):
        self.cookie=cookie
        self.dynamic_data=dynamic_data
    async def set_dynamic_data(self, data):
        self.host_url="https://yuanbao.tencent.com"
        self.base_url=self.host_url+"/api/chat/"+self.dynamic_data
        self.fp = get_fp(self.cookie).copy()
        self.proxy_url = self.fp.pop("proxy_url", None)
        self.impersonate = self.fp.pop("impersonate", "safari15_3")
        self.user_agent = self.fp.get("user-agent",
                                      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0")
        logger.info(f"Request cookie: {self.cookie}")
        logger.info(f"Request proxy: {self.proxy_url}")
        logger.info(f"Request UA: {self.user_agent}")
        logger.info(f"Request impersonate: {self.impersonate}")

        self.data = data
        await self.set_model()

        self.base_headers = {
            'accept': '*/*',
            'accept-encoding': 'gzip, deflate, br, zstd',
            'accept-language': 'en-US,en;q=0.9',
            'content-type': 'application/json',
            'oai-language': oai_language,
            'origin': self.host_url,
            'priority': 'u=1, i',
            'referer': f'{self.host_url}/',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'Cookie': self.cookie
        }
        self.base_headers.update(self.fp)
        self.s = Client(proxy=self.proxy_url, impersonate=self.impersonate)

        return

    async def set_model(self):
        self.origin_model = self.data.get("model", "deepseek-v3")
        self.resp_model = model_proxy.get(self.origin_model, self.origin_model)

        if "deepseek-v3" in self.origin_model:
            self.req_model = "deep_seek_v3"
        elif "deepseek-R1" in self.origin_model:
            self.req_model = "deep_seek"
        else:
            self.req_model = "deep_seek_v3"
    async def prepare_send_conversation(self):
        reqbody = {
            "model": "gpt_175B_0404",
            "prompt": self.data["messages"][-1]["content"],
            "plugin": "Adaptive",
            "displayPrompt":self.data["messages"][-1]["content"],
            "displayPromptType": 1,
            "options": {
                "imageIntention": {
                    "needIntentionModel": True,
                    "backendUpdateFlag": 2,
                    "intentionStatus": True
                }
            },
            "multimedia": [],
            "agentId": "naQivTmsDa",
            "supportHint": 1,
            "version": "v2",
            "chatModelId": self.req_model,
        }
        self.chat_request=reqbody
        return self.chat_request
    async def send_conversation(self):
        try:
            r = await self.s.post_stream(self.base_url, headers=self.base_headers, json=self.chat_request, timeout=10, stream=True)
            if r.status_code != 200:
                logger.error("响应错误："+r.status_code)
            else:
                return convert_to_openai_stream(r.aiter_lines(),self.resp_model)
                # # 处理流式响应
                # async for chunk in r.aiter_lines():
                #     print(chunk.decode('utf-8')+"-----------")  # 假设响应是文本数据
        except Exception as e:
            logger.error(e)
    async def close_client(self):
        if self.s:
            await self.s.close()
            del self.s

async def convert_to_openai_stream(input_stream, model="gpt-3.5-turbo", default_id=None, default_created=None):
    """将自定义格式的流转换为 OpenAI 兼容的流式格式"""

    # 生成默认值
    chat_id = default_id or f"chatcmpl-{''.join(random.choices(string.ascii_letters + string.digits, k=29))}"
    created_time = default_created or int(time.time())

    # 初始化状态
    accumulated_content = []
    finish_reason = None
    response_data = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created_time,
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {},
            "logprobs": None,
            "finish_reason": None
        }]
    }

    async for line in input_stream:
        line=line.decode('utf-8')
        # 跳过非数据行和特殊事件
        if not line.startswith("data: ") or "event: " in line:
            continue

        data = line[6:].strip()

        # 处理结束标记
        if data == "[DONE]":

            break
        elif "{"  not in data:
            continue
        try:
            # 解析 JSON 数据
            parsed = json.loads(data)

            # 只处理文本类型数据
            if parsed.get("type") == "text" and "msg" in parsed:
                # 累加文本内容
                accumulated_content.append(parsed["msg"])

                # 构建增量内容
                delta = {"content": parsed["msg"]}

                # 构造响应块
                response_data["choices"][0]["delta"] = delta
                response_data["choices"][0]["finish_reason"] = None

                yield f"data: {json.dumps(response_data)}\n\n"

            # 处理元数据
            elif parsed.get("type") == "meta":
                # 这里可以添加元数据到系统指纹等字段
                response_data.setdefault("system_fingerprint", parsed.get("pluginID", "unknown"))

        except json.JSONDecodeError:
            # 处理非 JSON 数据行（如 [TRACEID...]）
            if "[TRACEID:" in data:
                response_data["system_fingerprint"] = data.split(":")[1].strip("]")
            continue

    # 最终完成块
    if accumulated_content:
        response_data["choices"][0]["delta"] = {}
        response_data["choices"][0]["finish_reason"] = "stop"
        yield f"data: {json.dumps(response_data)}\n\n"

    yield "data: [DONE]\n\n"



