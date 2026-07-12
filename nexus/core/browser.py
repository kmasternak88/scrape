'''
Playwright browser instance pool manager.
Manages Google Chrome CDP (Browser-Harness) connections with automatic fallback to headless browser launch.
'''
import structlog
from typing import Optional
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from nexus.anti_bot.stealth import apply_stealth

logger = structlog.get_logger()


class BrowserManager:
    def __init__(self):
        self.pw = None
        self.browser: Optional[Browser] = None
        self.is_cdp: bool = False

    async def initialize(self) -> None:
        """
        Initializes the browser. Tries to connect to Browser-Harness CDP on port 9222 first.
        Falls back to local Playwright headless chromium if CDP is unavailable.
        """
        if self.browser:
            return

        if not self.pw:
            self.pw = await async_playwright().start()

        # Step 1: Attempt connection to Layer 2 Browser-Harness (CDP on port 9222)
        try:
            logger.info("Attempting connection to Browser-Harness CDP...", endpoint="http://127.0.0.1:9222")
            # Connect over CDP with a tight timeout
            self.browser = await self.pw.chromium.connect_over_cdp("http://127.0.0.1:9222", timeout=5000)
            self.is_cdp = True
            logger.info("Successfully connected to Linux Browser-Harness CDP", port=9222)
            return
        except Exception as e:
            logger.warn("Browser-Harness CDP connection failed. Falling back to local headless browser", error=str(e))

        # Step 2: Fallback to local Headless Chromium
        try:
            logger.info("Launching fallback local headless Chromium browser...")
            self.browser = await self.pw.chromium.launch(headless=True)
            self.is_cdp = False
            logger.info("Local fallback Chromium browser launched successfully")
        except Exception as e:
            logger.error("Failed to launch local fallback Chromium browser", error=str(e))
            raise RuntimeError(f"All browser options failed: {str(e)}")

    async def get_page(self, proxy: Optional[str] = None) -> Page:
        """
        Creates a new page within a clean context and applies stealth patches.
        """
        await self.initialize()
        
        # Connect over CDP returns a browser that manages contexts differently, 
        # but standard context API still works.
        playwright_proxy = None
        if proxy:
            playwright_proxy = {'server': proxy}

        context: BrowserContext = await self.browser.new_context(proxy=playwright_proxy)
        page: Page = await context.new_page()
        
        # Apply anti-bot stealth emulation patches
        try:
            await apply_stealth(page)
        except Exception as e:
            logger.warn("Failed to apply stealth patches to page context", error=str(e))

        return page

    async def close(self) -> None:
        """
        Closes current browser instances and stops Playwright core.
        """
        if self.browser:
            try:
                await self.browser.close()
            except Exception as e:
                logger.warn("Failed to close browser session cleanly", error=str(e))
        if self.pw:
            try:
                await self.pw.stop()
            except Exception as e:
                logger.warn("Failed to stop Playwright driver cleanly", error=str(e))
        self.browser = None
        self.pw = None
        self.is_cdp = False


# Global single-instance pool manager
browser_manager = BrowserManager()
