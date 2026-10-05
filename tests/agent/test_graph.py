"""Grafo: lista blanca, topes, escalada con pausa y reanudacion."""

from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent.graph import ESCALATED_TEXT
from agent.runner import ConversationRunner
from agent.runtime import Runtime, build_runtime
from agent.scenarios import load_scenarios
from agent.types import (
    Action,
    CustomerEvent,
    DocRef,
    Policy,
    StageView,
    ToolCall,
)
from config.settings import load_settings
from domain.case import Case, Stage
from tools.session import Session

BASE: dict[str, Any] = {
    "case_id": "c1",
    "customer_id": "cust-s01",
    "vehicle_id": "veh-s01",
    "customer_name": "Juan Pérez López",
    "declared_income": "20000.00",
    "requested_amount": "80000",
    "employment_type": "salaried",
    "phone_last4": "1234",
    "address_street": "Calle Reforma 10",
    "address_postal_code": "06600",
}
GOOD = {
    "payslip": "doc-good-payslip",
    "proof_of_address": "doc-good-address",
    "id_card": "doc-good-id",
    "vehicle_title": "doc-good-title",
}


class Loop(Policy):
    """Politica terca: repite la misma accion para probar los topes."""

    name = "loop"

    def __init__(self, action: Action) -> None:
        self.action = action
        self.calls = 0

    def next_action(self, view: StageView) -> Action:
        self.calls += 1
        return self.action


def runtime(
    policy: Policy | None = None, **case: Any
) -> tuple[Runtime, Session]:
    rt = build_runtime(load_settings(), policy=policy)
    rt.create_case({**BASE, **case})
    return rt, rt.verify("c1", "1234")


def docs(**over: str) -> tuple[DocRef, ...]:
    return tuple(
        DocRef(doc_id=i, doc_type=t) for t, i in {**GOOD, **over}.items()
    )


def say(rt: Runtime, s: Session, text: str, **kw: Any):  # type: ignore[no-untyped-def]
    return rt.runner.turn(s, CustomerEvent(text=text, **kw))


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_ENV", "mock")


def test_una_tool_fuera_de_la_lista_blanca_se_niega_sin_ejecutarse() -> None:
    p = Loop(ToolCall(tool="mark_ready_for_lender"))
    rt, s = runtime(p)
    r = say(rt, s, "hola")
    events = rt.deps.audit.list_events("c1")
    assert all(e.reason_codes == ("TOOL_NOT_WHITELISTED",) for e in events[:3])
    assert p.calls == 3  # 3 violaciones y se corta
    assert rt.deps.repo.get("c1").stage is Stage.ELIGIBILITY  # type: ignore[union-attr]
    assert r.messages and "revisando" in r.messages[0]


def test_tope_de_pasos_en_perfilamiento_escala_al_asesor() -> None:
    p = Loop(ToolCall(tool="get_case_snapshot"))
    rt, s = runtime(p)
    # Se lleva el caso a PROFILING sin pasar por la politica.
    ok = rt.executor.call(
        rt.principals.get("customer-agent"),
        s,
        "check_vehicle_eligibility",
        {"case_id": "c1"},
    )
    assert ok.ok
    r = say(rt, s, "hola")
    case = rt.deps.repo.get("c1")
    assert case is not None and case.stage is Stage.ESCALATED
    assert r.awaiting_advisor and ESCALATED_TEXT in r.messages
    assert rt.deps.inbox.list_open()[0].reason_code == "AGENT_LIMIT"
    assert p.calls == 12  # el tope, ni uno mas


def _escalated_by_income() -> tuple[Runtime, Session]:
    rt, s = runtime(requested_amount="50000")
    say(rt, s, "Hola, quiero un credito")
    say(rt, s, "Sí, autorizo la consulta al Buró")
    say(rt, s, "Quiero el plazo de 24 meses")
    r = say(rt, s, "Adjunto", documents=docs(payslip="doc-s05-payslip"))
    assert r.stage == "ESCALATED" and r.awaiting_advisor
    return rt, s


