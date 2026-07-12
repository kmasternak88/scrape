"""
Persistent, Priority-based Task Queue and Background Worker for Nexus Scraper.
Implements crash recovery, priority scheduling, and exponential backoff.
"""

import uuid
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import structlog
from sqlalchemy import select, update, and_, or_

from nexus.db.models import AsyncSessionLocal, ScrapeTask
from nexus.core.engine import scraper_engine
from nexus.config import settings

logger = structlog.get_logger("nexus.core.queue")


class QueueWorker:
    """
    Asynchronous queue worker that processes prioritized scraper tasks persisted in SQLite.
    Optimized for high-concurrency throttling and resilient crash recovery.
    """

    def __init__(self):
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._wake_event = asyncio.Event()
        self._concurrency_semaphore = asyncio.Semaphore(settings.max_concurrent_browsers)

    def start(self) -> None:
        """Starts the background worker queue processor."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._main_loop())
        logger.info("Persistent Priority Task Queue worker started successfully")

    async def stop(self) -> None:
        """Gracefully stops the worker, waiting for in-flight tasks."""
        if not self._running:
            return
        self._running = False
        self._wake_event.set()  # Wake loop to exit cleanly
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Persistent Priority Task Queue worker stopped gracefully")

    async def submit_task(
        self,
        url: str,
        priority: int = 1,
        payload: Optional[Dict[str, Any]] = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Submits a new scraping task to the SQLite persistence queue.
        Bumps thread worker state immediately.
        """
        task_id = str(uuid.uuid4())
        serialized_payload = json.dumps(payload) if payload else "{}"

        async with AsyncSessionLocal() as db:
            task = ScrapeTask(
                id=task_id,
                url=url,
                priority=priority,
                status="PENDING",
                max_retries=max_retries,
                payload=serialized_payload
            )
            db.add(task)
            await db.commit()

        logger.info("Enqueued new scraper task", task_id=task_id, url=url, priority=priority)
        self._wake_event.set()  # Notify worker loop to immediately query DB
        return {
            "task_id": task_id,
            "url": url,
            "priority": priority,
            "status": "PENDING"
        }

    async def _main_loop(self) -> None:
        """Main processing loop checking for prioritized tasks in SQLite."""
        # Disaster / Crash Recovery Step:
        # Upon boot, reclaim any tasks that got interrupted in a 'RUNNING' or 'RETRYING' state
        await self._recover_interrupted_tasks()

        while self._running:
            self._wake_event.clear()
            try:
                # 1. Fetch next eligible task
                task_data = await self._fetch_next_task()
                if not task_data:
                    # No tasks pending. Sleep until woken or poll after 5 seconds for recovery checks
                    try:
                        await asyncio.wait_for(self._wake_event.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        pass
                    continue

                # 2. Acquire concurrency slot and dispatch task execution
                await self._concurrency_semaphore.acquire()
                asyncio.create_task(self._run_task_safe(task_data))

            except Exception as e:
                logger.error("Error in queue main processor loop", error=str(e))
                await asyncio.sleep(2.0)

    async def _recover_interrupted_tasks(self) -> None:
        """
        Disaster Recovery: Sets previously active tasks (left in 'RUNNING' status during crash)
        back to 'PENDING' so they are safely retried.
        """
        try:
            async with AsyncSessionLocal() as db:
                query = select(ScrapeTask).filter(ScrapeTask.status == "RUNNING")
                result = await db.execute(query)
                interrupted = result.scalars().all()
                
                if interrupted:
                    logger.info("Disaster Recovery: Found interrupted running tasks. Resetting to PENDING...", count=len(interrupted))
                    for task in interrupted:
                        task.status = "PENDING"
                        task.error_message = "Task execution interrupted by system shutdown/crash (recovered)"
                    await db.commit()
        except Exception as e:
            logger.critical("Failed to perform database crash recovery for tasks", error=str(e))

    async def _fetch_next_task(self) -> Optional[Dict[str, Any]]:
        """
        Retrieves the next pending prioritized task from SQLite.
        Includes support for scheduled task execution with exponential backoff.
        """
        try:
            async with AsyncSessionLocal() as db:
                # Fetch tasks that are PENDING or RETRYING
                # Order by: priority DESC (higher priority first), created_at ASC (oldest first)
                query = select(ScrapeTask).filter(
                    ScrapeTask.status == "PENDING"
                ).order_by(
                    ScrapeTask.priority.desc(),
                    ScrapeTask.created_at.asc()
                ).limit(1)

                result = await db.execute(query)
                task = result.scalar_one_or_none()
                if task:
                    # Atomically transition to RUNNING state to lock it from other instances
                    task.status = "RUNNING"
                    await db.commit()
                    return {
                        "id": task.id,
                        "url": task.url,
                        "priority": task.priority,
                        "retry_count": task.retry_count,
                        "max_retries": task.max_retries,
                        "payload": json.loads(task.payload) if task.payload else {}
                    }
        except Exception as e:
            logger.error("Failed to query next task from persistence store", error=str(e))
        return None

    async def _run_task_safe(self, task_data: Dict[str, Any]) -> None:
        """Safe execution wrapper releasing semaphore slot on completion."""
        try:
            await self._execute_task(task_data)
        except Exception as e:
            logger.error("Unhandled error executing task", task_id=task_data["id"], error=str(e))
        finally:
            self._concurrency_semaphore.release()

    async def _execute_task(self, task_data: Dict[str, Any]) -> None:
        """Processes task, saves result, or computes exponential backoff retries."""
        task_id = task_data["id"]
        url = task_data["url"]
        payload = task_data["payload"]

        # Extract specific options if provided
        dynamic = payload.get("dynamic", False)
        selector = payload.get("selector", None)
        timeout = payload.get("timeout", None)

        logger.info("Executing task from persistent queue", task_id=task_id, url=url, dynamic=dynamic)

        # Run scrape execution
        result = await scraper_engine.scrape(
            url=url,
            dynamic=dynamic,
            selector=selector,
            timeout=timeout
        )

        async with AsyncSessionLocal() as db:
            result_obj = await db.get(ScrapeTask, task_id)
            if not result_obj:
                logger.error("Task missing from persistence store during writeback", task_id=task_id)
                return

            if result["status"] == "success":
                result_obj.status = "COMPLETED"
                result_obj.result = json.dumps(result)
                result_obj.error_message = None
                logger.info("Task completed successfully", task_id=task_id, url=url)
            else:
                # Task failed: Handle exponential retries
                retry_count = task_data["retry_count"] + 1
                max_retries = task_data["max_retries"]

                if retry_count <= max_retries:
                    # Calculate backoff delay: 2, 4, 8, 16 seconds...
                    backoff_delay = 2 ** retry_count
                    logger.warn("Task failed. Scheduling retry with exponential backoff...", 
                                task_id=task_id, retry=retry_count, max_retries=max_retries, delay_sec=backoff_delay)
                    
                    result_obj.status = "PENDING"  # Place back into queue
                    result_obj.retry_count = retry_count
                    result_obj.error_message = result.get("error", "Temporary execution failure")
                    
                    # Artificially delay task re-selection by shifting created_at forward by backoff delay
                    result_obj.created_at = datetime.utcnow() + timedelta(seconds=backoff_delay)
                else:
                    result_obj.status = "FAILED"
                    result_obj.error_message = f"Max retries ({max_retries}) exceeded. Last error: {result.get('error')}"
                    logger.error("Task failed permanently. Retries exhausted.", task_id=task_id, url=url)

            await db.commit()


# Instantiate global singleton worker queue
queue_worker = QueueWorker()
