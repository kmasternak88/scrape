import asyncio
import hashlib
import logging
import time
from typing import Dict, List, Optional, Any, Callable
from bs4 import BeautifulSoup
import httpx

logger = logging.getLogger("nexus.innovations.event_trigger")


class EventTriggerEngine:
    """
    EventTriggerEngine manages background asynchronous web page watchers.
    It periodically fetches URLs, calculates content hashes (optionally filtered by a CSS selector),
    detects changes, and triggers registered webhooks.
    """

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self.client = client or httpx.AsyncClient(timeout=10.0, follow_redirects=True)
        self.watchers: Dict[str, Dict[str, Any]] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self._is_running = False

    def _calculate_hash(self, html: str, selector: Optional[str] = None) -> str:
        """Calculates a SHA-256 hash of the HTML content, or of a specific CSS selector if provided."""
        if not html:
            return ""

        content_to_hash = html
        if selector:
            try:
                soup = BeautifulSoup(html, 'html.parser')
                element = soup.select_one(selector)
                if element:
                    content_to_hash = element.get_text().strip()
                else:
                    logger.warning(f"Selector '{selector}' not found in DOM, hashing empty string.")
                    content_to_hash = ""
            except Exception as e:
                logger.error(f"Error extracting selector '{selector}' for hashing: {e}")
                content_to_hash = ""

        return hashlib.sha256(content_to_hash.encode('utf-8', errors='ignore')).hexdigest()

    async def _trigger_webhooks(self, watcher_id: str, url: str, old_hash: str, new_hash: str, webhooks: List[str]) -> None:
        """Asynchronously triggers all registered webhooks for a watcher."""
        payload = {
            "event": "nexus.scraper.change_detected",
            "watcher_id": watcher_id,
            "url": url,
            "old_hash": old_hash,
            "new_hash": new_hash,
            "timestamp": time.time()
        }

        async def send_one(webhook_url: str) -> None:
            try:
                response = await self.client.post(webhook_url, json=payload, timeout=5.0)
                if response.status_code >= 400:
                    logger.error(f"Webhook {webhook_url} returned status code {response.status_code}")
                else:
                    logger.debug(f"Webhook {webhook_url} triggered successfully")
            except Exception as e:
                logger.error(f"Failed to trigger webhook {webhook_url}: {e}")

        # Send concurrent webhook requests
        await asyncio.gather(*(send_one(wh) for wh in webhooks), return_exceptions=True)

    async def _watcher_loop(self, watcher_id: str) -> None:
        """Background asynchronous loop for a single watcher."""
        watcher = self.watchers[watcher_id]
        url = watcher["url"]
        interval = watcher["interval"]
        selector = watcher["selector"]
        webhooks = watcher["webhooks"]
        headers = watcher["headers"]

        logger.info(f"Starting watcher loop for '{watcher_id}' targeting '{url}' every {interval}s")

        while self._is_running and watcher_id in self.watchers:
            try:
                # Fetch content
                response = await self.client.get(url, headers=headers)
                response.raise_for_status()
                html = response.text

                # Compute new hash
                new_hash = self._calculate_hash(html, selector)
                old_hash = watcher["last_hash"]

                if old_hash is None:
                    # Initial hash setup
                    watcher["last_hash"] = new_hash
                    watcher["run_count"] += 1
                    watcher["last_checked"] = time.time()
                    logger.info(f"Initial hash for '{watcher_id}' computed: {new_hash}")
                elif new_hash != old_hash:
                    # Change detected!
                    watcher["last_hash"] = new_hash
                    watcher["run_count"] += 1
                    watcher["last_checked"] = time.time()
                    logger.warning(f"Change detected on '{watcher_id}'! Old hash: {old_hash} -> New hash: {new_hash}")
                    
                    if webhooks:
                        # Schedule webhook tasks in the background without blocking the loop
                        asyncio.create_task(self._trigger_webhooks(watcher_id, url, old_hash, new_hash, webhooks))
                else:
                    # No changes
                    watcher["run_count"] += 1
                    watcher["last_checked"] = time.time()
                    logger.debug(f"Checked '{watcher_id}': No changes detected.")

            except Exception as e:
                logger.error(f"Error in watcher '{watcher_id}' during fetch/analysis: {e}")
                watcher["last_error"] = str(e)

            await asyncio.sleep(interval)

    def add_watcher(
        self,
        watcher_id: str,
        url: str,
        interval: float,
        selector: Optional[str] = None,
        webhooks: Optional[List[str]] = None,
        headers: Optional[Dict[str, str]] = None
    ) -> bool:
        """Registers a new watcher and starts its background task if the engine is running."""
        if watcher_id in self.watchers:
            logger.warning(f"Watcher ID '{watcher_id}' already exists. Overwriting.")
            self.remove_watcher(watcher_id)

        self.watchers[watcher_id] = {
            "url": url,
            "interval": interval,
            "selector": selector,
            "webhooks": webhooks or [],
            "headers": headers or {},
            "last_hash": None,
            "last_checked": None,
            "last_error": None,
            "run_count": 0
        }

        if self._is_running:
            task = asyncio.create_task(self._watcher_loop(watcher_id))
            self.tasks[watcher_id] = task

        logger.info(f"Watcher '{watcher_id}' successfully added.")
        return True

    def remove_watcher(self, watcher_id: str) -> bool:
        """Stops and removes a watcher."""
        if watcher_id not in self.watchers:
            logger.warning(f"Watcher '{watcher_id}' not found.")
            return False

        if watcher_id in self.tasks:
            self.tasks[watcher_id].cancel()
            del self.tasks[watcher_id]

        del self.watchers[watcher_id]
        logger.info(f"Watcher '{watcher_id}' successfully removed.")
        return True

    def get_watcher_status(self, watcher_id: str) -> Optional[Dict[str, Any]]:
        """Returns the status and metrics of a specific watcher."""
        return self.watchers.get(watcher_id)

    def start(self) -> None:
        """Starts all background tasks for registered watchers."""
        if self._is_running:
            return
        self._is_running = True
        for watcher_id in self.watchers:
            task = asyncio.create_task(self._watcher_loop(watcher_id))
            self.tasks[watcher_id] = task
        logger.info("EventTriggerEngine started.")

    async def stop(self) -> None:
        """Gracefully cancels all background watcher tasks and closes the HTTP client."""
        self._is_running = False
        for watcher_id, task in list(self.tasks.items()):
            task.cancel()
            self.tasks.pop(watcher_id, None)
        
        await self.client.aclose()
        logger.info("EventTriggerEngine stopped.")
