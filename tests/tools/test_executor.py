"""Pipeline del ejecutor: cada defensa demostrada."""

from typing import Any

import pytest
from pydantic import BaseModel

from domain.case import Stage, with_data
from tests.tools.conftest import Env
from tools.executor import Executor, ToolStatus
from tools.session import Session
from tools.spec import Effect, Outcome, Risk, ToolInput, ToolSpec


def last_event(env: Env):  # type: ignore[no-untyped-def]
    return env.audit.list_events("c1")[-1]


def test_tool_desconocida_se_deniega(env: Env) -> None:
    env.new_case()
    r = env.call("borrar_todo")
    assert (r.status, r.code) == (ToolStatus.DENIED, "UNKNOWN_TOOL")


@pytest.mark.parametrize(
    "args",
    [
        {},  # falta case_id
        {"case_id": "c1", "extra": 1},  # campo no declarado
        {"case_id": "c1", "declared_second_key": "quizas"},
    ],
)
def test_entrada_invalida(env: Env, args: dict[str, Any]) -> None:
    env.new_case()
    r = env.executor.call(
        env.agent, Session("c1"), "check_vehicle_eligibility", args
    )
    assert (r.status, r.code) == (ToolStatus.INVALID, "INVALID_INPUT")


def test_sin_el_permiso_se_deniega(env: Env) -> None:
    env.new_case()
    r = env.as_advisor(
        "check_vehicle_eligibility"
    )  # el asesor no tiene vehicle:read
    assert (r.status, r.code) == (ToolStatus.DENIED, "SCOPE_DENIED")
    assert env.case().stage.value == "ELIGIBILITY"


def test_caso_ajeno_a_la_sesion_se_rechaza(env: Env) -> None:
    env.new_case("c1")
    env.new_case("c2")
    r = env.executor.call(
        env.agent,
        Session("c1"),
        "check_vehicle_eligibility",
        {"case_id": "c2"},
    )
    assert (r.status, r.code) == (ToolStatus.DENIED, "CASE_MISMATCH")
    assert env.case("c2").stage.value == "ELIGIBILITY"  # no se toco


def test_caso_inexistente(env: Env) -> None:
    r = env.call("get_case_snapshot", Session("nada"))
    assert r.code == "CASE_NOT_FOUND"


def test_tool_fuera_de_la_etapa_se_rechaza(env: Env) -> None:
    env.new_case()
    r = env.call("build_simulation", requested_amount="1000")
    assert (r.status, r.code) == (ToolStatus.DENIED, "STAGE_NOT_ALLOWED")


def test_version_esperada_vieja(env: Env) -> None:
    env.new_case()
    r = env.call("check_vehicle_eligibility", expected_version=99)
    assert r.code == "STALE_VERSION"


def test_escritura_concurrente_no_pisa_al_otro(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.new_case()
    real_get = env.repo.get

    def get_then_other_actor_writes(case_id: str):  # type: ignore[no-untyped-def]
        c = real_get(case_id)
        assert c is not None
        # Otro actor (p. ej. el asesor) guarda entre la lectura y el guardado.
        env.repo.save(
            with_data(c, {**c.data, "ticket_id": "T-del-asesor"}),
            expected_version=c.version,
        )
        return c

    monkeypatch.setattr(env.repo, "get", get_then_other_actor_writes)
    r = env.call("check_vehicle_eligibility")
    monkeypatch.undo()
    assert (r.status, r.code) == (ToolStatus.DENIED, "STALE_VERSION")
    assert (
        env.case().data["ticket_id"] == "T-del-asesor"
    )  # su escritura sobrevive
    assert env.case().stage.value == "ELIGIBILITY"  # la nuestra no se aplico


def test_reintento_idempotente_no_repite_la_consulta_al_buro(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = env.new_case()
    assert env.call("check_vehicle_eligibility").ok
    assert env.call("record_bureau_consent", consent=True).ok
    calls = 0
    real = env.providers.bureau.query

    def counting(customer_id: str):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return real(customer_id)

    monkeypatch.setattr(env.providers.bureau, "query", counting)
    first = env.call("query_credit_bureau", s)
    again = env.call(
        "query_credit_bureau", s
    )  # reintento tras respuesta perdida
    assert first.ok and again.ok and again.replayed
    assert again.output == first.output
    assert calls == 1


def test_reintento_no_salta_el_control_de_permisos(env: Env) -> None:
    s = env.new_case()
    env.call("check_vehicle_eligibility")
    env.call("record_bureau_consent", consent=True)
    assert env.call("query_credit_bureau", s).ok
    r = env.as_advisor("query_credit_bureau", s)  # mismo args, sin permiso
    assert r.code == "SCOPE_DENIED" and not r.replayed


def test_si_el_caso_ya_avanzo_mas_se_ejecuta_de_nuevo(env: Env) -> None:
    env.new_case(vehicle_id="veh-s04")
    env.call("check_vehicle_eligibility", declared_second_key=False)
    first = env.call("quote_second_key")
    assert first.ok
    # el caso avanza (otra escritura) y la misma peticion ya no es replay
    env.call("record_bureau_consent", consent=True)
    again = env.call("quote_second_key")
    assert again.ok and not again.replayed


def test_proveedor_caido_es_error_y_no_cambia_el_caso(env: Env) -> None:
    env.new_case(customer_id="cust-fail")
    env.call("check_vehicle_eligibility")
    env.call("record_bureau_consent", consent=True)
    before = env.case()
    r = env.call("query_credit_bureau")
    assert (r.status, r.code) == (ToolStatus.ERROR, "PROVIDER_UNAVAILABLE")
    assert env.case() == before


def test_salida_fuera_de_contrato_es_error(env: Env) -> None:
    class In(ToolInput):
        pass

    class Out(BaseModel):
        must: int

    class Wrong(BaseModel):
        other: str = "x"

    spec = ToolSpec(
        "rota",
        "x",
        In,
        Out,
        Effect.READ,
        Risk.LOW,
        "case:read",
        frozenset(Stage),
        lambda ctx, inp: Outcome(Wrong()),
    )
    env.new_case()
    r = Executor(env.deps, {"rota": spec}).call(
        env.agent, Session("c1"), "rota", {"case_id": "c1"}
    )
    assert (r.status, r.code) == (ToolStatus.ERROR, "INVALID_OUTPUT")


def test_bitacora_registra_todo_con_hash_y_sin_datos_crudos(env: Env) -> None:
    env.new_case()
    env.call("record_bureau_consent", consent=True)  # fuera de etapa
    env.call("check_vehicle_eligibility", declared_second_key=True)
    events = env.audit.list_events("c1")
    assert [e.outcome for e in events] == ["denied", "ok"]
    assert events[0].reason_codes == ("STAGE_NOT_ALLOWED",)
    assert all(e.inputs_hash and len(e.inputs_hash) == 64 for e in events)
    assert all(e.principal == "customer-agent" for e in events)
    dump = " ".join(e.model_dump_json() for e in events)
    assert "cust-s01" not in dump and "Juan" not in dump
