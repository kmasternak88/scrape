"""
API routes for performance metrics.
Computes and returns request execution metrics from database logs.
"""

from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy import select, case, func, func
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import get_db, ExecutionStat

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("")
async def get_execution_metrics(
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Returns compiled execution statistics.
    Includes request counts, average durations, and success rate metrics.
    """
    # 1. Total count
    total_stmt = select(func.count()).select_from(ExecutionStat)
    total_res = await db.execute(total_stmt)
    total_count = total_res.scalar() or 0

    if total_count == 0:
        return {
            "total_requests": 0,
            "average_duration_sec": 0.0,
            "endpoints": {},
            "recent_executions": []
        }

    # 2. Overall average duration
    avg_stmt = select(func.avg(ExecutionStat.duration)).select_from(ExecutionStat)
    avg_res = await db.execute(avg_stmt)
    overall_avg = avg_res.scalar() or 0.0

    # 3. Endpoint breakdown (group by endpoint)
    breakdown_stmt = select(
        ExecutionStat.endpoint,
        func.count(ExecutionStat.id).label("count"),
        func.avg(ExecutionStat.duration).label("avg_duration"),
        func.sum(case((ExecutionStat.status_code < 400, 1), else_=0)).label("successes")
    ).group_by(ExecutionStat.endpoint)
    
    breakdown_res = await db.execute(breakdown_stmt)
    endpoints = {}
    for row in breakdown_res:
        name = row[0]
        cnt = row[1]
        avg_dur = row[2] or 0.0
        succ = row[3] or 0
        success_rate = (succ / cnt) * 100 if cnt > 0 else 0.0
        
        endpoints[name] = {
            "request_count": cnt,
            "average_duration_sec": round(avg_dur, 4),
            "success_rate_percent": round(success_rate, 2)
        }

    # 4. Recent executions (last 10)
    recent_stmt = select(ExecutionStat).order_by(ExecutionStat.timestamp.desc()).limit(10)
    recent_res = await db.execute(recent_stmt)
    recent_list = []
    for stat in recent_res.scalars():
        recent_list.append({
            "id": stat.id,
            "endpoint": stat.endpoint,
            "status_code": stat.status_code,
            "duration_sec": round(stat.duration, 4),
            "timestamp": stat.timestamp.isoformat() if stat.timestamp else None
        })

    return {
        "total_requests": total_count,
        "average_duration_sec": round(overall_avg, 4),
        "endpoints": endpoints,
        "recent_executions": recent_list
    }
