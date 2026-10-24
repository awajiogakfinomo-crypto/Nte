"""Celery tasks for maintenance operations."""
from celery import shared_task
import structlog

logger = structlog.get_logger()


@shared_task(bind=True)
def reset_monthly_usage(self):
    """Reset monthly usage counters for all organizations."""
    from app.core.database import get_db_context
    from app.models.organization import Organization

    try:
        import asyncio

        async def _reset():
            async with get_db_context() as db:
                from sqlalchemy import update
                await db.execute(
                    update(Organization)
                    .where(Organization.monthly_validations_used > 0)
                    .values(monthly_validations_used=0)
                )
                await db.commit()

        asyncio.run(_reset())
        logger.info("monthly_usage_reset")
        return {"reset": True}

    except Exception as exc:
        logger.error("monthly_usage_reset_failed", error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True)
def cleanup_expired_tokens(self):
    """Clean up expired API keys and revoked tokens."""
    from app.core.database import get_db_context
    from app.core.cache import cache_manager
    from app.models.api_key import ApiKey, ApiKeyStatus
    from datetime import datetime, UTC

    try:
        import asyncio

        async def _cleanup():
            async with get_db_context() as db:
                from sqlalchemy import update
                # Expire API keys past their expiry date
                await db.execute(
                    update(ApiKey)
                    .where(
                        ApiKey.status == ApiKeyStatus.ACTIVE,
                        ApiKey.expires_at.is_not(None),
                        ApiKey.expires_at < datetime.now(UTC)
                    )
                    .values(status=ApiKeyStatus.EXPIRED)
                )
                await db.commit()

        asyncio.run(_cleanup())
        logger.info("expired_tokens_cleaned")
        return {"cleaned": True}

    except Exception as exc:
        logger.error("token_cleanup_failed", error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True)
def archive_old_validation_logs(self, days: int = 90):
    """Archive validation logs older than specified days."""
    from app.core.database import get_db_context
    from app.models.address_validation import AddressValidationLog
    from datetime import datetime, UTC, timedelta

    try:
        import asyncio

        async def _archive():
            async with get_db_context() as db:
                from sqlalchemy import delete
                cutoff = datetime.now(UTC) - timedelta(days=days)
                result = await db.execute(
                    delete(AddressValidationLog).where(AddressValidationLog.created_at < cutoff)
                )
                await db.commit()
                return result.rowcount

        deleted = asyncio.run(_archive())
        logger.info("validation_logs_archived", deleted=deleted)
        return {"deleted": deleted}

    except Exception as exc:
        logger.error("validation_logs_archive_failed", error=str(exc))
        raise self.retry(exc=exc)