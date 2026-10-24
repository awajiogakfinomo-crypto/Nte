"""Rate limiting middleware using Redis sliding window."""
import time
from typing import Optional

from fastapi import Request, Response, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

from app.core.cache import cache_manager
from app.core.config import settings

logger = structlog.get_logger()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Global rate limiting middleware with multiple strategies."""

    # Endpoints that skip rate limiting
    EXEMPT_PATHS = {"/health", "/health/ready", "/health/live", "/metrics", "/docs", "/redoc", "/openapi.json", "/"}

    # Default limits for unauthenticated requests
    DEFAULT_IP_LIMIT = 60  # per minute
    DEFAULT_IP_WINDOW = 60  # seconds

    async def dispatch(self, request: Request, call_next) -> Response:
        # Skip rate limiting for exempt paths
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        # Skip for internal/health checks
        if request.url.path.startswith("/internal/"):
            return await call_next(request)

        # Get client identifier
        client_id = self._get_client_id(request)
        if not client_id:
            return await call_next(request)

        # Check rate limit
        allowed, retry_after = await self._check_rate_limit(client_id, request)

        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                client_id=client_id,
                path=request.url.path,
                method=request.method,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Please slow down.",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(self.DEFAULT_IP_LIMIT),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                },
            )

        # Process request
        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(self.DEFAULT_IP_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(max(0, self.DEFAULT_IP_LIMIT - 1))
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + self.DEFAULT_IP_WINDOW)

        return response

    def _get_client_id(self, request: Request) -> Optional[str]:
        """Get client identifier for rate limiting."""
        # Use API key if present
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            # Hash the token for privacy
            import hashlib
            token_hash = hashlib.sha256(auth[7:].encode()).hexdigest()[:16]
            return f"apikey:{token_hash}"

        # Fall back to IP
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else "unknown"
        return f"ip:{ip}"

    async def _check_rate_limit(self, client_id: str, request: Request) -> tuple[bool, int]:
        """Check rate limit using sliding window."""
        if not cache_manager._connected or not cache_manager._redis:
            # Fail open if Redis unavailable
            return True, 0

        window = self.DEFAULT_IP_WINDOW
        limit = self.DEFAULT_IP_LIMIT

        # Adjust limits for authenticated API key requests
        if client_id.startswith("apikey:"):
            # API key requests have their own rate limiting in the API key dependency
            # This is a fallback
            limit = 1000
            window = 60

        key = f"ratelimit:{client_id}"
        now = time.time()
        window_start = now - window

        try:
            pipe = cache_manager._redis.pipeline()
            pipe.zremrangebyscore(key, 0, window_start)
            pipe.zcard(key)
            pipe.zadd(key, {str(now): now})
            pipe.expire(key, window + 1)
            results = await pipe.execute()

            current_count = results[1]
            allowed = current_count < limit
            retry_after = int(window) if not allowed else 0

            return allowed, retry_after
        except Exception as e:
            logger.warning("rate_limit_check_failed", client_id=client_id, error=str(e))
            return True, 0  # Fail open