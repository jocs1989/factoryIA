"""Valida el catalogo: schema, ids unicos, duplicados y shadowing.

Uso: `python -m mocks.validate [directorio]` (sale con 1 si hay errores).
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from pydantic import ValidationError

from mocks.model import Mapping


def _signature(m: Mapping) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    pats = tuple(
        sorted(
            ("+".join(p.jsonPathConcat or [p.jsonPath or ""]), p.equalTo)
            for p in m.request.bodyPatterns
        )
    )
    return m.request.method, m.request.path, pats


def validate_catalog(directory: Path) -> list[str]:
    """Errores del catalogo: esquema, ids repetidos, duplicados y shadowing."""
    errors: list[str] = []
    parsed: list[tuple[Path, Mapping]] = []
    for path in sorted(directory.rglob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            errors.append(f"{path}: JSON invalido: {exc}")
            continue
        for i, item in enumerate(raw if isinstance(raw, list) else [raw]):
            try:
                parsed.append((path, Mapping.model_validate(item)))
            except ValidationError as exc:
                msgs = "; ".join(
                    f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                    for e in exc.errors()
                )
                errors.append(f"{path}[{i}]: {msgs}")

    ids: dict[str, Path] = {}
    groups: dict[object, list[tuple[Path, Mapping]]] = defaultdict(list)
    for path, m in parsed:
        if m.id in ids:
            errors.append(f"{path}: id duplicado {m.id} (ya en {ids[m.id]})")
        ids[m.id] = path
        groups[_signature(m)].append((path, m))

    for items in groups.values():
        if len(items) < 2:
            continue
        names = ", ".join(m.id for _, m in items)
        if len({m.priority for _, m in items}) < len(items):
            errors.append(f"duplicado ambiguo (misma prioridad): {names}")
        else:
            errors.append(
                f"shadowing (el de mayor prioridad nunca se alcanza): {names}"
            )
    return errors


def main(argv: list[str]) -> int:
    """Valida el catalogo; sale con 1 si hay errores."""
    directory = Path(argv[1]) if len(argv) > 1 else Path("mocks/mappings")
    errors = validate_catalog(directory)
    for e in errors:
        print(f"ERROR {e}")
    if not errors:
        print(f"catalogo valido: {directory}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
