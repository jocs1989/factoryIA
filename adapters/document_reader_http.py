from __future__ import annotations

from adapters.http_client import ProviderClient
from domain.hashing import canonical_hash
from ports import DocumentRef, Extraction


class HttpDocumentReader:
    """Lector de documentos (OCR o vision) detras de un servicio HTTP."""

    def __init__(self, http: ProviderClient) -> None:
        self._http = http

    def read(self, ref: DocumentRef) -> Extraction:
        raw = self._http.post(
            "/api/documents/extract",
            {"doc_id": ref.doc_id, "doc_type": ref.doc_type},
        )
        return Extraction.model_validate(
            {
                "doc_id": ref.doc_id,
                "doc_type": raw.get("doc_type", ref.doc_type),
                "content_hash": canonical_hash(raw),
                "fields": raw["fields"],
                "raw_text": raw.get("raw_text", ""),
            }
        )
