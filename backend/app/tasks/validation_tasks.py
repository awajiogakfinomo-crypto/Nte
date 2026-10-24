"""Celery tasks for address validation."""
from celery import shared_task
from uuid import UUID
import structlog

logger = structlog.get_logger()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def validate_addresses_bulk(self, batch_id: str, organization_id: str, addresses: list, api_key_id: str = None):
    """Validate a batch of addresses asynchronously."""
    from app.core.database import get_db_context
    from app.services.validation_service import ValidationService
    from app.schemas.address import AddressValidationRequest, BulkAddressValidationRequest
    from app.models.address_validation import ValidationSource

    try:
        # Run async validation in sync context
        import asyncio

        async def _validate():
            async with get_db_context() as db:
                svc = ValidationService(db)
                request = BulkAddressValidationRequest(
                    addresses=[AddressValidationRequest(**addr) for addr in addresses]
                )
                return await svc.validate_bulk(
                    request=request,
                    organization_id=UUID(organization_id),
                    api_key_id=UUID(api_key_id) if api_key_id else None,
                    source=ValidationSource.BULK_UPLOAD,
                )

        result = asyncio.run(_validate())

        logger.info(
            "bulk_validation_completed",
            batch_id=batch_id,
            total=result.total,
            valid=result.valid,
        )

        return {
            "batch_id": batch_id,
            "total": result.total,
            "valid": result.valid,
            "invalid": result.invalid,
            "partial": result.partial,
            "errors": result.errors,
        }

    except Exception as exc:
        logger.error("bulk_validation_failed", batch_id=batch_id, error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3)
def validate_job_addresses(self, job_id: str, organization_id: str):
    """Validate all addresses in a delivery job."""
    from app.core.database import get_db_context
    from app.services.logistics_service import LogisticsService

    try:
        import asyncio

        async def _validate():
            async with get_db_context() as db:
                svc = LogisticsService(db)
                return await svc.validate_job(UUID(job_id), UUID(organization_id))

        result = asyncio.run(_validate())

        logger.info("job_validation_completed", job_id=job_id)
        return {"job_id": job_id, "status": "validated"}

    except Exception as exc:
        logger.error("job_validation_failed", job_id=job_id, error=str(exc))
        raise self.retry(exc=exc)