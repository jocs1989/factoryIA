"""`make demo`: corre los escenarios y muestra su desenlace. Sin red."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agent.scenarios import load_scenarios, run_scenario
from cli._output import summary, timeline
from config.settings import load_settings


def main(argv: list[str] | None = None) -> int:
    """Corre los escenarios y muestra su desenlace, sin red."""
    os.environ.setdefault("AGENT_ENV", "mock")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy", choices=["rules", "llm"], default="rules")
    p.add_argument("--scenario", help="filtra por id (p. ej. 05)")
    p.add_argument(
        "--timeline",
        action="store_true",
        help="muestra la conversacion y las decisiones",
    )
    p.add_argument(
        "--audit",
        type=Path,
        help="escribe la bitacora JSONL (para `cli.report`)",
    )
    args = p.parse_args(argv)

    settings = load_settings()
    if args.audit:
        args.audit.parent.mkdir(parents=True, exist_ok=True)
        args.audit.write_text("", encoding="utf-8")
        settings = settings.model_copy(
            update={"audit_backend": "jsonl", "audit_path": str(args.audit)}
        )
    scenarios = [
        s
        for s in load_scenarios()
        if not args.scenario or s.id.startswith(args.scenario)
    ]
    if not scenarios:
        print(f"sin escenarios para {args.scenario!r}")
        return 2
    failed = 0
    for sc in scenarios:
        result = run_scenario(sc, args.policy, settings=settings)
        print(summary(result))
        if args.timeline:
            print(f"  {sc.title}")
            print("\n".join(timeline(result)))
            print()
        for problem in result.problems:
            print(f"      ! {problem}")
        failed += 0 if result.passed else 1
    print(
        f"\n{len(scenarios) - failed}/{len(scenarios)} escenarios con el "
        f"desenlace esperado (politica: {args.policy})"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
