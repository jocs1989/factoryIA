"""Motor de mocks declarativo: resuelve (metodo, path, cuerpo) a un mapping.

Gana el de menor `priority`; a igual prioridad, el mas especifico (mas
bodyPatterns) y luego el id. Sin match, 404 con diagnostico de cercania.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mocks.model import BodyPattern, Mapping

_TEMPLATE = re.compile(r"\{\{request\.body\.([a-zA-Z0-9_.]+)\}\}")


class MockResponse(BaseModel):
    status: int
    body: Any
    delay_ms: int = 0
    mapping_id: str | None = None


def lookup(body: Any, path: str) -> Any:
    """`$.a.b` sobre dicts anidados. None si no existe."""
    node = body
    for part in path.removeprefix("$.").split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def as_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "null" if value is None else str(value)


def _selected(pattern: BodyPattern, body: Any) -> tuple[str, str]:
    if pattern.jsonPath is not None:
        return pattern.jsonPath, as_text(lookup(body, pattern.jsonPath))
    paths = pattern.jsonPathConcat or []
    return "+".join(paths), "".join(
        "" if (v := lookup(body, p)) is None else as_text(v) for p in paths
    )


def _matches(mapping: Mapping, body: Any) -> bool:
    return all(
        _selected(p, body)[1] == p.equalTo
        for p in mapping.request.bodyPatterns
    )


def _render(node: Any, body: Any) -> Any:
    if isinstance(node, str):
        return _TEMPLATE.sub(
            lambda m: as_text(lookup(body, "$." + m.group(1))), node
        )
    if isinstance(node, list):
        return [_render(n, body) for n in node]
    if isinstance(node, dict):
        return {k: _render(v, body) for k, v in node.items()}
    return node


def load_mappings(directory: Path) -> list[tuple[Path, Mapping]]:
    """Cada .json es un mapping o una lista de mappings."""
    found: list[tuple[Path, Mapping]] = []
    for path in sorted(directory.rglob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        for item in raw if isinstance(raw, list) else [raw]:
            found.append((path, Mapping.model_validate(item)))
    return found


class MockEngine:
    def __init__(self, mappings: Sequence[Mapping]) -> None:
        self._mappings = list(mappings)

    @classmethod
    def from_dir(cls, directory: Path) -> MockEngine:
        return cls([m for _, m in load_mappings(directory)])

    @property
    def mappings_loaded(self) -> int:
        return len(self._mappings)

    def ids(self) -> list[str]:
        return sorted(m.id for m in self._mappings)

    def handle(self, method: str, path: str, body: Any) -> MockResponse:
        same = [
            m
            for m in self._mappings
            if m.request.method == method.upper() and m.request.path == path
        ]
        hits = sorted(
            (m for m in same if _matches(m, body)),
            key=lambda m: (
                m.priority,
                -len(m.request.bodyPatterns),
                m.id,
            ),
        )
        if hits:
            m = hits[0]
            return MockResponse(
                status=m.response.status,
                body=_render(m.response.jsonBody, body),
                delay_ms=m.response.faultDelayMs,
                mapping_id=m.id,
            )
        return MockResponse(
            status=404, body=self._near_miss(method, path, body, same)
        )

    def _near_miss(
        self, method: str, path: str, body: Any, same: list[Mapping]
    ) -> dict[str, Any]:
        info: dict[str, Any] = {
            "error": "no_mock_matched",
            "method": method.upper(),
            "path": path,
        }
        if not same:
            other = sorted(
                {
                    m.request.method
                    for m in self._mappings
                    if m.request.path == path
                }
            )
            info["near_miss"] = (
                {"other_methods_for_path": other}
                if other
                else "ningun mapping para este path"
            )
            return info
        info["near_miss"] = [
            {
                "id": m.id,
                "expected": {
                    "+".join(p.jsonPathConcat or [p.jsonPath or ""]): p.equalTo
                    for p in m.request.bodyPatterns
                },
                "got": {
                    "+".join(
                        p.jsonPathConcat or [p.jsonPath or ""]
                    ): _selected(p, body)[1]
                    for p in m.request.bodyPatterns
                },
            }
            for m in same
        ]
        return info
