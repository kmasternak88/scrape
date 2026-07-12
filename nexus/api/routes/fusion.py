"""
API routes for Fusion data combination and synthesis.
Combines multiple scraped data sources based on specific merging keys and strategies.
"""

import time
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import get_db, ExecutionStat

router = APIRouter(prefix="/api/v1/fusion", tags=["fusion"])


class FusionRequest(BaseModel):
    sources: List[Dict[str, Any]]
    fusion_key: Optional[str] = None
    strategy: str = "merge"  # merge, intersection, override


class FusionResponse(BaseModel):
    fused_data: Dict[str, Any]
    sources_count: int
    duration: float


@router.post("", response_model=FusionResponse)
async def execute_data_fusion(
    payload: FusionRequest,
    db: AsyncSession = Depends(get_db)
) -> FusionResponse:
    """
    Combines multiple dictionary data structures into a single synthesized result.
    Strategies:
      - 'merge': Merges dictionaries, grouping lists/sets for colliding keys.
      - 'override': Subsequent dictionaries overwrite keys in preceding ones.
      - 'intersection': Retains only the keys that are present in ALL source dictionaries.
    """
    start_time = time.time()
    
    if not payload.sources:
        raise HTTPException(status_code=400, detail="Sources list cannot be empty")
        
    fused: Dict[str, Any] = {}
    strategy = payload.strategy.lower()
    
    try:
        if strategy == "override":
            for src in payload.sources:
                fused.update(src)
                
        elif strategy == "intersection":
            if len(payload.sources) == 1:
                fused = payload.sources[0]
            else:
                common_keys = set(payload.sources[0].keys())
                for src in payload.sources[1:]:
                    common_keys.intersection_update(src.keys())
                    
                for key in common_keys:
                    # Keep value from the last source
                    fused[key] = payload.sources[-1][key]
                    
        else:  # default 'merge'
            for src in payload.sources:
                for k, v in src.items():
                    if k not in fused:
                        fused[k] = v
                    else:
                        # Collision handling
                        if isinstance(fused[k], list) and isinstance(v, list):
                            fused[k] = list(set(fused[k] + v))
                        elif isinstance(fused[k], list):
                            if v not in fused[k]:
                                fused[k].append(v)
                        elif isinstance(v, list):
                            fused[k] = [fused[k]] + [item for item in v if item != fused[k]]
                        else:
                            if fused[k] != v:
                                fused[k] = [fused[k], v]
                                
        duration = time.time() - start_time
        
        # Save statistics
        stat = ExecutionStat(
            endpoint="fusion",
            status_code=200,
            duration=duration
        )
        db.add(stat)
        await db.commit()
        
        return FusionResponse(
            fused_data=fused,
            sources_count=len(payload.sources),
            duration=duration
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Data fusion error: {str(e)}")
