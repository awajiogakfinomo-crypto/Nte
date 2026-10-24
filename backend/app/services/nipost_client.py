"""NIPOST Postcode API Client with Mock Fallback for Development."""
import httpx
import logging
from typing import Optional, List, Dict, Any
from app.core.config import settings

logger = logging.getLogger(__name__)

# Mock data for development without API key
MOCK_STATES = [
    {"state": "Abia", "code": "AB", "capital": "Umuahia"},
    {"state": "Adamawa", "code": "AD", "capital": "Yola"},
    {"state": "Akwa Ibom", "code": "AK", "capital": "Uyo"},
    {"state": "Anambra", "code": "AN", "capital": "Awka"},
    {"state": "Bauchi", "code": "BA", "capital": "Bauchi"},
    {"state": "Bayelsa", "code": "BY", "capital": "Yenagoa"},
    {"state": "Benue", "code": "BE", "capital": "Makurdi"},
    {"state": "Borno", "code": "BO", "capital": "Maiduguri"},
    {"state": "Cross River", "code": "CR", "capital": "Calabar"},
    {"state": "Delta", "code": "DE", "capital": "Asaba"},
    {"state": "Ebonyi", "code": "EB", "capital": "Abakaliki"},
    {"state": "Edo", "code": "ED", "capital": "Benin City"},
    {"state": "Ekiti", "code": "EK", "capital": "Ado-Ekiti"},
    {"state": "Enugu", "code": "EN", "capital": "Enugu"},
    {"state": "Gombe", "code": "GO", "capital": "Gombe"},
    {"state": "Imo", "code": "IM", "capital": "Owerri"},
    {"state": "Jigawa", "code": "JI", "capital": "Dutse"},
    {"state": "Kaduna", "code": "KD", "capital": "Kaduna"},
    {"state": "Kano", "code": "KN", "capital": "Kano"},
    {"state": "Katsina", "code": "KT", "capital": "Katsina"},
    {"state": "Kebbi", "code": "KE", "capital": "Birnin Kebbi"},
    {"state": "Kogi", "code": "KO", "capital": "Lokoja"},
    {"state": "Kwara", "code": "KW", "capital": "Ilorin"},
    {"state": "Lagos", "code": "LA", "capital": "Ikeja"},
    {"state": "Nasarawa", "code": "NA", "capital": "Lafia"},
    {"state": "Niger", "code": "NI", "capital": "Minna"},
    {"state": "Ogun", "code": "OG", "capital": "Abeokuta"},
    {"state": "Ondo", "code": "ON", "capital": "Akure"},
    {"state": "Osun", "code": "OS", "capital": "Oshogbo"},
    {"state": "Oyo", "code": "OY", "capital": "Ibadan"},
    {"state": "Plateau", "code": "PL", "capital": "Jos"},
    {"state": "Rivers", "code": "RV", "capital": "Port Harcourt"},
    {"state": "Sokoto", "code": "SO", "capital": "Sokoto"},
    {"state": "Taraba", "code": "TA", "capital": "Jalingo"},
    {"state": "Yobe", "code": "YO", "capital": "Damaturu"},
    {"state": "Zamfara", "code": "ZA", "capital": "Gusau"},
    {"state": "FCT", "code": "FC", "capital": "Abuja"},
]

MOCK_LGAS = {
    "Lagos": ["Agege", "Ajeromi-Ifelodun", "Alimosho", "Amuwo-Odofin", "Apapa", "Badagry", "Epe", "Eti-Osa", "Ibeju-Lekki", "Ifako-Ijaiye", "Ikeja", "Ikorodu", "Kosofe", "Lagos Island", "Lagos Mainland", "Mushin", "Ojo", "Oshodi-Isolo", "Shomolu", "Surulere"],
    "FCT": ["Abaji", "Abuja Municipal", "Bwari", "Gwagwalada", "Kuje", "Kwali"],
    "Kano": ["Ajingi", "Albasu", "Bagwai", "Bebeji", "Bichi", "Bunkure", "Dala", "Dambatta", "Dawakin Kudu", "Dawakin Tofa", "Doguwa", "Fagge", "Gabasawa", "Garko", "Garun Mallam", "Gaya", "Gezawa", "Gwale", "Gwarzo", "Kabo", "Kano Municipal", "Karaye", "Kibiya", "Kiru", "Kumbotso", "Kunchi", "Kura", "Madobi", "Makoda", "Minjibir", "Nasarawa", "Rano", "Rimin Gado", "Rogo", "Shanono", "Sumaila", "Takai", "Tarauni", "Tofa", "Tsanyawa", "Tudun Wada", "Ungogo", "Warawa", "Wudil"],
}

