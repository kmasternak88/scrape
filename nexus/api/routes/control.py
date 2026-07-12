"""
API Control Plane for LLM Agent Management and Priority Queue Interacting.
Allows remote LLM agents to dynamically manage browser settings, bypasses, proxies,
and priorities in the asynchronous persistent SQLite task queue.
"""

import json
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import get_db, ControlConfig, ScrapeTask
from nexus.core.queue import queue_worker
from nexus.core.browser import browser_manager

router = APIRouter(prefix="/api/v1/control", tags=["control_plane"])


# --- Schemas ---

class ControlOverrideRequest(BaseModel):
    key: str = Field(..., description="Override key, e.g., 'headers_override', 'proxy_rules', 'bypass_rules'")
    value: Dict[str, Any] = Field(..., description="Configuration dictionary representing active overrides")


class QueueTaskRequest(BaseModel):
    url: str = Field(..., description="URL targeting webpage to scrape")
    priority: int = Field(default=1, ge=1, le=5, description="Task execution priority. 1 = Low, 5 = High")
    payload: Optional[Dict[str, Any]] = Field(default=None, description="Custom scrape configurations")
    max_retries: int = Field(default=3, ge=0, le=10, description="Max failed attempts before marking task as failed")


# --- Endpoint Route Controllers ---

@router.get("", response_model=Dict[str, Any])
async def list_active_overrides(db: AsyncSession = Depends(get_db)):
    """
    Returns all active dynamic control plane overrides currently saved in SQLite.
    Allows LLM agents to inspect active configs.
    """
    result = await db.execute(select(ControlConfig))
    overrides = result.scalars().all()
    
    return {
        "browser_harness_status": {
            "is_cdp_connected": browser_manager.is_cdp,
            "cdp_endpoint": "http://127.0.0.1:9222"
        },
        "active_overrides": {
            ov.key: json.loads(val) if (val := ov.value) else {}
            for ov in overrides
        }
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_or_update_override(
    payload: ControlOverrideRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Saves or updates a specific override key.
    Used by remote LLM Agents to dynamically inject configurations like headers or proxies.
    """
    serialized_val = json.dumps(payload.value)
    
    # Check if override already exists
    result = await db.execute(select(ControlConfig).filter(ControlConfig.key == payload.key))
    existing = result.scalar_one_or_none()
    
    if existing:
        existing.value = serialized_val
    else:
        new_override = ControlConfig(key=payload.key, value=serialized_val)
        db.add(new_override)
        
    await db.commit()
    return {"status": "success", "message": f"Successfully updated override key: {payload.key}"}


@router.delete("/{key}", status_code=status.HTTP_200_OK)
async def delete_override(key: str, db: AsyncSession = Depends(get_db)):
    """
    Deletes a specific override key, reverting the scraper engine back to defaults.
    """
    result = await db.execute(select(ControlConfig).filter(ControlConfig.key == key))
    existing = result.scalar_one_or_none()
    
    if not existing:
        raise HTTPException(status_code=404, detail=f"Override key '{key}' not found")
        
    await db.delete(existing)
    await db.commit()
    return {"status": "success", "message": f"Successfully deleted override key: {key}"}


@router.post("/queue", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_scrape_task(payload: QueueTaskRequest):
    """
    Enqueues a prioritized scraping task with persistence, automatic retries,
    and exponential backoff support.
    """
    task = await queue_worker.submit_task(
        url=payload.url,
        priority=payload.priority,
        payload=payload.payload,
        max_retries=payload.max_retries
    )
    return task


@router.get("/queue/{task_id}", response_model=Dict[str, Any])
async def get_queue_task_status(task_id: str, db: AsyncSession = Depends(get_db)):
    """
    Retrieves status, execution details, and eventual results of a queued scraping task.
    """
    result = await db.execute(select(ScrapeTask).filter(ScrapeTask.id == task_id))
    task = result.scalar_one_or_none()
    
    if not task:
        raise HTTPException(status_code=404, detail=f"Scraper task with ID '{task_id}' not found in queue")
        
    return task.to_dict()


@router.get("/queue", response_model=List[Dict[str, Any]])
async def list_queue_tasks(
    status_filter: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db)
):
    """
    Lists tasks currently stored in the queue, with optional status filtering.
    """
    query = select(ScrapeTask)
    if status_filter:
        query = query.filter(ScrapeTask.status == status_filter.upper())
        
    query = query.order_by(ScrapeTask.created_at.desc()).limit(limit)
    result = await db.execute(query)
    tasks = result.scalars().all()
    
    return [t.to_dict() for task in tasks if (t := task)]
