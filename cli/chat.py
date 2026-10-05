"""Chat con el agente: cliente simulado (--scenario) o interactivo."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable

from agent.runtime import Runtime, build_runtime
from agent.scenarios import load_scenarios, run_scenario
from agent.types import CustomerEvent, DocRef
from cli._output import summary, timeline
from config.settings import load_settings

DEFAULT_CASE = {
    "case_id": "chat-1",
    "customer_id": "cust-s01",
    "vehicle_id": "veh-s01",
    "customer_name": "Juan Pérez López",
    "declared_income": "20000.00",
    "requested_amount": "80000",
    "employment_type": "salaried",
    "phone_last4": "1234",
}
HELP = (
    "Escribe tu mensaje. Comandos: /doc <tipo> <id> adjunta un documento, "
    "/estado muestra la etapa, /salir termina."
)


def interactive(
    rt: Runtime,
    read: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> int:
    case = rt.create_case(dict(DEFAULT_CASE))
    session = rt.verify(case.case_id, DEFAULT_CASE["phone_last4"])
    out(HELP)
    while True:
        try:
            line = read("Tu> ").strip()
        except EOFError:
            return 0
        if not line:
            continue
        if line in ("/salir", "/quit"):
            return 0
        if line == "/estado":
            current = rt.deps.repo.get(case.case_id)
            out(f"etapa: {current.stage.value if current else '?'}")
            continue
        docs: tuple[DocRef, ...] = ()
        text = line
        if line.startswith("/doc"):
            parts = line.split()
            if len(parts) != 3:
                out("uso: /doc <tipo> <id>")
                continue
            docs = (DocRef(doc_type=parts[1], doc_id=parts[2]),)
            text = "Adjunto un documento"
        result = rt.runner.turn(
            session, CustomerEvent(text=text, documents=docs)
        )
        for m in result.messages:
            out(f"Agente> {m}")
        if result.outcome:
            out(f"[caso terminado: {result.outcome}]")
            return 0


def main(
    argv: list[str] | None = None,
    read: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> int:
    os.environ.setdefault("AGENT_ENV", "mock")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scenario", help="reproduce un escenario (p. ej. 05)")
    p.add_argument("--policy", choices=["rules", "llm"], default="rules")
    p.add_argument(
        "--llm",
        help="proveedor: openai, gemini, deepseek, "
        "anthropic o una cadena 'gemini,openai'",
    )
    args = p.parse_args(argv)
    settings = load_settings()
    if args.llm:
        settings = settings.model_copy(
            update={"llm_backend": args.llm, "policy": "llm"}
        )
    if args.scenario:
        found = [s for s in load_scenarios() if s.id.startswith(args.scenario)]
        if not found:
            out(f"sin escenario {args.scenario!r}")
            return 2
        result = run_scenario(
            found[0],
            "llm" if args.policy == "llm" else "rules",
            settings=settings,
        )
        out(found[0].title)
        out("\n".join(timeline(result)))
        out(summary(result))
        return 0 if result.passed else 1
    settings = settings.model_copy(
        update={
            "policy": "llm" if args.llm or args.policy == "llm" else "rules"
        }
    )
    return interactive(build_runtime(settings), read, out)


if __name__ == "__main__":
    sys.exit(main())
