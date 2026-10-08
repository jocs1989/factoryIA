"""Repositorio de casos en MongoDB con escritura optimista."""

from __future__ import annotations

from typing import Any

from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError

from domain.case import Case, StaleVersion
from ports import CaseExists, CaseNotFound


class MongoCaseRepository:
    """Casos en Mongo. La concurrencia optimista es un update condicional
    sobre `version`, atomico en el servidor."""

    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._coll = collection

    @staticmethod
    def _doc(case: Case) -> dict[str, Any]:
        return {"_id": case.case_id, **case.model_dump(mode="json")}

    def add(self, case: Case) -> None:
        """Inserta el caso; `CaseExists` si el indice unico lo rechaza."""
        try:
            self._coll.insert_one(self._doc(case))
        except DuplicateKeyError as exc:
            raise CaseExists(case.case_id) from exc

    def get(self, case_id: str) -> Case | None:
        """Carga y valida el caso.

        Falla si el documento no respeta el esquema.
        """
        doc = self._coll.find_one({"_id": case_id})
        if doc is None:
            return None
        doc.pop("_id")
        return Case.model_validate(doc)

    def save(self, case: Case, *, expected_version: int) -> None:
        """Actualiza solo si la version coincide (atomico en el servidor)."""
        res = self._coll.update_one(
            {"_id": case.case_id, "version": expected_version},
            {"$set": self._doc(case)},
        )
        if res.matched_count == 0:
            if self._coll.count_documents({"_id": case.case_id}, limit=1) == 0:
                raise CaseNotFound(case.case_id)
            raise StaleVersion(f"version distinta de v{expected_version}")
