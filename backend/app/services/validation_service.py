"""Address validation service - business logic layer."""
from typing import List, Optional, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime, UTC

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import structlog

from app.core.cache import cache_manager
from app.services.nipost_client import nipost_client
from app.services.rate_limit import check_organization_rate_limit
from app.models.address_validation import AddressValidationLog, ValidationStatus, ValidationSource
from app.models.usage import UsageRecord, UsageType
from app.schemas.address import (
    AddressValidationRequest,
    BulkAddressValidationRequest,
    AddressValidationResult,
    AddressValidationResponse,
    BulkValidationResponse,
    AddressAutocompleteRequest,
    AutocompleteSuggestion,
    AddressAutocompleteResponse,
    ReverseGeocodeRequest,
    PostcodeLookupRequest,
    PostcodeInfo,
)

logger = structlog.get_logger()


class ValidationService:
    """Service for address validation operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # -------------------------------------------------------------------------
    # Single Validation
    # -------------------------------------------------------------------------

    async def validate_address(
        self,
        request: AddressValidationRequest,
        organization_id: UUID,
        api_key_id: Optional[UUID] = None,
        source: ValidationSource = ValidationSource.API,
        ip_address: str = None,
        user_agent: str = None,
    ) -> AddressValidationResponse:
        """Validate a single address."""
        # Check organization rate limit
        allowed, retry_after = await check_organization_rate_limit(str(organization_id))
        if not allowed:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Organization rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        # Call NIPOST API
        result = await nipost_client.validate_address(
            address=request.address,
            landmarks=request.landmarks or "",
            latitude=request.latitude,
            longitude=request.longitude,
            postcode_level=request.postcode_level,
        )

        # Log validation
        await self._log_validation(
            organization_id=organization_id,
            api_key_id=api_key_id,
            request=request,
            result=result,
            source=source,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        # Record usage
        await self._record_usage(
            organization_id=organization_id,
            api_key_id=api_key_id,
            usage_type=UsageType.ADDRESS_VALIDATE,
            endpoint="/api/v1/address/validate",
            status_code=200 if result.status != ValidationStatus.ERROR else 502,
            response_time_ms=result.processing_time_ms,
        )

        return AddressValidationResponse(request_id=uuid4(), result=result)

    async def validate_bulk(
        self,
        request: BulkAddressValidationRequest,
        organization_id: UUID,
        api_key_id: Optional[UUID] = None,
        source: ValidationSource = ValidationSource.BULK_UPLOAD,
        ip_address: str = None,
        user_agent: str = None,
    ) -> BulkValidationResponse:
        """Validate multiple addresses in bulk."""
        # Check rate limit (bulk counts as multiple)
        allowed, retry_after = await check_organization_rate_limit(str(organization_id), limit_per_minute=100)
        if not allowed:
            from fastapi import HTTPException, status
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Organization bulk rate limit exceeded",
                headers={"Retry-After": str(retry_after)},
            )

        # Prepare addresses for NIPOST
        addresses_data = [
            {
                "address": addr.address,
                "landmarks": addr.landmarks or "",
                "latitude": addr.latitude,
                "longitude": addr.longitude,
            }
            for addr in request.addresses
        ]

        # Call NIPOST bulk validation
        results = await nipost_client.bulk_validate(
            addresses=addresses_data,
            postcode_level=request.addresses[0].postcode_level if request.addresses else "building",
        )

        # Log each validation
        for addr_req, result in zip(request.addresses, results):
            await self._log_validation(
                organization_id=organization_id,
                api_key_id=api_key_id,
                request=addr_req,
                result=result,
                source=source,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        # Record usage (one record for bulk)
        await self._record_usage(
            organization_id=organization_id,
            api_key_id=api_key_id,
            usage_type=UsageType.BULK_VALIDATE,
            endpoint="/api/v1/address/validate/bulk",
            status_code=200,
            response_time_ms=sum(r.processing_time_ms for r in results),
            items_processed=len(results),
        )

        # Build response
        valid = sum(1 for r in results if r.status == ValidationStatus.VALID)
        invalid = sum(1 for r in results if r.status == ValidationStatus.INVALID)
        partial = sum(1 for r in results if r.status == ValidationStatus.PARTIAL)
        errors = sum(1 for r in results if r.status == ValidationStatus.ERROR)

        return BulkValidationResponse(
            batch_id=uuid4(),
            total=len(results),
            processed=len(results),
            valid=valid,
            invalid=invalid,
            partial=partial,
            errors=errors,
            results=results,
        )

    # -------------------------------------------------------------------------
    # Autocomplete
    # -------------------------------------------------------------------------

    async def autocomplete(
        self,
        request: AddressAutocompleteRequest,
        organization_id: UUID,
        api_key_id: Optional[UUID] = None,
    ) -> AddressAutocompleteResponse:
        """Get address autocomplete suggestions."""
        suggestions = await nipost_client.autocomplete(
            query=request.query,
            limit=request.limit,
            latitude=request.latitude,
            longitude=request.longitude,
            radius_km=request.radius_km,
        )

        # Record usage
        await self._record_usage(
            organization_id=organization_id,
            api_key_id=api_key_id,
            usage_type=UsageType.ADDRESS_AUTOCOMPLETE,
            endpoint="/api/v1/address/autocomplete",
            status_code=200,
            response_time_ms=0,  # Not tracked from NIPOST
        )

        return AddressAutocompleteResponse(suggestions=suggestions)

    # -------------------------------------------------------------------------
    # Reverse Geocode
    # -------------------------------------------------------------------------

    async def reverse_geocode(
        self,
        request: ReverseGeocodeRequest,
        organization_id: UUID,
        api_key_id: Optional[UUID] = None,
    ) -> AddressValidationResult:
        """Reverse geocode coordinates to address."""
        result = await nipost_client.reverse_geocode(
            latitude=request.latitude,
            longitude=request.longitude,
            radius_meters=request.radius_meters,
        )

        # Record usage
        await self._record_usage(
            organization_id=organization_id,
            api_key_id=api_key_id,
            usage_type=UsageType.REVERSE_GEOCODE,
            endpoint="/api/v1/address/reverse",
            status_code=200 if result else 404,
            response_time_ms=result.processing_time_ms if result else 0,
        )

        return result

    # -------------------------------------------------------------------------
    # Postcode Lookup
    # -------------------------------------------------------------------------

    async def lookup_postcode(
        self,
        request: PostcodeLookupRequest,
        organization_id: UUID,
        api_key_id: Optional[UUID] = None,
    ) -> Optional[PostcodeInfo]:
        """Look up postcode information."""
        result = await nipost_client.lookup_postcode(postcode=request.postcode)

        # Record usage
        await self._record_usage(
            organization_id=organization_id,
            api_key_id=api_key_id,
            usage_type=UsageType.POSTCODE_LOOKUP,
            endpoint="/api/v1/address/postcode",
            status_code=200 if result else 404,
            response_time_ms=0,
        )

        return result

    # -------------------------------------------------------------------------
    # Validation History
    # -------------------------------------------------------------------------

    async def get_validation_history(
        self,
        organization_id: UUID,
        page: int = 1,
        page_size: int = 20,
        status_filter: Optional[ValidationStatus] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get validation history with pagination and filters."""
        query = select(AddressValidationLog).where(
            AddressValidationLog.organization_id == organization_id
        )

        if status_filter:
            query = query.where(AddressValidationLog.status == status_filter)
        if date_from:
            query = query.where(AddressValidationLog.created_at >= date_from)
        if date_to:
            query = query.where(AddressValidationLog.created_at <= date_to)

        query = query.order_by(AddressValidationLog.created_at.desc())

        # Count total
        count_query = select(func.count()).select_from(query.subquery())
        total = await self.db.scalar(count_query)

        # Paginate
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        logs = result.scalars().all()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": logs,
        }

    async def get_validation_stats(
        self,
        organization_id: UUID,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get validation statistics."""
        query = select(
            func.count(AddressValidationLog.id).label("total"),
            func.sum(func.case((AddressValidationLog.status == ValidationStatus.VALID, 1), else_=0)).label("valid"),
            func.sum(func.case((AddressValidationLog.status == ValidationStatus.INVALID, 1), else_=0)).label("invalid"),
            func.sum(func.case((AddressValidationLog.status == ValidationStatus.PARTIAL, 1), else_=0)).label("partial"),
            func.sum(func.case((AddressValidationLog.status == ValidationStatus.ERROR, 1), else_=0)).label("errors"),
            func.avg(AddressValidationLog.processing_time_ms).label("avg_time"),
        ).where(AddressValidationLog.organization_id == organization_id)

        if date_from:
            query = query.where(AddressValidationLog.created_at >= date_from)
        if date_to:
            query = query.where(AddressValidationLog.created_at <= date_to)

        result = await self.db.execute(query)
        row = result.one()

        total = row.total or 0
        valid = row.valid or 0
        invalid = row.invalid or 0
        partial = row.partial or 0
        errors = row.errors or 0

        return {
            "total_validations": total,
            "valid_count": valid,
            "invalid_count": invalid,
            "partial_count": partial,
            "error_count": errors,
            "success_rate": (valid + partial) / total if total > 0 else 0,
            "avg_processing_time_ms": float(row.avg_time) if row.avg_time else 0,
        }

    # -------------------------------------------------------------------------
    # Private Helpers
    # -------------------------------------------------------------------------

    async def _log_validation(
        self,
        organization_id: UUID,
        api_key_id: Optional[UUID],
        request: AddressValidationRequest,
        result: AddressValidationResult,
        source: ValidationSource,
        ip_address: str = None,
        user_agent: str = None,
    ) -> AddressValidationLog:
        """Log validation request to database."""
        log = AddressValidationLog(
            organization_id=organization_id,
            api_key_id=api_key_id,
            raw_address=request.address,
            raw_landmarks=request.landmarks,
            input_latitude=request.latitude,
            input_longitude=request.longitude,
            status=result.status,
            postcode=result.postcode,
            postcode_level=result.postcode_level,
            formatted_address=result.formatted_address,
            latitude=result.latitude,
            longitude=result.longitude,
            state=result.state,
            lga=result.lga,
            ward=result.ward,
            district=result.district,
            area=result.area,
            confidence_score=result.confidence_score,
            match_type=result.match_type,
            suggestions=result.suggestions,
            source=source,
            ip_address=ip_address,
            user_agent=user_agent,
            processing_time_ms=result.processing_time_ms,
            error_code=result.error_code,
            error_message=result.error_message,
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def _record_usage(
        self,
        organization_id: UUID,
        api_key_id: Optional[UUID],
        usage_type: UsageType,
        endpoint: str,
        method: str = "POST",
        status_code: int = 200,
        response_time_ms: int = 0,
        items_processed: int = 1,
    ) -> UsageRecord:
        """Record usage for billing/analytics."""
        from app.models.organization import OrganizationPlan

        # Get organization to check plan
        from app.models.organization import Organization
        org_result = await self.db.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        org = org_result.scalar_one_or_none()

        # Calculate cost based on plan (simplified)
        cost_map = {
            OrganizationPlan.FREE: 0,
            OrganizationPlan.STARTER: 100,  # 1 kobo per request
            OrganizationPlan.PROFESSIONAL: 50,
            OrganizationPlan.ENTERPRISE: 10,
        }
        cost_kobo = cost_map.get(org.plan if org else OrganizationPlan.FREE, 100)

        usage = UsageRecord(
            organization_id=organization_id,
            api_key_id=api_key_id,
            usage_type=usage_type,
            endpoint=endpoint,
            method=method,
            status_code=status_code,
            request_count=1,
            items_processed=items_processed,
            response_time_ms=response_time_ms,
            cost_kobo=cost_kobo * items_processed,
            date_bucket=datetime.now(UTC).replace(minute=0, second=0, microsecond=0),
            hour_bucket=datetime.now(UTC).hour,
        )
        self.db.add(usage)

        # Update organization monthly usage
        if org:
            org.monthly_validations_used += items_processed

        await self.db.flush()
        return usage