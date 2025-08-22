# app/main.py
from fastapi import FastAPI
from app.routes import completions

# 在启动时创建共享的 CopilotProxy（可选提前初始化浏览器），在关闭时优雅关闭
from app.services.copilot_proxy import get_shared_proxy

app = FastAPI()

# 注册路由
app.include_router(completions.router)


@app.on_event("startup")
async def startup_event():
    # 触发创建共享代理（但不强制浏览器启动）。如果你希望在启动时就启动浏览器，
    # 可以在此调用 await proxy.set_dynamic_data({}) 来触发 _init_browser_and_page。
    try:
        await get_shared_proxy()
    except Exception:
        # 忽略启动时的初始化错误，运行时会按需重试
        pass


@app.on_event("shutdown")
async def shutdown_event():
    # 关闭共享代理中的浏览器/Playwright
    try:
        proxy = await get_shared_proxy()
        # 直接调用底层关闭函数，如果不存在则忽略
        if hasattr(proxy, "close_client"):
            await proxy.close_client()
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5005)
