"""Compuerta de documentacion: cobertura de docstrings publica.

Superficie publica = modulos, clases y funciones de nivel de modulo y metodos
de clases publicas, cuyo nombre no empieza con guion bajo (se excluyen
`__init__`, pruebas y closures). Uso:

  uv run python -m scripts.check_docstrings --min 85 [--list]
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

PACKAGES = (
    "api",
    "config",
    "domain",
    "adapters",
    "tools",
    "mocks",
    "agent",
    "observability",
    "cli",
    "scripts",
    "ports.py",
)
SKIP_METHODS = {"__init__", "__post_init__"}


def public_items(path: Path) -> list[tuple[str, bool]]:
    """Devuelve (nombre calificado, tiene docstring) de lo publico."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, bool]] = [
        (f"{path}:<modulo>", bool(ast.get_docstring(tree)))
    ]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                out.append(
                    (f"{path}:{node.name}", bool(ast.get_docstring(node)))
                )
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            out.append((f"{path}:{node.name}", bool(ast.get_docstring(node))))
            for sub in node.body:
                if (
                    isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not sub.name.startswith("_")
                    and sub.name not in SKIP_METHODS
                ):
                    out.append(
                        (
                            f"{path}:{node.name}.{sub.name}",
                            bool(ast.get_docstring(sub)),
                        )
                    )
    return out


def collect(root: Path = Path(".")) -> list[tuple[str, bool]]:
    """Items publicos de los paquetes y si tienen docstring."""
    files: list[Path] = []
    for pkg in PACKAGES:
        base = root / pkg
        files += [base] if base.suffix == ".py" else sorted(base.rglob("*.py"))
    items: list[tuple[str, bool]] = []
    for f in files:
        if f.name != "__init__.py":
            items += public_items(f)
    return items


def main(argv: list[str] | None = None) -> int:
    """Falla si la cobertura de docstrings baja del minimo."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--min", type=float, default=85.0, help="% minimo")
    p.add_argument("--list", action="store_true", help="lista lo que falta")
    args = p.parse_args(argv)
    items = collect()
    done = sum(1 for _, ok in items if ok)
    pct = 100 * done / len(items)
    if args.list:
        for name, ok in items:
            if not ok:
                print(name)
    print(f"docstrings: {done}/{len(items)} = {pct:.1f}% (minimo {args.min}%)")
    return 0 if pct >= args.min else 1


if __name__ == "__main__":
    sys.exit(main())
