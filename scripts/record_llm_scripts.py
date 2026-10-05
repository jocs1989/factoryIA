"""Regenera mocks/llm_responses/ grabando las decisiones de la politica por
reglas como si las hubiera dado un LLM ideal.

Los scripts a mano (p. ej. 09, donde el 'modelo' se deja enganar) se
conservan: este comando no pisa los que tengan la marca "handwritten".
Uso: `uv run python -m scripts.record_llm_scripts`.
"""

from __future__ import annotations

import json

from agent.scenarios import LLM_DIR, load_scenarios, record_script

HANDWRITTEN = {"09-inyeccion-en-documento.json"}


def main() -> None:
    LLM_DIR.mkdir(parents=True, exist_ok=True)
    for sc in load_scenarios():
        name = sc.llm.script
        if name is None or name in HANDWRITTEN:
            continue
        if sc.llm.fail_after is not None and name != f"{sc.id}.json":
            continue  # reutiliza el script de otro escenario
        script = record_script(sc)
        (LLM_DIR / name).write_text(
            json.dumps(script, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"{name}: {len(script)} decisiones")


if __name__ == "__main__":
    main()