def _advisor_resolves(rt: Runtime, s: Session) -> None:
    ticket = rt.deps.inbox.list_open()[0]
    res = rt.executor.call(
        rt.principals.get("advisor"),
        s,
        "resolve_escalation",
        {
            "case_id": "c1",
            "ticket_id": ticket.ticket_id,
            "decision": "resume",
            "justification": "Validado por telefono",
            "override_codes": ["INCOME_MISMATCH"],
        },
    )
    assert res.ok, res


def test_con_el_caso_escalado_el_agente_no_corre() -> None:
    rt, s = _escalated_by_income()
    before = len(rt.deps.audit.list_events("c1"))
    r = say(rt, s, "¿ya viste mi caso?")
    assert r.messages == [ESCALATED_TEXT] and r.steps == 0
    assert len(rt.deps.audit.list_events("c1")) == before  # no hizo nada


def test_el_asesor_resuelve_y_el_agente_reanuda_hasta_el_final() -> None:
    rt, s = _escalated_by_income()
    _advisor_resolves(rt, s)
    r = rt.runner.resume_after_advisor(s)  # reanuda desde el checkpoint
    assert r.stage == "READY_FOR_LENDER" and r.outcome == "READY_FOR_LENDER"
    assert "enviado a la financiera" in r.messages[-1]
    assert ESCALATED_TEXT not in r.messages  # eso ya se le dijo antes
    case = rt.deps.repo.get("c1")
    assert case is not None and case.data["overrides"]["INCOME_MISMATCH"]
    assert rt.deps.inbox.list_open() == []


def test_reanudar_sin_checkpoint_arranca_limpio() -> None:
    """Reinicio del proceso: el caso persistido es la verdad."""
    rt, s = _escalated_by_income()
    _advisor_resolves(rt, s)
    fresh = ConversationRunner(rt.runner._deps, InMemorySaver())
    r = fresh.resume_after_advisor(s)
    assert r.stage == "READY_FOR_LENDER"


def test_el_asesor_puede_cerrar_el_caso() -> None:
    rt, s = _escalated_by_income()
    t = rt.deps.inbox.list_open()[0]
    rt.executor.call(
        rt.principals.get("advisor"),
        s,
        "resolve_escalation",
        {
            "case_id": "c1",
            "ticket_id": t.ticket_id,
            "decision": "reject",
            "justification": "Comprobante no confiable",
        },
    )
    r = rt.runner.resume_after_advisor(s)
    assert r.stage == "REJECTED" and r.outcome == "REJECTED"


def test_terminal_responde_siempre_lo_mismo() -> None:
    rt, s = runtime(vehicle_id="veh-s02")
    first = say(rt, s, "hola")
    again = say(rt, s, "¿y ahora?")
    assert first.stage == again.stage == "REJECTED"
    assert first.messages == again.messages
    assert "no esta a tu nombre" in first.messages[0]


def test_documentos_a_destiempo_no_se_adjuntan() -> None:
    rt, s = runtime()
    say(rt, s, "hola", documents=docs())
    case = rt.deps.repo.get("c1")
    assert case is not None and not case.data.get("documents")


def test_invariante_listo_sin_evidencia_del_gate_deja_rastro() -> None:
    rt, s = runtime()
    rt.deps.repo.add(
        Case(
            case_id="c9",
            stage=Stage.READY_FOR_LENDER,
            data=dict(BASE, case_id="c9"),
        )
    )
    rt.runner.turn(Session("c9"), CustomerEvent(text="hola"))
    ev = [e for e in rt.deps.audit.list_events("c9") if e.type == "invariant"]
    assert ev and ev[0].reason_codes == ("READY_WITHOUT_GATE_EVIDENCE",)


def test_los_escenarios_se_pueden_repetir_sin_estado_compartido() -> None:
    sc = next(x for x in load_scenarios() if x.id.startswith("01"))
    from agent.scenarios import run_scenario

    assert (
        run_scenario(sc, "rules").passed and run_scenario(sc, "rules").passed
    )
