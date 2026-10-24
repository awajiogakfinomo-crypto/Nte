"""NIPOST Postcode API client with circuit breaker, caching, and bulk operations."""
import asyncio
import hashlib
import time
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from enum import Enum

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
)
import structlog

from app.core.config import settings
from app.core.cache import cache_manager
from app.schemas.address import (
    ValidationStatus,
    AddressValidationResult,
    PostcodeInfo,
    AutocompleteSuggestion,
)

logger = structlog.get_logger()


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Circuit breaker for external API calls."""
    failure_threshold: int = 5
    recovery_timeout: int = 60
    half_open_max_calls: int = 3

    def __post_init__(self):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.half_open_calls = 0
        self._lock = asyncio.Lock()

    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        async with self._lock:
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                    logger.info("circuit_breaker_half_open")
                else:
                    raise CircuitBreakerOpenError("Circuit breaker is OPEN")

            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpenError("Circuit breaker half-open limit reached")
                self.half_open_calls += 1

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self.on_success()
            return result
        except Exception as e:
            async with self._lock:
                self.on_failure()
            raise

    def on_success(self):
        """Reset on successful call."""
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            logger.info("circuit_breaker_closed")

    def on_failure(self):
        """Record failure and potentially open circuit."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning("circuit_breaker_opened", failures=self.failure_count)


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


