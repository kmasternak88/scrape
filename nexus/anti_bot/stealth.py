'''
Stealth plugin for Playwright.
'''
import asyncio
from playwright.async_api import Page

async def apply_stealth(page: Page) -> None:
    # Override navigator.webdriver
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
    """)
    # Mock languages and plugins
    await page.add_init_script("""
        Object.defineProperty(navigator, 'languages', {
            get: () => ['pl-PL', 'pl', 'en-US', 'en']
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
    """)