"""Celery tasks for logistics/delivery operations."""
from celery import shared_task
from uuid import UUID
import structlog

logger = structlog.get_logger()


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def optimize_delivery_route(self, job_id: str, organization_id: str, vehicle_capacity: int = 50):
    """Optimize delivery route using OR-Tools."""
    from app.core.database import get_db_context
    from app.services.logistics_service import LogisticsService
    from app.schemas.logistics import RouteOptimizationRequest

    try:
        import asyncio

        async def _optimize():
            async with get_db_context() as db:
                svc = LogisticsService(db)
                request = RouteOptimizationRequest(vehicle_capacity=vehicle_capacity)
                return await svc.optimize_route(UUID(job_id), UUID(organization_id), request)

        result = asyncio.run(_optimize())

        logger.info("route_optimized", job_id=job_id, distance=result.total_distance_km)
        return {"job_id": job_id, "optimized": True, "distance_km": result.total_distance_km}

    except Exception as exc:
        logger.error("route_optimization_failed", job_id=job_id, error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3)
def retry_failed_deliveries(self):
    """Retry failed deliveries that are due for retry."""
    from app.core.database import get_db_context
    from app.services.logistics_service import LogisticsService

    try:
        import asyncio

        async def _retry():
            async with get_db_context() as db:
                svc = LogisticsService(db)
                return await svc.retry_due_deliveries()

        result = asyncio.run(_retry())

        logger.info("failed_deliveries_retried", retried=result.get("retried", 0))
        return result

    except Exception as exc:
        logger.error("retry_failed_deliveries_failed", error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True)
def notify_delivery_status(self, item_id: str, status: str, organization_id: str):
    """Send notification for delivery status change (webhook, email, SMS)."""
    from app.core.database import get_db_context
    from app.services.notification_service import NotificationService

    try:
        import asyncio

        async def _notify():
            async with get_db_context() as db:
                svc = NotificationService(db)
                await svc.send_delivery_notification(UUID(item_id), status, UUID(organization_id))

        asyncio.run(_notify())

        logger.info("delivery_notification_sent", item_id=item_id, status=status)
        return {"item_id": item_id, "notified": True}

    except Exception as exc:
        logger.error("delivery_notification_failed", item_id=item_id, error=str(exc))
        # Don't retry notifications to avoid spam
        return {"item_id": item_id, "notified": False, "error": str(exc)}