class NIPostClient:
    """NIPOST Digital Postcode API client."""

    def __init__(self):
        self.base_url = settings.POSTCODE_API_URL.rstrip("/")
        self.api_key = settings.POSTCODE_API_KEY
        self.circuit_breaker = CircuitBreaker()
        self._client: Optional[httpx.AsyncClient] = None
        self._semaphore = asyncio.Semaphore(20)  # Max concurrent requests

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(30.0, connect=10.0),
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
                headers={
                    "User-Agent": "Usuk/0.1.0",
                    "Accept": "application/json",
                    **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
                },
            )
        return self._client

    async def close(self):
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _cache_key(self, *parts: str) -> str:
        """Generate cache key from parts."""
        return "nipost:" + ":".join(parts)

    def _address_hash(self, address: str, landmarks: str = "", lat: float = None, lon: float = None) -> str:
        """Generate hash for address validation caching."""
        content = f"{address}|{landmarks}|{lat}|{lon}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    # -------------------------------------------------------------------------
    # Core Request Methods with Retry & Circuit Breaker
    # -------------------------------------------------------------------------

    @retry(
        wait=wait_exponential_jitter(initial=1, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError)),
    )
    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with retry logic."""
        client = await self._get_client()
        response = await client.request(method, endpoint, **kwargs)
        response.raise_for_status()
        return response.json()

    async def _request_with_circuit(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make request with circuit breaker."""
        return await self.circuit_breaker.call(self._request, method, endpoint, **kwargs)

    # -------------------------------------------------------------------------
    # Address Validation
    # -------------------------------------------------------------------------

    async def validate_address(
        self,
        address: str,
        landmarks: str = "",
        latitude: float = None,
        longitude: float = None,
        postcode_level: str = "building",
        use_cache: bool = True,
    ) -> AddressValidationResult:
        """Validate a single address."""
        start_time = time.time()

        # Check cache first
        cache_key = self._cache_key("validate", self._address_hash(address, landmarks, latitude, longitude))
        if use_cache:
            cached = await cache_manager.get(cache_key)
            if cached:
                cached["processing_time_ms"] = int((time.time() - start_time) * 1000)
                return AddressValidationResult(**cached)

        # Call NIPOST API
        try:
            payload = {
                "address": address,
                "landmarks": landmarks,
                "postcode_level": postcode_level,
            }
            if latitude is not None and longitude is not None:
                payload["latitude"] = latitude
                payload["longitude"] = longitude

            data = await self._request_with_circuit("POST", "/api/v1/validate", json=payload)
            result = self._parse_validation_response(data)
            result.processing_time_ms = int((time.time() - start_time) * 1000)

            # Cache result
            if use_cache:
                await cache_manager.set(cache_key, result.model_dump(), ttl=3600)

            return result

        except CircuitBreakerOpenError:
            logger.warning("nipost_circuit_open", address=address[:50])
            return AddressValidationResult(
                raw_address=address,
                raw_landmarks=landmarks,
                input_latitude=latitude,
                input_longitude=longitude,
                status=ValidationStatus.ERROR,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error_code="CIRCUIT_OPEN",
                error_message="NIPOST API temporarily unavailable",
            )
        except httpx.HTTPStatusError as e:
            logger.error("nipost_http_error", status=e.response.status_code, address=address[:50])
            return AddressValidationResult(
                raw_address=address,
                raw_landmarks=landmarks,
                input_latitude=latitude,
                input_longitude=longitude,
                status=ValidationStatus.ERROR,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error_code=f"HTTP_{e.response.status_code}",
                error_message=e.response.text[:200],
            )
        except Exception as e:
            logger.error("nipost_validation_error", error=str(e), address=address[:50])
            return AddressValidationResult(
                raw_address=address,
                raw_landmarks=landmarks,
                input_latitude=latitude,
                input_longitude=longitude,
                status=ValidationStatus.ERROR,
                processing_time_ms=int((time.time() - start_time) * 1000),
                error_code="CLIENT_ERROR",
                error_message=str(e)[:200],
            )

    async def bulk_validate(
        self,
        addresses: List[Dict[str, Any]],
        postcode_level: str = "building",
        max_concurrent: int = 20,
    ) -> List[AddressValidationResult]:
        """Validate multiple addresses concurrently with semaphore limiting."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def validate_one(addr_data: Dict[str, Any]) -> AddressValidationResult:
            async with semaphore:
                return await self.validate_address(
                    address=addr_data["address"],
                    landmarks=addr_data.get("landmarks", ""),
                    latitude=addr_data.get("latitude"),
                    longitude=addr_data.get("longitude"),
                    postcode_level=postcode_level,
                )

        tasks = [validate_one(addr) for addr in addresses]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle exceptions
        validated_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("bulk_validation_failed", index=i, error=str(result))
                validated_results.append(AddressValidationResult(
                    raw_address=addresses[i].get("address", ""),
                    raw_landmarks=addresses[i].get("landmarks", ""),
                    input_latitude=addresses[i].get("latitude"),
                    input_longitude=addresses[i].get("longitude"),
                    status=ValidationStatus.ERROR,
                    error_code="TASK_ERROR",
                    error_message=str(result)[:200],
                ))
            else:
                validated_results.append(result)

        return validated_results

    def _parse_validation_response(self, data: Dict[str, Any]) -> AddressValidationResult:
        """Parse NIPOST validation response."""
        # Handle both success and error responses
        status_map = {
            "valid": ValidationStatus.VALID,
            "invalid": ValidationStatus.INVALID,
            "partial": ValidationStatus.PARTIAL,
            "error": ValidationStatus.ERROR,
        }

        return AddressValidationResult(
            raw_address=data.get("raw_address", ""),
            raw_landmarks=data.get("raw_landmarks"),
            input_latitude=data.get("input_latitude"),
            input_longitude=data.get("input_longitude"),
            status=status_map.get(data.get("status", "error"), ValidationStatus.ERROR),
            postcode=data.get("postcode"),
            postcode_level=data.get("postcode_level"),
            formatted_address=data.get("formatted_address"),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            state=data.get("state"),
            lga=data.get("lga"),
            ward=data.get("ward"),
            district=data.get("district"),
            area=data.get("area"),
            confidence_score=data.get("confidence_score"),
            match_type=data.get("match_type"),
            suggestions=data.get("suggestions"),
            processing_time_ms=data.get("processing_time_ms", 0),
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
        )

    # -------------------------------------------------------------------------
    # Postcode Lookup
    # -------------------------------------------------------------------------

    async def lookup_postcode(self, postcode: str, use_cache: bool = True) -> Optional[PostcodeInfo]:
        """Look up postcode details."""
        if use_cache:
            cached = await cache_manager.get_postcode(postcode)
            if cached:
                return PostcodeInfo(**cached)

        try:
            data = await self._request_with_circuit("GET", f"/api/v1/postcode/{postcode}")
            result = PostcodeInfo(**data)
            if use_cache:
                await cache_manager.set_postcode(postcode, data)
            return result
        except Exception as e:
            logger.error("nipost_postcode_lookup_failed", postcode=postcode, error=str(e))
            return None

    # -------------------------------------------------------------------------
    # Autocomplete
    # -------------------------------------------------------------------------

    async def autocomplete(
        self,
        query: str,
        limit: int = 10,
        latitude: float = None,
        longitude: float = None,
        radius_km: float = None,
        use_cache: bool = True,
    ) -> List[AutocompleteSuggestion]:
        """Get address autocomplete suggestions."""
        if use_cache:
            cached = await cache_manager.get_autocomplete(query, latitude, longitude)
            if cached:
                return [AutocompleteSuggestion(**s) for s in cached]

        try:
            params = {"q": query, "limit": limit}
            if latitude is not None:
                params["lat"] = latitude
            if longitude is not None:
                params["lon"] = longitude
            if radius_km is not None:
                params["radius_km"] = radius_km

            data = await self._request_with_circuit("GET", "/api/v1/autocomplete", params=params)
            suggestions = [AutocompleteSuggestion(**s) for s in data.get("suggestions", [])]

            if use_cache:
                await cache_manager.set_autocomplete(
                    query, [s.model_dump() for s in suggestions], latitude, longitude
                )

            return suggestions
        except Exception as e:
            logger.error("nipost_autocomplete_failed", query=query, error=str(e))
            return []

    # -------------------------------------------------------------------------
    # Reverse Geocode
    # -------------------------------------------------------------------------

    async def reverse_geocode(
        self,
        latitude: float,
        longitude: float,
        radius_meters: int = 100,
        use_cache: bool = True,
    ) -> Optional[AddressValidationResult]:
        """Reverse geocode coordinates to address."""
        cache_key = self._cache_key("reverse", f"{latitude:.6f}:{longitude:.6f}:{radius_meters}")
        if use_cache:
            cached = await cache_manager.get(cache_key)
            if cached:
                return AddressValidationResult(**cached)

        try:
            data = await self._request_with_circuit(
                "GET",
                "/api/v1/reverse",
                params={"lat": latitude, "lon": longitude, "radius": radius_meters}
            )
            result = self._parse_validation_response(data)
            if use_cache:
                await cache_manager.set(cache_key, result.model_dump(), ttl=3600)
            return result
        except Exception as e:
            logger.error("nipost_reverse_geocode_failed", lat=latitude, lon=longitude, error=str(e))
            return None

    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------

    async def health_check(self) -> Dict[str, Any]:
        """Check NIPOST API health."""
        try:
            data = await self._request("GET", "/health")
            return {"status": "healthy", "nipost": data}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


# Global instance
nipost_client = NIPostClient()