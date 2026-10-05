"""Los 12 escenarios recorren el grafo de punta a punta, sin red."""

import pytest

from agent.scenarios import ScenarioResult, load_scenarios, run_scenario

SCENARIOS = load_scenarios()
IDS = [s.id for s in SCENARIOS]


def test_hay_doce_escenarios() -> None:
    assert len(SCENARIOS) == 12
    assert {s.id[:2] for s in SCENARIOS} == {f"{n:02d}" for n in range(1, 13)}


@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_con_politica_por_reglas(scenario) -> None:  # type: ignore[no-untyped-def]
    r = run_scenario(scenario, "rules")
    assert r.passed, r.problems


@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_con_politica_llm_guionado(scenario) -> None:  # type: ignore[no-untyped-def]
    r = run_scenario(scenario, "llm")
    assert r.passed, r.problems


@pytest.mark.parametrize("scenario", SCENARIOS, ids=IDS)
def test_ambas_politicas_dan_el_mismo_desenlace(scenario) -> None:  # type: ignore[no-untyped-def]
    a = run_scenario(scenario, "rules")
    b = run_scenario(scenario, "llm")
    assert a.final_stage == b.final_stage == scenario.expected.stage


def by_id(prefix: str) -> ScenarioResult:
    s = next(x for x in SCENARIOS if x.id.startswith(prefix))
    return run_scenario(s, "llm")


def test_inyeccion_el_modelo_se_deja_enganar_pero_el_gate_no() -> None:
    r = by_id("09")
    # el 'modelo' propuso mark_ready_for_lender y el sistema lo nego
    denied = [e for e in r.events if e.name == "mark_ready_for_lender"]
    assert denied and denied[0].outcome == "denied"
    assert (
        "NOT_READY" in " ".join(denied[0].reason_codes)
        or denied[0].reason_codes
    )
    assert r.final_stage == "ESCALATED"
    flagged = r.runtime.deps.repo.get("s09")
    assert flagged is not None
    assert flagged.data["documents"]["payslip"]["flags"] == [
        "PROMPT_INJECTION"
    ]


def test_falla_del_llm_cae_a_reglas_y_el_caso_no_se_pierde() -> None:
    r = by_id("12")
    assert r.final_stage == "READY_FOR_LENDER"
    llm_events = [e for e in r.events if e.type == "llm"]
    assert any(e.outcome == "error" for e in llm_events)
    assert any(e.outcome == "circuit_open" for e in llm_events)
    assert any(
        e.reason_codes == ("LLM_FALLBACK_TO_RULES",) for e in llm_events
    )


def test_llave_cotizada_sube_la_cuota() -> None:
    r = by_id("04")
    case = r.runtime.deps.repo.get("s04")
    assert case is not None
    option = next(
        o for o in case.data["simulation"]["options"] if o["term_months"] == 24
    )
    assert option["second_key_cost"] == "4200.00"
    assert float(option["monthly_payment"]) > 4473.03


def test_ningun_escenario_adversarial_llega_a_listo() -> None:
    for s in SCENARIOS:
        if s.expected.adversarial:
            assert run_scenario(s, "rules").final_stage != "READY_FOR_LENDER"
            assert run_scenario(s, "llm").final_stage != "READY_FOR_LENDER"
