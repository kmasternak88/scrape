"""
API routes for single-page web scraping.
Provides synchronous scrape execution.
"""

import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.core.engine import scraper_engine
from nexus.db.models import get_db, ExecutionStat

router = APIRouter(prefix="/api/v1/scrape", tags=["scrape"])


class ScrapeRequest(BaseModel):
    url: str
    dynamic: bool = False
    selector: Optional[str] = None
    timeout: Optional[int] = None  # timeout in ms


class ScrapeResponse(BaseModel):
    url: str
    title: str
    html: str
    markdown: str
    text: str
    duration: float
    status: str
    error: Optional[str] = None


@router.post("", response_model=ScrapeResponse)
async def execute_scrape(
    payload: ScrapeRequest,
    db: AsyncSession = Depends(get_db)
) -> ScrapeResponse:
    """
    Executes a single page scrape.
    Supports both static and dynamic browser rendering.
    """
    start_time = time.time()
    
    # Convert timeout to seconds
    timeout_s = (payload.timeout / 1000.0) if payload.timeout else None
    
    # Run the scraper engine
    result = await scraper_engine.scrape(
        url=payload.url,
        dynamic=payload.dynamic,
        selector=payload.selector,
        timeout=timeout_s
    )
    
    duration = time.time() - start_time
    
    # Save statistics
    status_code = 200 if result["status"] == "success" else 500
    stat = ExecutionStat(
        endpoint="scrape",
        status_code=status_code,
        duration=duration
    )
    db.add(stat)
    
    if result["status"] == "failed":
        raise HTTPException(status_code=500, detail=result.get("error", "Scrape failed"))
        
    return ScrapeResponse(
        url=result["url"],
        title=result["title"],
        html=result["html"],
        markdown=result["markdown"],
        text=result["text"],
        duration=result["duration"],
        status=result["status"],
        error=result.get("error")
    )


@router.get("")
async def scrape_info():
    """
    Returns information on how to use the scrape API.
    """
    return {
        "message": "Welcome to Nexus Scraper Single Page API",
        "usage": "Send a POST request to this endpoint with a JSON body.",
        "schema": {
            "url": "https://example.com",
            "dynamic": "bool (default: false)",
            "selector": "string (optional wait-for CSS selector for dynamic rendering)",
            "timeout": "integer (optional timeout in ms)"
        }
    }
