import time
from typing import Any, Dict, Optional, Tuple
from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError, ConnectionError
from nexus.config import settings
from nexus.utils.logger import get_logger

logger = get_logger("cache")


class RedisCache:
    """Asynchronous Redis Cache with seamless automatic fallback to in-memory storage.

    If Redis is unavailable at startup or fails during runtime, the cache falls
    back to a local thread-safe in-memory dictionary. It also implements an in-memory
    TTL (Time-To-Live) expiration checker to closely mirror Redis behavior.
    """

    def __init__(self, redis_url: Optional[str] = None) -> None:
        self.redis_url = redis_url or settings.redis_url
        self.redis: Optional[Redis] = None
        self.use_fallback = False

        # In-memory store schema: {key: (value, expire_at_timestamp)}
        # None as expire_at means it never expires.
        self._in_memory_store: Dict[str, Tuple[str, Optional[float]]] = {}
        self._connection_checked = False

    async def _get_client(self) -> Optional[Redis]:
        """Lazy initializes and verifies the Redis client connection.

        If connection fails, marks fallback mode as active.
        """
        if self.use_fallback:
            return None

        if self.redis is not None:
            return self.redis

        try:
            logger.debug("Attempting to connect to Redis...", redis_url=self.redis_url)
            self.redis = from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=2.0,
                socket_timeout=2.0,
            )
            # Verify connection with a ping
            await self.redis.ping()
            self.use_fallback = False
            logger.info("Successfully connected to Redis. Cache backend: Redis")
        except (RedisError, ConnectionError) as exc:
            self.use_fallback = True
            self.redis = None
            logger.warning(
                "Redis is unavailable. Falling back to local in-memory cache.",
                error=type(exc).__name__,
                message=str(exc),
            )

        return self.redis

    async def get(self, key: str) -> Optional[str]:
        """Gets a string value from the cache.

        If Redis fails, seamlessly reads from the in-memory fallback.
        """
        client = await self._get_client()

        if client and not self.use_fallback:
            try:
                return await client.get(key)
            except (RedisError, ConnectionError) as exc:
                logger.warning(
                    "Redis read operation failed. Switching to in-memory fallback.",
                    key=key,
                    error=type(exc).__name__,
                )
                self.use_fallback = True
                self.redis = None

        # Fallback implementation
        if key in self._in_memory_store:
            val, expire_at = self._in_memory_store[key]
            if expire_at is not None and time.time() > expire_at:
                # Key expired, remove it and return None
                del self._in_memory_store[key]
                logger.debug("In-memory key expired", key=key)
                return None
            return val

        return None

    async def set(self, key: str, value: str, expire_seconds: Optional[int] = None) -> bool:
        """Sets a string value in the cache with an optional TTL in seconds.

        If Redis fails, seamlessly writes to the in-memory fallback.
        """
        client = await self._get_client()

        if client and not self.use_fallback:
            try:
                await client.set(key, value, ex=expire_seconds)
                return True
            except (RedisError, ConnectionError) as exc:
                logger.warning(
                    "Redis write operation failed. Switching to in-memory fallback.",
                    key=key,
                    error=type(exc).__name__,
                )
                self.use_fallback = True
                self.redis = None

        # Fallback implementation
        expire_at = (time.time() + expire_seconds) if expire_seconds is not None else None
        self._in_memory_store[key] = (value, expire_at)
        return True

    async def delete(self, key: str) -> bool:
        """Deletes a key from the cache.

        If Redis fails, seamlessly deletes from the in-memory fallback.
        """
        client = await self._get_client()

        if client and not self.use_fallback:
            try:
                deleted_count = await client.delete(key)
                return deleted_count > 0
            except (RedisError, ConnectionError) as exc:
                logger.warning(
                    "Redis delete operation failed. Switching to in-memory fallback.",
                    key=key,
                    error=type(exc).__name__,
                )
                self.use_fallback = True
                self.redis = None

        # Fallback implementation
        if key in self._in_memory_store:
            del self._in_memory_store[key]
            return True
        return False

    async def clear(self) -> None:
        """Clears all keys from the cache."""
        client = await self._get_client()

        if client and not self.use_fallback:
            try:
                await client.flushdb()
                logger.info("Redis cache flushed successfully.")
            except (RedisError, ConnectionError) as exc:
                logger.warning(
                    "Redis flushdb failed. Clearing in-memory fallback.",
                    error=type(exc).__name__,
                )
                self.use_fallback = True
                self.redis = None

        self._in_memory_store.clear()
        logger.info("Local in-memory cache cleared.")


# Global cache instance
cache = RedisCache()
