"""Health check endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_db
from app.core.cache import cache_manager
from app.services.nipost_client import nipost_client

router = APIRouter()


@router.get("/health", tags=["health"])
async def health_check() -> dict:
    """Basic health check - no dependencies."""
    return {
        "status": "healthy",
        "service": "usuk-api",
        "version": "0.1.0",
        "environment": settings.ENVIRONMENT,
    }


@router.get("/health/ready", tags=["health"])
async def readiness_check(db: AsyncSession = Depends(get_db)) -> dict:
    """Readiness check - verifies all dependencies."""
    checks = {}

    # Database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {e}"

    # Redis/Cache
    try:
        if cache_manager._connected:
            await cache_manager._redis.ping()
            checks["cache"] = "healthy"
        else:
            checks["cache"] = "disconnected"
    except Exception as e:
        checks["cache"] = f"unhealthy: {e}"

    # NIPOST API
    nipost_health = await nipost_client.health_check()
    checks["nipost"] = nipost_health.get("status", "unknown")

    all_healthy = all(v == "healthy" for v in checks.values() if v != "disconnected")

    return {
        "status": "ready" if all_healthy else "degraded",
        "checks": checks,
    }


@router.get("/health/live", tags=["health"])
async def liveness_check() -> dict:
    """Liveness check - process is alive."""
    return {"status": "alive"}