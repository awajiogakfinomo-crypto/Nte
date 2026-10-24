"""Address validation API routes."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.api.deps import (
    get_api_key,
    get_api_key_optional,
    get_current_user_optional,
    get_db,
    get_organization_id,
    get_client_ip,
    get_pagination,
    get_request_id,
)
from app.schemas.address import (
    AddressValidationRequest,
    AddressValidationResponse,
    BulkAddressValidationRequest,
    BulkValidationResponse,
    AddressAutocompleteRequest,
    AddressAutocompleteResponse,
    ReverseGeocodeRequest,
    PostcodeLookupRequest,
    PostcodeInfo,
    ValidationStats,
)
from app.services.validation_service import ValidationService

router = APIRouter()
logger = structlog.get_logger()


def get_validation_service(db: AsyncSession = Depends(get_db)) -> ValidationService:
    """Get validation service instance."""
    return ValidationService(db)


# -------------------------------------------------------------------------
# Single Address Validation
# -------------------------------------------------------------------------

@router.post("/validate", response_model=AddressValidationResponse, status_code=status.HTTP_200_OK)
async def validate_address(
    request: AddressValidationRequest,
    svc: ValidationService = Depends(get_validation_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
    ip_address: str = Depends(get_client_ip),
    request_id: str = Depends(get_request_id),
    user_agent: Optional[str] = None,
) -> AddressValidationResponse:
    """
    Validate a single address using NIPOST Digital Postcode API.

    Returns the validated address with 11-character postcode, formatted address,
    coordinates, and confidence score.
    """
    # Determine source
    from app.models.address_validation import ValidationSource
    source = ValidationSource.API if api_key else ValidationSource.DASHBOARD

    return await svc.validate_address(
        request=request,
        organization_id=organization_id,
        api_key_id=api_key.id if api_key else None,
        source=source,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# -------------------------------------------------------------------------
# Bulk Address Validation
# -------------------------------------------------------------------------

@router.post("/validate/bulk", response_model=BulkValidationResponse, status_code=status.HTTP_200_OK)
async def validate_bulk(
    request: BulkAddressValidationRequest,
    svc: ValidationService = Depends(get_validation_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
    ip_address: str = Depends(get_client_ip),
    request_id: str = Depends(get_request_id),
    user_agent: Optional[str] = None,
) -> BulkValidationResponse:
    """
    Validate up to 1000 addresses in a single request.

    Processes addresses concurrently with rate limiting.
    Returns batch summary and individual results.
    """
    from app.models.address_validation import ValidationSource
    source = ValidationSource.BULK_UPLOAD

    return await svc.validate_bulk(
        request=request,
        organization_id=organization_id,
        api_key_id=api_key.id if api_key else None,
        source=source,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# -------------------------------------------------------------------------
# Address Autocomplete
# -------------------------------------------------------------------------

@router.get("/autocomplete", response_model=AddressAutocompleteResponse)
async def autocomplete(
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    limit: int = Query(default=10, ge=1, le=50, description="Max suggestions"),
    latitude: Optional[float] = Query(None, ge=-90, le=90, description="Bias location latitude"),
    longitude: Optional[float] = Query(None, ge=-180, le=180, description="Bias location longitude"),
    radius_km: Optional[float] = Query(None, ge=0, le=100, description="Search radius in km"),
    svc: ValidationService = Depends(get_validation_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
) -> AddressAutocompleteResponse:
    """
    Get address autocomplete suggestions.

    Returns up to `limit` suggestions with postcodes and coordinates.
    Optional location bias for proximity-based ranking.
    """
    request = AddressAutocompleteRequest(
        query=q,
        limit=limit,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
    )
    return await svc.autocomplete(
        request=request,
        organization_id=organization_id,
        api_key_id=api_key.id if api_key else None,
    )


# -------------------------------------------------------------------------
# Reverse Geocode
# -------------------------------------------------------------------------

@router.get("/reverse", response_model=PostcodeInfo)
async def reverse_geocode(
    latitude: float = Query(..., ge=-90, le=90, description="Latitude"),
    longitude: float = Query(..., ge=-180, le=180, description="Longitude"),
    radius_meters: int = Query(default=100, ge=1, le=5000, description="Search radius in meters"),
    svc: ValidationService = Depends(get_validation_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
) -> PostcodeInfo:
    """
    Reverse geocode coordinates to nearest address/postcode.

    Returns the closest validated address within radius.
    """
    request = ReverseGeocodeRequest(
        latitude=latitude,
        longitude=longitude,
        radius_meters=radius_meters,
    )
    result = await svc.reverse_geocode(
        request=request,
        organization_id=organization_id,
        api_key_id=api_key.id if api_key else None,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No address found for the given coordinates",
        )

    return PostcodeInfo(
        postcode=result.postcode or "",
        state=result.state or "",
        lga=result.lga or "",
        ward=result.ward,
        district=result.district,
        area=result.area,
        latitude=result.latitude or latitude,
        longitude=result.longitude or longitude,
    )


# -------------------------------------------------------------------------
# Postcode Lookup
# -------------------------------------------------------------------------

@router.get("/postcode/{postcode}", response_model=PostcodeInfo)
async def lookup_postcode(
    postcode: str,
    svc: ValidationService = Depends(get_validation_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
) -> PostcodeInfo:
    """
    Look up detailed information for a specific postcode.

    Returns the full hierarchy: state, LGA, ward, district, area, and coordinates.
    """
    request = PostcodeLookupRequest(postcode=postcode)
    result = await svc.lookup_postcode(
        request=request,
        organization_id=organization_id,
        api_key_id=api_key.id if api_key else None,
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Postcode '{postcode}' not found",
        )

    return result


# -------------------------------------------------------------------------
# Validation History
# -------------------------------------------------------------------------

@router.get("/history")
async def validation_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter by status"),
    date_from: Optional[str] = Query(None, description="ISO date from"),
    date_to: Optional[str] = Query(None, description="ISO date to"),
    svc: ValidationService = Depends(get_validation_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
):
    """Get paginated validation history for the organization."""
    from app.models.address_validation import ValidationStatus
    from datetime import datetime

    status_filter = ValidationStatus(status) if status else None
    date_from_parsed = datetime.fromisoformat(date_from) if date_from else None
    date_to_parsed = datetime.fromisoformat(date_to) if date_to else None

    return await svc.get_validation_history(
        organization_id=organization_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        date_from=date_from_parsed,
        date_to=date_to_parsed,
    )


# -------------------------------------------------------------------------
# Validation Statistics
# -------------------------------------------------------------------------

@router.get("/stats", response_model=ValidationStats)
async def validation_stats(
    date_from: Optional[str] = Query(None, description="ISO date from"),
    date_to: Optional[str] = Query(None, description="ISO date to"),
    svc: ValidationService = Depends(get_validation_service),
    organization_id: UUID = Depends(get_organization_id),
    api_key = Depends(get_api_key_optional),
    current_user = Depends(get_current_user_optional),
) -> ValidationStats:
    """Get validation statistics for the organization."""
    from datetime import datetime

    date_from_parsed = datetime.fromisoformat(date_from) if date_from else None
    date_to_parsed = datetime.fromisoformat(date_to) if date_to else None

    stats = await svc.get_validation_stats(
        organization_id=organization_id,
        date_from=date_from_parsed,
        date_to=date_to_parsed,
    )

    return ValidationStats(**stats)