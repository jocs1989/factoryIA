"""Formato comun de las CLIs."""

from __future__ import annotations

from agent.scenarios import ScenarioResult


def timeline(result: ScenarioResult) -> list[str]:
    """Conversacion y decisiones de un escenario, en lineas legibles."""
    lines: list[str] = []
    for i, turn in enumerate(result.turns, start=1):
        lines.append(f"  turno {i}  Cliente: {turn.customer}")
        for m in turn.messages:
            for j, part in enumerate(m.splitlines() or [""]):
                prefix = (
                    "           Agente:  "
                    if j == 0
                    else "                    "
                )
                lines.append(prefix + part)
        lines.append(f"           (etapa: {turn.stage})")
    lines.append("  linea de tiempo de decisiones:")
    for e in result.events:
        stage = f" -> {e.stage_after}" if e.stage_after else ""
        codes = f" {list(e.reason_codes)}" if e.reason_codes else ""
        lines.append(f"    {e.type:9} {e.name:28} {e.outcome:8}{stage}{codes}")
    return lines


def summary(result: ScenarioResult) -> str:
    """Una linea con el desenlace de un escenario."""
    mark = "PASS" if result.passed else "FAIL"
    tools = [e for e in result.events if e.type == "tool"]
    note = " (degrado a reglas)" if result.degraded else ""
    return (
        f"[{mark}] {result.scenario.id:30} -> {result.final_stage:18} "
        f"esperado {result.scenario.expected.stage:18} "
        f"tools={len(tools):2} negadas={len(result.denied_tools)}{note}"
    )
