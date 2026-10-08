"""Escenarios reproducibles: un cliente simulado conversa con el agente."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from adapters.llm.scripted import ScriptedLLM
from agent.runtime import Runtime, build_runtime
from agent.types import (
    Action,
    CustomerEvent,
    Policy,
    Reply,
    StageView,
    ToolCall,
)
from config.settings import Settings, load_settings
from ports import AuditEvent, LLMPort

SCENARIOS_DIR = Path("fixtures/scenarios")
LLM_DIR = Path("mocks/llm_responses")


class Checkpoint(BaseModel):
    """Etapa esperada tras un turno concreto del escenario."""

    after_turn: int
    stage: str


class Expected(BaseModel):
    """Desenlace esperado de un escenario."""

    stage: str
    reason_codes: list[str] = Field(default_factory=list)
    adversarial: bool = False
    data: dict[str, str] = Field(default_factory=dict)
    checkpoints: list[Checkpoint] = Field(default_factory=list)
    degraded: bool = False


class LlmSpec(BaseModel):
    """Guion del LLM de un escenario y, opcionalmente, cuando falla."""

    script: str | None = None
    fail_after: int | None = None


class Scenario(BaseModel):
    """Un escenario reproducible.

    Caso, turnos del cliente y desenlace esperado.
    """

    id: str
    title: str
    case: dict[str, Any]
    turns: list[CustomerEvent]
    expected: Expected
    llm: LlmSpec = Field(default_factory=LlmSpec)


def load_scenarios(directory: Path = SCENARIOS_DIR) -> list[Scenario]:
    """Carga los escenarios JSON de un directorio, ordenados por nombre."""
    return [
        Scenario.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(directory.glob("*.json"))
    ]


class RecordingPolicy(Policy):
    """Envuelve una politica y anota cada decision como respuesta de LLM."""

    name = "recording"

    def __init__(self, inner: Policy) -> None:
        self._inner = inner
        self.script: list[str] = []

    def next_action(self, view: StageView) -> Action:
        """Delega en la politica interna y anota la decision."""
        action = self._inner.next_action(view)
        raw: dict[str, Any]
        if isinstance(action, Reply):
            raw = {"action": "reply", "text": action.text}
        else:
            assert isinstance(action, ToolCall)
            raw = {"action": "tool", "tool": action.tool, "args": action.args}
        self.script.append(json.dumps(raw, ensure_ascii=False))
        return action


@dataclass
class TurnLog:
    """Un turno ocurrido.

    Lo que dijo el cliente, lo que respondio el agente y la etapa.
    """

    customer: str
    messages: list[str]
    stage: str


@dataclass
class ScenarioResult:
    """Resultado de correr un escenario, con sus problemas si no cumple."""

    scenario: Scenario
    policy: str
    final_stage: str
    turns: list[TurnLog]
    events: list[AuditEvent]
    runtime: Runtime
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True si el escenario termino como se esperaba."""
        return not self.problems

    @property
    def degraded(self) -> bool:
        """True si el LLM fallo y se uso la politica por reglas."""
        return any(e.type == "llm" and e.outcome != "ok" for e in self.events)

    @property
    def denied_tools(self) -> list[str]:
        """Tools que el ejecutor nego durante el escenario."""
        return [
            e.name
            for e in self.events
            if e.type == "tool" and e.outcome == "denied"
        ]


def _settings(policy: str, base: Settings | None) -> Settings:
    s = base or load_settings()
    return s.model_copy(update={"policy": policy})


def run_scenario(
    scenario: Scenario,
    policy: Literal["rules", "llm"] = "rules",
    *,
    settings: Settings | None = None,
    llm_dir: Path = LLM_DIR,
    policy_override: Policy | None = None,
    script_override: list[str] | None = None,
    llm: LLMPort | None = None,
) -> ScenarioResult:
    """Corre un escenario con la politica dada y compara con lo esperado."""
    cfg = _settings(policy, settings)
    if policy == "llm" and llm is None:
        if script_override is not None:
            script = script_override
        else:
            name = scenario.llm.script
            if name is None:
                raise ValueError(f"{scenario.id}: sin script de LLM")
            script = json.loads((llm_dir / name).read_text(encoding="utf-8"))
        llm = ScriptedLLM(script, fail_after=scenario.llm.fail_after)
    rt = build_runtime(cfg, llm=llm, policy=policy_override)
    rt.create_case(dict(scenario.case))
    session = rt.verify(
        scenario.case["case_id"], str(scenario.case["phone_last4"])
    )
    logs: list[TurnLog] = []
    problems: list[str] = []
    for i, event in enumerate(scenario.turns, start=1):
        result = rt.runner.turn(session, event)
        logs.append(TurnLog(event.text, result.messages, result.stage))
        for cp in scenario.expected.checkpoints:
            if cp.after_turn == i and result.stage != cp.stage:
                problems.append(
                    f"tras el turno {i} se esperaba {cp.stage} "
                    f"y fue {result.stage}"
                )
    case = rt.deps.repo.get(scenario.case["case_id"])
    assert case is not None
    exp = scenario.expected
    if case.stage.value != exp.stage:
        problems.append(
            f"etapa final {case.stage.value}, esperada {exp.stage}"
        )
    events = rt.deps.audit.list_events(case.case_id)
    seen = {c for e in events for c in e.reason_codes}
    for code in exp.reason_codes:
        if code not in seen:
            problems.append(f"no aparecio el motivo {code}")
    for key, want in exp.data.items():
        if str(case.data.get(key)) != want:
            problems.append(
                f"data[{key}]={case.data.get(key)!r}, esperado {want!r}"
            )
    result_obj = ScenarioResult(
        scenario, policy, case.stage.value, logs, events, rt, problems
    )
    if policy == "llm" and exp.degraded and not result_obj.degraded:
        problems.append("se esperaba degradacion a reglas y no ocurrio")
    return result_obj


def record_script(scenario: Scenario) -> list[str]:
    """Corre el escenario con reglas y devuelve lo que diria un LLM ideal."""
    from agent.policy_rules import RuleBasedPolicy

    rec = RecordingPolicy(RuleBasedPolicy())
    run_scenario(scenario, "rules", policy_override=rec)
    return rec.script
