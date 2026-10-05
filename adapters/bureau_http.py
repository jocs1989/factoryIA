from __future__ import annotations

from adapters.http_client import ProviderClient
from domain.profile import BureauProfile

MIN_HISTORY_MONTHS = 12


class HttpBureau:
    """Consulta el buro y NORMALIZA: el resto del sistema nunca ve el
    reporte crudo, solo el perfil."""

    def __init__(self, http: ProviderClient) -> None:
        self._http = http

    def query(self, customer_id: str) -> BureauProfile:
        raw = self._http.post(
            "/api/bureau/query", {"customer_id": customer_id}
        )
        score = raw.get("score")
        history = int(raw.get("history_months") or 0)
        return BureauProfile(
            score=int(score) if score is not None else None,
            active_delinquency=int(raw.get("accounts_delinquent") or 0) > 0,
            thin_file=history < MIN_HISTORY_MONTHS,
        )
