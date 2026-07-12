"""
Rate Limiting Middleware for Nexus Scraper.
Limits request rates per IP address using Redis (if configured) or thread-safe in-memory fallback.
"""

import time
import asyncio
from typing import Dict, List, Optional
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from nexus.config import settings

# Thread-safe in-memory rate limiter state
_in_memory_storage: Dict[str, List[float]] = {}
_lock = asyncio.Lock()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware to limit incoming request rates based on Client IP.
    Integrates with Redis for distributed environments or falls back to in-memory tracking.
    """

    def __init__(
        self,
        app,
        rate_limit: int = 60,
        time_window: int = 60,
        redis_url: Optional[str] = None
    ):
        super().__init__(app)
        self.rate_limit = rate_limit  # Max requests
        self.time_window = time_window  # Time window in seconds
        self.redis_url = redis_url or settings.redis_url
        self.redis_client = None
        self._redis_connected = False

        if self.redis_url:
            try:
                from redis import asyncio as aioredis
                self.redis_client = aioredis.from_url(self.redis_url, decode_responses=True)
                self._redis_connected = True
            except Exception:
                # Fall back silently to in-memory
                self._redis_connected = False

    async def _is_rate_limited_redis(self, key: str) -> bool:
        """
        Check rate limit using Redis.
        """
        if not self.redis_client:
            return False
        try:
            current_time = time.time()
            # Use transaction pipeline to clean old and add new
            async with self.redis_client.pipeline(transaction=True) as pipe:
                pipe.zremrangebyscore(key, 0, current_time - self.time_window)
                pipe.zadd(key, {str(current_time): current_time})
                pipe.zcard(key)
                pipe.expire(key, self.time_window)
                results = await pipe.execute()
                request_count = results[2]
                return request_count > self.rate_limit
        except Exception:
            # If Redis fails, fall back to in-memory check
            self._redis_connected = False
            return await self._is_rate_limited_in_memory(key)

    async def _is_rate_limited_in_memory(self, key: str) -> bool:
        """
        Check rate limit using in-memory dict.
        """
        async with _lock:
            current_time = time.time()
            if key not in _in_memory_storage:
                _in_memory_storage[key] = []

            # Clean up elements older than time window
            timestamps = [t for t in _in_memory_storage[key] if t > current_time - self.time_window]
            _in_memory_storage[key] = timestamps

            if len(timestamps) >= self.rate_limit:
                return True

            _in_memory_storage[key].append(current_time)
            return False

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Bypassed endpoints
        if request.url.path in {"/health", "/docs", "/redoc", "/openapi.json"} or request.url.path.startswith("/docs"):
            return await call_next(request)

        # Rate limit identifier (Client IP)
        client_ip = request.client.host if request.client else "unknown"
        key = f"rate_limit:{client_ip}"

        is_limited = False
        if self._redis_connected:
            is_limited = await self._is_rate_limited_redis(key)
        else:
            is_limited = await self._is_rate_limited_in_memory(key)

        if is_limited:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please try again later."}
            )

        return await call_next(request)
