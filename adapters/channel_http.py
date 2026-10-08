"""Cliente HTTP del canal de mensajeria saliente."""

from __future__ import annotations

from adapters.http_client import ProviderClient


class HttpChannel:
    """Envia mensajes al cliente a traves del proveedor de mensajeria."""

    def __init__(self, http: ProviderClient) -> None:
        self._http = http

    def send(self, case_id: str, text: str) -> str:
        """Envia el texto y devuelve el id del mensaje."""
        raw = self._http.post(
            "/api/channel/send", {"case_id": case_id, "text": text}
        )
        return str(raw["message_id"])
