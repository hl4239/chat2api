from typing import Optional


class ReverseBase:
    """抽象基类：逆向模块的统一接口。

    实现类需提供异步方法：
    - set_dynamic_data(data: dict)
    - prepare_send_conversation()
    - send_conversation()
    - close_client()
    """

    async def set_dynamic_data(self, data: dict):
        raise NotImplementedError()

    async def prepare_send_conversation(self):
        raise NotImplementedError()

    async def send_conversation(self, text: Optional[any] = None,payload:Optional[dict] = None):
        raise NotImplementedError()

    async def close_client(self):
        raise NotImplementedError()
