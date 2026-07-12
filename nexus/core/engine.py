"""
Core Scraper Engine for Nexus Scraper.
Provides a highly-resilient, three-tier anti-bot scraping architecture:
Tier 1: Browser-Harness CDP (True Google Chrome under Xvfb)
Tier 2: Playwright Headless (Local fallback Chromium browser)
Tier 3: curl_cffi Impersonate / httpx (Advanced TLS/JA4 evasion engine)
Supports live configuration overrides from the dynamic LLM Control Plane (ControlConfig).
"""

import re
import json
import asyncio
from typing import Any, Dict, Optional
import httpx
import structlog
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from sqlalchemy import select

from nexus.config import settings
from nexus.core.browser import browser_manager
from nexus.db.models import AsyncSessionLocal, ControlConfig

logger = structlog.get_logger()


async def get_control_override(key: str) -> Optional[Dict[str, Any]]:
    """
    Helper function to query active Control Plane configurations 
    remotely managed by LLM Agents.
    """
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(ControlConfig).filter(ControlConfig.key == key))
            config = result.scalar_one_or_none()
            if config:
                return json.loads(config.value)
    except Exception as e:
        logger.debug("Failed to fetch control override config from DB", key=key, error=str(e))
    return None


class ScraperEngine:
    """
    Production-grade web scraper engine supporting three layers of request execution and TLS evasions.
    """

    def __init__(self):
        self.default_timeout = settings.default_timeout / 1000.0  # Convert ms to seconds
        self.max_concurrent = settings.max_concurrent_browsers

    async def fetch_static(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        proxy: Optional[str] = None
    ) -> str:
        """
        Fetch HTML content from a webpage using curl_cffi for TLS/JA4 impersonation.
        Falls back to httpx if curl_cffi fails.
        """
        timeout = timeout or self.default_timeout
        
        # 1. Fetch active custom headers from LLM Control Plane
        control_headers = await get_control_override("headers_override")
        active_headers = headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if control_headers:
            logger.info("Applying LLM Control Plane headers override", count=len(control_headers))
            active_headers.update(control_headers)

        # 2. Fetch active proxy from LLM Control Plane
        control_proxy = await get_control_override("proxy_rules")
        active_proxy = proxy
        if control_proxy and "server" in control_proxy:
            logger.info("Applying LLM Control Plane proxy override", proxy=control_proxy["server"])
            active_proxy = control_proxy["server"]

        # 3. Layer 3 Anti-Bot: Attempt curl_cffi with Chrome Impersonation
        try:
            from curl_cffi import requests as curl_requests
            logger.info("Attempting Layer 3 Static Fetch (curl_cffi Chrome impersonation)...", url=url)
            
            # Map proxy to format expected by curl_cffi
            proxies = {"http": active_proxy, "https": active_proxy} if active_proxy else None
            
            # Executing non-blocking in a thread pool as curl_cffi requests is synchronous under the hood
            def _sync_curl():
                return curl_requests.get(
                    url,
                    headers=active_headers,
                    timeout=int(timeout),
                    impersonate="chrome120",
                    proxies=proxies,
                    verify=False
                )
            
            response = await asyncio.to_thread(_sync_curl)
            response.raise_for_status()
            logger.info("Layer 3 Static Fetch (curl_cffi) succeeded", url=url)
            return response.text
        except ImportError:
            logger.warn("curl_cffi is not installed. Falling back to HTTPX...")
        except Exception as e:
            logger.warn("Layer 3 Static Fetch (curl_cffi) failed. Falling back to HTTPX...", error=str(e))

        # 4. Standard HTTPX Fallback
        proxies = active_proxy if active_proxy else None
        async with httpx.AsyncClient(http2=True, follow_redirects=True, proxies=proxies) as client:
            try:
                logger.info("Attempting HTTPX fallback static fetch...", url=url)
                response = await client.get(url, headers=active_headers, timeout=timeout)
                response.raise_for_status()
                logger.info("HTTPX fallback static fetch succeeded", url=url)
                return response.text
            except Exception as e:
                logger.error("All Static fetch layers failed", url=url, error=str(e))
                raise RuntimeError(f"Static fetch failed: {str(e)}")

    async def fetch_dynamic(
        self,
        url: str,
        selector: Optional[str] = None,
        timeout: Optional[float] = None,
        proxy: Optional[str] = None
    ) -> str:
        """
        Fetch HTML content from a dynamic webpage using Playwright.
        Orchestrates Browser-Harness CDP or standard headless browser fallback.
        """
        timeout_ms = int(timeout * 1000) if timeout else settings.default_timeout

        try:
            # Get a page instance from browser_manager (orchestrates CDP 9222 and local headless launch)
            page = await browser_manager.get_page(proxy=proxy)
            try:
                logger.info("Executing browser-rendered fetch...", url=url, is_cdp=browser_manager.is_cdp)
                await page.goto(url, timeout=timeout_ms)
                if selector:
                    await page.wait_for_selector(selector, timeout=timeout_ms)
                content = await page.content()
                return content
            finally:
                # Close only the context page, keeping the browser manager instance pooled and active
                await page.context.close()
        except Exception as e:
            logger.warn("Browser-rendered fetch failed, falling back to static curl_cffi fetch", url=url, error=str(e))
            return await self.fetch_static(url, timeout=timeout, proxy=proxy)

    async def scrape(
        self,
        url: str,
        dynamic: bool = False,
        selector: Optional[str] = None,
        timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Perform a full scrape of a webpage and return metadata, raw HTML, parsed text, and markdown.
        Automatically handles dynamic overrides from the database Control Plane.
        """
        logger.info("Starting scrape", url=url, dynamic=dynamic, selector=selector)
        start_time = asyncio.get_event_loop().time()

        # Check for dynamic control plane overrides (e.g. bypass rules, selector overrides)
        control_bypass = await get_control_override("bypass_rules")
        active_dynamic = dynamic
        active_selector = selector

        if control_bypass:
            if "force_dynamic" in control_bypass and control_bypass["force_dynamic"]:
                logger.info("Applying LLM Control Plane override: forcing dynamic rendering")
                active_dynamic = True
            if "selector_overrides" in control_bypass and url in control_bypass["selector_overrides"]:
                active_selector = control_bypass["selector_overrides"][url]
                logger.info("Applying LLM Control Plane selector override", selector=active_selector)

        try:
            if active_dynamic:
                html = await self.fetch_dynamic(url, selector=active_selector, timeout=timeout)
            else:
                html = await self.fetch_static(url, timeout=timeout)

            # Parse page title and structured content
            soup = BeautifulSoup(html, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else "No Title"

            # Convert to markdown
            markdown_content = md(html, strip=["script", "style"])

            # Clean up text content
            text_content = soup.get_text(separator=" ").strip()
            text_content = re.sub(r"\s+", " ", text_content)

            duration = max(0.001, asyncio.get_event_loop().time() - start_time)
            logger.info("Scrape completed successfully", url=url, duration=duration)

            return {
                "url": url,
                "title": title,
                "html": html,
                "markdown": markdown_content,
                "text": text_content,
                "duration": duration,
                "status": "success"
            }
        except Exception as e:
            duration = max(0.001, asyncio.get_event_loop().time() - start_time)
            logger.error("Scrape failed", url=url, duration=duration, error=str(e))
            return {
                "url": url,
                "title": "",
                "html": "",
                "markdown": "",
                "text": "",
                "duration": duration,
                "status": "failed",
                "error": str(e)
            }


# Instantiate global scraper engine
scraper_engine = ScraperEngine()
