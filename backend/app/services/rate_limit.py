"""Rate limiting service using Redis sliding window."""
from typing import Tuple
import structlog

from app.core.cache import cache_manager
from app.models.api_key import ApiKey

logger = structlog.get_logger()


async def check_rate_limit(api_key: ApiKey) -> Tuple[bool, int]:
    """
    Check if API key is within rate limits.

    Returns:
        Tuple of (allowed, retry_after_seconds)
    """
    # Check per-minute limit
    minute_key = f"apikey:{api_key.id}:minute"
    minute_count, minute_allowed, minute_retry = await cache_manager.increment_counter(
        minute_key, 60, api_key.rate_limit_per_minute
    )

    if not minute_allowed:
        return False, minute_retry

    # Check per-day limit
    day_key = f"apikey:{api_key.id}:day"
    day_count, day_allowed, day_retry = await cache_manager.increment_counter(
        day_key, 86400, api_key.rate_limit_per_day
    )

    if not day_allowed:
        return False, day_retry

    return True, 0


async def check_organization_rate_limit(organization_id: str, limit_per_minute: int = 1000) -> Tuple[bool, int]:
    """Check organization-level rate limit."""
    key = f"org:{organization_id}:minute"
    count, allowed, retry_after = await cache_manager.increment_counter(
        key, 60, limit_per_minute
    )
    return allowed, retry_after


async def check_ip_rate_limit(ip: str, limit_per_minute: int = 60) -> Tuple[bool, int]:
    """Check IP-based rate limit for unauthenticated endpoints."""
    key = f"ip:{ip}:minute"
    count, allowed, retry_after = await cache_manager.increment_counter(
        key, 60, limit_per_minute
    )
    return allowed, retry_after