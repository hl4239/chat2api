import asyncio
import os
import subprocess
from typing import Optional
from playwright.async_api import async_playwright
from app.config.settings import get_user_data_dir

# sensible defaults
DEFAULT_CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEFAULT_DEBUG_PORT = "9999"


class BrowserManager:
    """全局单例的浏览器管理器。

    责任：启动/连接底层浏览器（通过 CDP），维护 playwright/browser/context 实例，并提供创建 page 的方法。
    设计要点：
    - 全局单例（跨多个 reverse 实例共享）
    - 异步初始化（保证仅初始化一次）
    - 提供 new_page(url=None) 创建独立 page
    """

    _instance = None
    _instance_lock = asyncio.Lock()

    def __init__(self):
        # apply defaults if caller didn't provide values
        self.CHROME_PATH =  DEFAULT_CHROME_PATH
        self.DEBUG_PORT =  DEFAULT_DEBUG_PORT
       
        self.USER_DATA_DIR = os.path.abspath(get_user_data_dir())
        self.CDP_URL = f"http://localhost:{self.DEBUG_PORT}"

        self.playwright = None
        self.browser = None
        self.context = None
        self._chrome_proc = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    @classmethod
    async def get_instance(cls, chrome_path: Optional[str] = None, debug_port: Optional[str] = None, user_data_dir: Optional[str] = None):
        """Get or create the global BrowserManager singleton.

        Optional overrides may be provided when the singleton is first created. If the
        singleton already exists, any provided overrides will be ignored.
        """
        # simple double-checked locking to avoid races

        if cls._instance is None:

            async with cls._instance_lock:
                if cls._instance is None:
                    mgr = BrowserManager()

                    # apply any provided overrides before starting the browser
                    if chrome_path:
                        mgr.CHROME_PATH = chrome_path
                    if debug_port:
                        mgr.DEBUG_PORT = debug_port
                    if user_data_dir:
                        mgr.USER_DATA_DIR = os.path.abspath(user_data_dir)

                    # update dependent CDP URL in case debug port changed
                    mgr.CDP_URL = f"http://localhost:{mgr.DEBUG_PORT}"

                    await mgr._ensure_started()
                    cls._instance = mgr
        return cls._instance

    async def _ensure_started(self):
        async with self._init_lock:
            if self._initialized:
                return

            os.makedirs(self.USER_DATA_DIR, exist_ok=True)
            cmd = (
                f'"{self.CHROME_PATH}" --remote-debugging-port={self.DEBUG_PORT}'
                f' --user-data-dir="{self.USER_DATA_DIR}" --no-first-run --no-default-browser-check'
            )
            # start chrome in background
            try:
                self._chrome_proc = subprocess.Popen(cmd, shell=True)
            except Exception:
                # best-effort: even if launching fails, try to connect (user may have started chrome manually)
                self._chrome_proc = None

            # give chrome some time to start and open CDP
            await asyncio.sleep(1.5)

            # start playwright and connect over CDP
            self.playwright = await async_playwright().start()
            # connect_over_cdp will attach to the running chrome instance
            self.browser = await self.playwright.chromium.connect_over_cdp(self.CDP_URL)

            # reuse an existing context if available, else create a new one
            if getattr(self.browser, "contexts", None) and len(self.browser.contexts) > 0:
                self.context = self.browser.contexts[0]
            else:
                self.context = await self.browser.new_context()

            self._initialized = True

    async def new_page(self, url: Optional[str] = None, route_overrides: Optional[list] = None):
        """Create a new page bound to the shared context. Optionally navigate to url.

        route_overrides: list of callables that receive a Playwright page and register
        route handlers on it. This allows callers to inject request/response interception
        logic when the page is created.
        """
        if not self._initialized:
            await self._ensure_started()
        page = await self.context.new_page()

        # apply any provided route override functions
        if route_overrides:
            for ro in route_overrides:
                try:
                    await ro(page)
                except Exception:
                    # best-effort: don't fail page creation if override errors
                    pass

        if url:
            try:
                await page.goto(url)
            except Exception:
                # navigation is best-effort here; caller may handle retries
                pass
        return page

    async def new_context(self):
        """Return the shared context (ensure browser started).

        Callers may register context-level routes (e.g. to intercept service worker
        requests) before creating pages from the context.
        """
        if not self._initialized:
            await self._ensure_started()
        return self.context

    async def close(self):
        """Stop playwright and try to terminate the chrome process. This will shut down the shared browser."""
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass

        try:
            if self._chrome_proc:
                self._chrome_proc.terminate()
        except Exception:
            pass

        self._initialized = False
