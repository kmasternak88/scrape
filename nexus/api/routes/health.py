"""
API routes for health checks.
Verifies the health and connectivity of downstream dependencies: SQLite, Redis, and Playwright.
"""

import time
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.config import settings
from nexus.db.models import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check(
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Consolidated health status endpoint.
    Checks connectivity for the Database, Redis, and Playwright.
    """
    health_status = "healthy"
    details = {}

    # 1. Database Check
    try:
        start_time = time.time()
        await db.execute(select(1))
        db_duration = time.time() - start_time
        details["database"] = {
            "status": "connected",
            "latency_sec": db_duration
        }
    except Exception as e:
        health_status = "unhealthy"
        details["database"] = {
            "status": "disconnected",
            "error": str(e)
        }

    # 2. Redis Check
    if settings.redis_url:
        try:
            from redis import asyncio as aioredis
            redis_client = aioredis.from_url(settings.redis_url, socket_timeout=2.0)
            start_time = time.time()
            pong = await redis_client.ping()
            redis_duration = time.time() - start_time
            await redis_client.close()
            
            if pong:
                details["redis"] = {
                    "status": "connected",
                    "latency_sec": redis_duration
                }
            else:
                health_status = "unhealthy"
                details["redis"] = {
                    "status": "unhealthy",
                    "error": "Ping failed"
                }
        except Exception as e:
            # We don't necessarily fail the whole app health check if Redis is down
            # depending on critical requirements, but let's report it as degraded
            if health_status == "healthy":
                health_status = "degraded"
            details["redis"] = {
                "status": "disconnected",
                "error": str(e)
            }
    else:
        details["redis"] = {
            "status": "disabled",
            "message": "Redis is not configured"
        }

    # 3. Playwright Check
    try:
        import playwright
        details["playwright"] = {
            "status": "ready",
            "version": playwright.__version__
        }
    except ImportError:
        if health_status == "healthy":
            health_status = "degraded"
        details["playwright"] = {
            "status": "unsupported",
            "error": "Playwright module is not installed"
        }
    except Exception as e:
        if health_status == "healthy":
            health_status = "degraded"
        details["playwright"] = {
            "status": "degraded",
            "error": str(e)
        }

    return {
        "status": health_status,
        "timestamp": time.time(),
        "services": details
    }
