from __future__ import annotations

from decimal import Decimal

from adapters.http_client import ProviderClient
from domain.eligibility import VehicleFacts
from ports import VehicleRecord


class HttpVehicleRegistry:
    def __init__(self, http: ProviderClient) -> None:
        self._http = http

    def get_vehicle(self, vehicle_id: str, customer_id: str) -> VehicleRecord:
        raw = self._http.post(
            "/api/vehicles/get",
            {"vehicle_id": vehicle_id, "customer_id": customer_id},
        )
        liens = raw.get("active_liens")
        return VehicleRecord(
            vehicle_id=vehicle_id,
            facts=VehicleFacts(
                owner_matches=raw.get("owner_matches"),
                has_liens=None if liens is None else int(liens) > 0,
                has_second_key=raw.get("second_key"),
            ),
            appraised_value=Decimal(str(raw["appraised_value"])),
        )
