"""Multi-level cache abstraction with Redis backend and in-memory L1 cache."""
import json
import time
from typing import Any, Optional, List, Dict
from functools import wraps

import redis.asyncio as redis
from cachetools import TTLCache
import structlog

from app.core.config import settings

logger = structlog.get_logger()


class CacheManager:
    """Two-level cache: in-memory L1 (TTLCache) + Redis L2."""

    def __init__(self):
        self._redis: Optional[redis.Redis] = None
        self._l1_cache: TTLCache = TTLCache(maxsize=10000, ttl=300)  # 5 min L1 TTL
        self._connected = False

    async def connect(self) -> None:
        """Initialize Redis connection pool."""
        if self._connected:
            return

        try:
            self._redis = redis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=50,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )
            # Test connection
            await self._redis.ping()
            self._connected = True
            logger.info("redis_connected", url=settings.REDIS_URL)
        except Exception as e:
            logger.error("redis_connection_failed", error=str(e))
            self._connected = False
            # Don't raise - allow degraded mode without Redis

    async def disconnect(self) -> None:
        """Close Redis connections."""
        if self._redis:
            await self._redis.close()
            self._connected = False
            logger.info("redis_disconnected")

    # -------------------------------------------------------------------------
    # L1 Cache (in-memory, fast, per-process)
    # -------------------------------------------------------------------------

    def _l1_get(self, key: str) -> Optional[Any]:
        return self._l1_cache.get(key)

    def _l1_set(self, key: str, value: Any, ttl: int = 300) -> None:
        self._l1_cache[key] = value
        # Note: TTLCache doesn't support per-key TTL, uses global TTL

    def _l1_delete(self, key: str) -> None:
        self._l1_cache.pop(key, None)

    def _l1_clear(self) -> None:
        self._l1_cache.clear()

    # -------------------------------------------------------------------------
    # L2 Cache (Redis, shared, persistent)
    # -------------------------------------------------------------------------

    async def _l2_get(self, key: str) -> Optional[Any]:
        if not self._connected or not self._redis:
            return None
        try:
            value = await self._redis.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            logger.warning("redis_get_failed", key=key, error=str(e))
        return None

    async def _l2_set(self, key: str, value: Any, ttl: int = 3600) -> bool:
        if not self._connected or not self._redis:
            return False
        try:
            await self._redis.setex(key, ttl, json.dumps(value, default=str))
            return True
        except Exception as e:
            logger.warning("redis_set_failed", key=key, error=str(e))
            return False

    async def _l2_delete(self, key: str) -> bool:
        if not self._connected or not self._redis:
            return False
        try:
            await self._redis.delete(key)
            return True
        except Exception as e:
            logger.warning("redis_delete_failed", key=key, error=str(e))
            return False

    async def _l2_delete_pattern(self, pattern: str) -> int:
        if not self._connected or not self._redis:
            return 0
        try:
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
                if keys:
                    deleted += await self._redis.delete(*keys)
                if cursor == 0:
                    break
            return deleted
        except Exception as e:
            logger.warning("redis_delete_pattern_failed", pattern=pattern, error=str(e))
            return 0

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    async def get(self, key: str, default: Any = None) -> Any:
        """Get value from L1, then L2."""
        # Try L1
        value = self._l1_get(key)
        if value is not None:
            return value

        # Try L2
        value = await self._l2_get(key)
        if value is not None:
            # Populate L1
            self._l1_set(key, value)
            return value

        return default

    async def set(self, key: str, value: Any, ttl: int = 3600, l1_ttl: int = 300) -> bool:
        """Set value in both L1 and L2."""
        self._l1_set(key, value, l1_ttl)
        return await self._l2_set(key, value, ttl)

    async def delete(self, key: str) -> bool:
        """Delete from both L1 and L2."""
        self._l1_delete(key)
        return await self._l2_delete(key)

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern from L2, clear L1."""
        self._l1_clear()  # Conservative: clear L1 on pattern delete
        return await self._l2_delete_pattern(pattern)

    async def exists(self, key: str) -> bool:
        """Check if key exists in L1 or L2."""
        if self._l1_get(key) is not None:
            return True
        if not self._connected or not self._redis:
            return False
        try:
            return await self._redis.exists(key) > 0
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Rate Limiting Support
    # -------------------------------------------------------------------------

    async def increment_counter(
        self,
        key: str,
        window_seconds: int,
        limit: int,
    ) -> tuple[int, bool, int]:
        """
        Increment sliding window counter.
        Returns: (current_count, allowed, retry_after_seconds)
        """
        if not self._connected or not self._redis:
            # Degraded mode: allow all
            return (0, True, 0)

        now = time.time()
        window_start = now - window_seconds
        redis_key = f"ratelimit:{key}"

        try:
            pipe = self._redis.pipeline()
            # Remove expired entries
            pipe.zremrangebyscore(redis_key, 0, window_start)
            # Count current
            pipe.zcard(redis_key)
            # Add current request
            pipe.zadd(redis_key, {str(now): now})
            # Set expiry
            pipe.expire(redis_key, window_seconds + 1)
            results = await pipe.execute()

            current_count = results[1]
            allowed = current_count < limit
            retry_after = int(window_seconds) if not allowed else 0

            return (current_count + 1, allowed, retry_after)
        except Exception as e:
            logger.warning("rate_limit_check_failed", key=key, error=str(e))
            return (0, True, 0)  # Fail open

    # -------------------------------------------------------------------------
    # Token Blocklist
    # -------------------------------------------------------------------------

    async def revoke_token(self, jti: str, ttl: int = 604800) -> bool:
        """Add token JTI to blocklist (default 7 days)."""
        return await self._l2_set(f"blocklist:{jti}", "1", ttl)

    async def is_token_revoked(self, jti: str) -> bool:
        """Check if token is revoked."""
        return await self.exists(f"blocklist:{jti}")

    # -------------------------------------------------------------------------
    # Specialized Methods for Common Patterns
    # -------------------------------------------------------------------------

    async def get_postcode(self, postcode: str) -> Optional[Dict]:
        """Get cached postcode info."""
        return await self.get(f"postcode:{postcode}")

    async def set_postcode(self, postcode: str, data: Dict, ttl: int = 86400) -> bool:
        """Cache postcode info (default 24h)."""
        return await self.set(f"postcode:{postcode}", data, ttl)

    async def get_validation(self, address_hash: str) -> Optional[Dict]:
        """Get cached validation result."""
        return await self.get(f"validation:{address_hash}")

    async def set_validation(self, address_hash: str, data: Dict, ttl: int = 3600) -> bool:
        """Cache validation result (default 1h)."""
        return await self.set(f"validation:{address_hash}", data, ttl)

    async def get_autocomplete(self, query: str, lat: float = None, lon: float = None) -> Optional[List]:
        """Get cached autocomplete suggestions."""
        key = f"autocomplete:{query}"
        if lat and lon:
            key += f":{lat:.4f}:{lon:.4f}"
        return await self.get(key)

    async def set_autocomplete(self, query: str, data: List, lat: float = None, lon: float = None, ttl: int = 300) -> bool:
        """Cache autocomplete suggestions (default 5 min)."""
        key = f"autocomplete:{query}"
        if lat and lon:
            key += f":{lat:.4f}:{lon:.4f}"
        return await self.set(key, data, ttl)


# Global instance
cache_manager = CacheManager()


# -------------------------------------------------------------------------
# Decorator for easy caching
# -------------------------------------------------------------------------

def cached(ttl: int = 3600, key_prefix: str = ""):
    """Decorator to cache async function results."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Build cache key from function name and arguments
            key_parts = [key_prefix, func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
            cache_key = ":".join(key_parts)

            # Try cache
            cached_value = await cache_manager.get(cache_key)
            if cached_value is not None:
                return cached_value

            # Execute and cache
            result = await func(*args, **kwargs)
            await cache_manager.set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator