"""Request logging middleware with structured logging."""
import time
import uuid
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

logger = structlog.get_logger()


class LoggingMiddleware(BaseHTTPMiddleware):
    """Structured request/response logging."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Generate request ID
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        # Start timing
        start_time = time.perf_counter()

        # Log request
        logger.info(
            "request_started",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            query_params=dict(request.query_params),
            client_ip=self._get_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
        )

        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            # Log exception
            process_time = time.perf_counter() - start_time
            logger.error(
                "request_failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                error=str(e),
                process_time_ms=round(process_time * 1000, 2),
            )
            raise

        # Calculate process time
        process_time = time.perf_counter() - start_time

        # Log response
        logger.info(
            "request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            process_time_ms=round(process_time * 1000, 2),
        )

        # Add headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(round(process_time * 1000, 2))

        return response

    def _get_client_ip(self, request: Request) -> str:
        """Get client IP address."""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"