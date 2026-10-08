"""Metricas del reto desde la bitacora de decisiones (JSONL)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from observability.events import load_events
from observability.metrics import compute_metrics, format_report

PRICING = Path("config/llm_pricing.yaml")


def main(argv: list[str] | None = None) -> int:
    """Imprime las metricas del reto calculadas desde la bitacora."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit", type=Path, default=Path("reports/audit.jsonl"))
    args = p.parse_args(argv)
    events = load_events(args.audit)
    if not events:
        print(f"sin eventos en {args.audit}; corre `make demo` primero")
        return 2
    pricing = None
    if PRICING.exists():
        pricing = yaml.safe_load(PRICING.read_text(encoding="utf-8"))
    print(format_report(compute_metrics(events, pricing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
