"""Prueba de humo con un LLM real (OpenAI): ¿el modelo realmente responde?

Corre un escenario con la politica `llm` y un proveedor real, y reporta
cuantas decisiones tomo el MODELO y cuantas cayeron a las reglas.

Las credenciales se leen de un archivo tipo `.env` que tu indicas con
`--env-file`, SOLO en la memoria de este proceso: no se escriben en el
repo, no se exportan al shell y nunca se imprimen. Solo se cargan las
variables de la lista permitida de abajo; el resto del archivo se ignora.

  uv run python -m scripts.smoke_llm --env-file /ruta/al/env --scenario 01
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from adapters.llm.registry import create_llm
from agent.scenarios import load_scenarios, run_scenario
from cli._output import summary, timeline
from ports import LLMError

# Unicas variables que se toman del archivo (se ignora todo lo demas).
ALLOWED = (
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "LLM_MODEL",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_DEPLOYMENT_NAME",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_TIMEOUT_SEC",
)


def read_allowed(path: Path) -> dict[str, str]:
    """Lee `KEY=VALUE` (admite `export` y comillas); solo las permitidas."""
    found: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in ALLOWED and value:
            found[key] = value
    return found


def main(argv: list[str] | None = None) -> int:
    """Corre un escenario con un modelo real e informa sus decisiones."""
    os.environ.setdefault("AGENT_ENV", "mock")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--env-file", type=Path, help="archivo con OPENAI_API_KEY")
    p.add_argument("--scenario", default="01", help="prefijo del escenario")
    p.add_argument("--model", help="modelo (por defecto el del proveedor)")
    p.add_argument("--timeline", action="store_true")
    args = p.parse_args(argv)

    env = dict(os.environ)
    if args.env_file:
        if not args.env_file.is_file():
            print(f"no existe {args.env_file}")
            return 2
        env.update(read_allowed(args.env_file))
    provider = "azure" if env.get("AZURE_OPENAI_API_KEY") else "openai"
    if provider == "openai" and not env.get("OPENAI_API_KEY"):
        print(
            "falta OPENAI_API_KEY o AZURE_OPENAI_API_KEY "
            "(en el entorno o en --env-file)"
        )
        return 2
    model = args.model or env.get("OPENAI_MODEL") or env.get("LLM_MODEL")

    found = [s for s in load_scenarios() if s.id.startswith(args.scenario)]
    if not found:
        print(f"sin escenario {args.scenario!r}")
        return 2
    sc = found[0]
    try:
        # `env=` evita tocar os.environ: la clave vive solo en este objeto.
        llm = create_llm(provider, model=model, env=env)
    except LLMError as exc:
        print(f"no se pudo crear el proveedor: {exc}")
        return 2

    print(f"{sc.id}: {sc.title}\nproveedor: {provider}")
    result = run_scenario(sc, "llm", llm=llm)
    if args.timeline:
        print("\n".join(timeline(result)))
    print(summary(result))

    calls = [e for e in result.events if e.type == "llm"]
    by = Counter(e.outcome for e in calls)
    tin = sum(e.tokens_in for e in calls)
    tout = sum(e.tokens_out for e in calls)
    used = sorted({e.model for e in calls if e.model})
    print(
        f"\ndecisiones del modelo: {by.get('ok', 0)} de {len(calls)} "
        f"(invalidas/error: {by.get('invalid', 0) + by.get('error', 0)}, "
        f"circuito abierto: {by.get('circuit_open', 0)})"
    )
    print(f"modelo que respondio: {', '.join(used) or '-'}")
    print(f"tokens: {tin} entrada, {tout} salida")
    if by.get("ok", 0) == 0:
        print("El modelo NO respondio de forma util: decidieron las reglas.")
        return 1
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
