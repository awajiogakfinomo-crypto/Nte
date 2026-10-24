"""Usuk - Nigerian Location Intelligence Platform.

FastAPI application with horizontal scaling support.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from prometheus_client import Counter, Histogram, generate_latest
from prometheus_client.openmetrics.exposition import CONTENT_TYPE_LATEST
import structlog

from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.cache import cache_manager
from app.api.middleware.rate_limit import RateLimitMiddleware
from app.api.middleware.logging import LoggingMiddleware
from app.api.routes import auth, address, logistics, kyc, api_keys, usage, health

# Structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ] if settings.LOG_FORMAT == "json" else [
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(__import__("logging"), settings.LOG_LEVEL.upper())
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Prometheus metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"]
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    logger.info("starting_up", environment=settings.ENVIRONMENT)

    # Initialize database
    await init_db()
    logger.info("database_initialized")

    # Initialize cache
    await cache_manager.connect()
    logger.info("cache_connected")

    # Warm cache with common postcodes (optional background task)
    # asyncio.create_task(warm_postcode_cache())

    yield

    # Shutdown
    logger.info("shutting_down")
    await cache_manager.disconnect()
    await close_db()
    logger.info("shutdown_complete")


app = FastAPI(
    title="Usuk API",
    description="Nigerian Location Intelligence Platform powered by NIPOST Digital Postcode API",
    version="0.1.0",
    docs_url="/docs" if settings.is_development else None,
    redoc_url="/redoc" if settings.is_development else None,
    openapi_url="/openapi.json" if settings.is_development else None,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom middleware (order matters - inner to outer)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RateLimitMiddleware)

# Prometheus metrics endpoint
@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

# Health check (no auth, no rate limit)
app.include_router(health.router, tags=["health"])

# API routes
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(address.router, prefix="/api/v1/address", tags=["address"])
app.include_router(logistics.router, prefix="/api/v1/logistics", tags=["logistics"])
app.include_router(kyc.router, prefix="/api/v1/kyc", tags=["kyc"])
app.include_router(api_keys.router, prefix="/api/v1/api-keys", tags=["api-keys"])
app.include_router(usage.router, prefix="/api/v1/usage", tags=["usage"])


@app.get("/", include_in_schema=False)
async def root() -> dict:
    """Root endpoint."""
    return {
        "name": "Usuk API",
        "version": "0.1.0",
        "description": "Nigerian Location Intelligence Platform",
        "docs": "/docs" if settings.is_development else "disabled in production",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        workers=1 if settings.is_development else 4,
    )