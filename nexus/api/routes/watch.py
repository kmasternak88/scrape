"""
API routes for watch events management.
Provides registration, removal, and listing of monitored web components.
"""

import uuid
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import get_db, WatchEvent, ExecutionStat

router = APIRouter(prefix="/api/v1/watch", tags=["watch"])


class WatchRequest(BaseModel):
    url: str
    selector: str
    frequency: int = 60  # Check frequency in minutes


class WatchResponse(BaseModel):
    id: str
    url: str
    selector: str
    frequency: int
    last_value: Optional[str] = None
    last_checked: Optional[str] = None
    created_at: str


@router.post("", response_model=WatchResponse, status_code=status.HTTP_201_CREATED)
async def register_watch(
    payload: WatchRequest,
    db: AsyncSession = Depends(get_db)
) -> WatchResponse:
    """
    Register a new page element watch monitoring target.
    """
    start_time = time.time()
    event_id = str(uuid.uuid4())
    
    event = WatchEvent(
        id=event_id,
        url=payload.url,
        selector=payload.selector,
        frequency=payload.frequency
    )
    db.add(event)
    await db.commit()
    
    # Refresh to load dates
    await db.refresh(event)
    
    duration = time.time() - start_time
    stat = ExecutionStat(
        endpoint="watch",
        status_code=201,
        duration=duration
    )
    db.add(stat)
    await db.commit()
    
    return WatchResponse(**event.to_dict())


@router.delete("/{event_id}", status_code=status.HTTP_200_OK)
async def delete_watch(
    event_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Delete / unregister a watch event by ID.
    """
    stmt = select(WatchEvent).where(WatchEvent.id == event_id)
    result = await db.execute(stmt)
    event = result.scalar_one_or_none()
    
    if not event:
        raise HTTPException(status_code=404, detail="Watch event not found")
        
    await db.delete(event)
    await db.commit()
    
    return {"message": "Watch event unregistered successfully", "id": event_id}


@router.get("", response_model=List[WatchResponse])
async def list_watches(
    db: AsyncSession = Depends(get_db)
) -> List[WatchResponse]:
    """
    List all active watch events.
    """
    stmt = select(WatchEvent)
    result = await db.execute(stmt)
    events = result.scalars().all()
    
    return [WatchResponse(**e.to_dict()) for e in events]