MOCK_POSTCODES = {
    ("Lagos", "Ikeja"): ["100001", "100211", "100212", "100213", "100214", "100215"],
    ("Lagos", "Lagos Island"): ["101001", "101002", "101003", "101004", "101005", "101006", "101007", "101008"],
    ("Lagos", "Surulere"): ["101211", "101212", "101213", "101214", "101215", "101216"],
    ("FCT", "Abuja Municipal"): ["900001", "900101", "900102", "900103", "900104", "900105"],
    ("FCT", "Gwagwalada"): ["900106", "900107", "900108"],
    ("Kano", "Kano Municipal"): ["700001", "700002", "700003", "700004", "700005"],
}


class NIPostClient:
    """Client for NIPOST Digital Postcode API with mock fallback."""

    def __init__(self):
        self.base_url = settings.POSTCODE_API_URL.rstrip("/")
        self.api_key = settings.POSTCODE_API_KEY
        self.use_mock = not self.api_key or self.api_key == "test"
        
        if self.use_mock:
            logger.warning("NIPOST API key not set — using MOCK data for development")
        
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "Nte/0.1.0"} if not self.use_mock else {}
        )

    async def close(self):
        await self.client.aclose()

    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        if self.use_mock:
            raise NotImplementedError("Mock mode - use mock methods directly")
        
        headers = {"Authorization": f"Bearer {self.api_key}"}
        url = f"{self.base_url}{endpoint}"
        response = await self.client.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()

    # ============ MOCK METHODS (for development) ============
    
    async def get_states(self) -> List[Dict[str, Any]]:
        """Get all Nigerian states."""
        if self.use_mock:
            return MOCK_STATES
        return await self._request("GET", "/states")

    async def get_lgas(self, state: str) -> List[str]:
        """Get LGAs for a state."""
        if self.use_mock:
            return MOCK_LGAS.get(state, [f"{state} LGA"])
        return await self._request("GET", f"/states/{state}/lgas")

    async def get_postcodes(self, state: str, lga: str) -> List[str]:
        """Get postcodes for a state/LGA."""
        if self.use_mock:
            return MOCK_POSTCODES.get((state, lga), [f"{state[:2].upper()}{hash(lga) % 100000:05d}"])
        return await self._request("GET", f"/states/{state}/lgas/{lga}/postcodes")

    async def validate_address(self, state: str, lga: str, postcode: str) -> Dict[str, Any]:
        """Validate an address/postcode combination."""
        if self.use_mock:
            valid = postcode in MOCK_POSTCODES.get((state, lga), [])
            return {
                "valid": valid,
                "state": state,
                "lga": lga,
                "postcode": postcode,
                "message": "Valid postcode" if valid else "Invalid postcode for this LGA",
                "source": "mock"
            }
        return await self._request("POST", "/validate", json={
            "state": state, "lga": lga, "postcode": postcode
        })

    async def lookup_postcode(self, postcode: str) -> Optional[Dict[str, Any]]:
        """Look up postcode details."""
        if self.use_mock:
            for (state, lga), codes in MOCK_POSTCODES.items():
                if postcode in codes:
                    return {"state": state, "lga": lga, "postcode": postcode, "source": "mock"}
            return None
        return await self._request("GET", f"/postcodes/{postcode}")

    async def search_address(self, query: str) -> List[Dict[str, Any]]:
        """Search addresses by query string."""
        if self.use_mock:
            results = []
            query_lower = query.lower()
            for state in MOCK_STATES:
                if query_lower in state["state"].lower() or query_lower in state["capital"].lower():
                    results.append({**state, "source": "mock"})
            return results[:10]
        return await self._request("GET", "/search", params={"q": query})

    # ============ REAL API METHODS (when key available) ============
    
    # The real API calls would go here when API key is available
    # For now, mock methods above handle all cases


# Global client instance
nipost_client = NIPostClient()
