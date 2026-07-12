"""
API routes for bulk web scraping.
Provides asynchronous queuing and execution with job status retrieval.
"""

import uuid
import json
import asyncio
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.engine import scraper_engine
from nexus.db.models import get_db, ScrapeJob, ExecutionStat

router = APIRouter(prefix="/api/v1/scrape/bulk", tags=["bulk"])


class BulkScrapeRequest(BaseModel):
    urls: List[str]
    dynamic: bool = False
    selector: Optional[str] = None
    timeout: Optional[int] = None


class BulkJobCreatedResponse(BaseModel):
    job_id: str
    status: str
    urls_count: int


async def process_bulk_scrape_job(
    job_id: str,
    urls: List[str],
    dynamic: bool,
    selector: Optional[str],
    timeout_ms: Optional[int],
    db_session_factory
) -> None:
    """
    Background worker task to process a bulk scrape job.
    Uses async database session locally.
    """
    start_time = asyncio.get_event_loop().time()
    
    # We will instantiate a new session to run in the background
    async with db_session_factory() as db:
        # 1. Update job to RUNNING
        stmt = select(ScrapeJob).where(ScrapeJob.id == job_id)
        result = await db.execute(stmt)
        job = result.scalar_one_or_none()
        
        if not job:
            return
            
        job.status = "RUNNING"
        await db.commit()
        
        # 2. Scrape each URL
        results = []
        timeout_s = (timeout_ms / 1000.0) if timeout_ms else None
        
        for url in urls:
            try:
                res = await scraper_engine.scrape(
                    url=url,
                    dynamic=dynamic,
                    selector=selector,
                    timeout=timeout_s
                )
                results.append(res)
            except Exception as e:
                results.append({
                    "url": url,
                    "status": "failed",
                    "error": str(e)
                })
                
        # 3. Save results and update job status
        # Re-fetch the job to make sure we are inside the transaction correctly
        stmt = select(ScrapeJob).where(ScrapeJob.id == job_id)
        result = await db.execute(stmt)
        job = result.scalar_one_or_none()
        
        if job:
            job.results = json.dumps(results)
            job.status = "COMPLETED"
            job.completed_at = datetime.utcnow()
            
            # Record bulk duration in stats
            duration = asyncio.get_event_loop().time() - start_time
            stat = ExecutionStat(
                endpoint="bulk",
                status_code=200,
                duration=duration
            )
            db.add(stat)
            
            await db.commit()


@router.post("", response_model=BulkJobCreatedResponse)
async def create_bulk_job(
    payload: BulkScrapeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
) -> BulkJobCreatedResponse:
    """
    Submit a list of URLs to be scraped asynchronously.
    Returns a unique job_id to monitor progress.
    """
    if not payload.urls:
        raise HTTPException(status_code=400, detail="URLs list cannot be empty")
        
    job_id = str(uuid.uuid4())
    
    # Save pending job to database
    job = ScrapeJob(
        id=job_id,
        status="PENDING",
        urls=json.dumps(payload.urls),
        results=json.dumps([])
    )
    db.add(job)
    await db.commit()
    
    # Define a helper lambda to construct background DB sessions
    from nexus.db.models import AsyncSessionLocal
    
    # Queue background task
    background_tasks.add_task(
        process_bulk_scrape_job,
        job_id=job_id,
        urls=payload.urls,
        dynamic=payload.dynamic,
        selector=payload.selector,
        timeout_ms=payload.timeout,
        db_session_factory=AsyncSessionLocal
    )
    
    return BulkJobCreatedResponse(
        job_id=job_id,
        status="PENDING",
        urls_count=len(payload.urls)
    )


@router.get("/{job_id}")
async def get_bulk_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve status and results of a bulk scraping job by its job_id.
    """
    stmt = select(ScrapeJob).where(ScrapeJob.id == job_id)
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Bulk scrape job not found")
        
    return job.to_dict()
