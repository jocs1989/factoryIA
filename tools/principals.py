"""Quien llama: identidad y permisos minimos (scopes)."""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: Literal["agent", "human", "anonymous"]
    scopes: frozenset[str]


ANONYMOUS = Principal(id="anonymous", kind="anonymous", scopes=frozenset())


class PrincipalRegistry:
    def __init__(
        self,
        principals: list[tuple[Principal, str]],
    ) -> None:
        # (principal, api_key); una clave vacia no es alcanzable por HTTP.
        self._by_id = {p.id: p for p, _ in principals}
        self._keys = [(k, p) for p, k in principals if k]

    @classmethod
    def from_yaml(
        cls, path: Path, env: Mapping[str, str]
    ) -> PrincipalRegistry:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        items: list[tuple[Principal, str]] = []
        for raw in data["principals"]:
            principal = Principal(
                id=raw["id"],
                kind=raw["kind"],
                scopes=frozenset(raw["scopes"]),
            )
            items.append((principal, env.get(raw.get("api_key_env", ""), "")))
        return cls(items)

    def has_key(self, principal_id: str) -> bool:
        """True si el principal tiene una credencial resuelta."""
        return any(p.id == principal_id for _, p in self._keys)

    def key_of(self, principal_id: str) -> str:
        """Credencial del principal (solo para validar su fortaleza)."""
        return next((k for k, p in self._keys if p.id == principal_id), "")

    def get(self, principal_id: str) -> Principal:
        return self._by_id[principal_id]

    def resolve(self, api_key: str | None) -> Principal | None:
        if not api_key:
            return None
        for key, principal in self._keys:
            if hmac.compare_digest(key, api_key):
                return principal
        return None
