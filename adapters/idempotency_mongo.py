from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError


class MongoIdempotency:
    """El _id es la clave: el indice unico impide dos resultados."""

    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._coll = collection

    def get(self, key: str) -> dict[str, Any] | None:
        doc = self._coll.find_one({"_id": key})
        return doc["result"] if doc else None

    def put(self, key: str, result: dict[str, Any]) -> None:
        # Si ya hay uno, gana el primero.
        with contextlib.suppress(DuplicateKeyError):
            self._coll.insert_one(
                {
                    "_id": key,
                    "result": result,
                    "created_at": datetime.now(UTC),  # indice TTL
                }
            )
