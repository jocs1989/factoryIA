"""Las preguntas del reto, respondidas desde la bitacora."""

from pathlib import Path

import pytest

from adapters.channel_memory import MemoryChannel
from agent.scenarios import load_scenarios, run_scenario
from mocks.validate import main as validate_main
from observability.events import by_case, load_events
from observability.metrics import compute_metrics, format_report
from ports import AuditEvent


def events_of(*prefixes: str) -> list[AuditEvent]:
    out: list[AuditEvent] = []
    for sc in load_scenarios():
        if sc.id[:2] in prefixes:
            out += run_scenario(sc, "rules").events
    return out


def test_responde_las_preguntas_del_reto() -> None:
    m = compute_metrics(events_of("02", "03", "04", "05", "07", "10"))
    # ¿Rechaza bien por auto?
    assert m.rejections_by_reason == {
        "VEHICLE_NOT_OWNED": 1,
        "VEHICLE_ENCUMBERED": 1,
    }
    # ¿Detecta mismatches? (un caso cuenta una vez por tipo)
    assert m.mismatches_by_type == {
        "ingreso": 1,
        "baja confianza": 1,
        "documento ajeno": 1,
    }
    # ¿Casos con llave cotizada?
    assert m.key_quoted_cases == ["s04"]
    # Salud: escaladas, listos, invariantes
    assert m.cases == 6
    assert m.escalated_cases == 2 and abs(m.escalation_rate - 2 / 6) < 1e-9
    assert m.ready_cases == 1
    assert m.invariant_violations == 0


def test_estadisticas_por_tool() -> None:
    m = compute_metrics(events_of("01"))
    st = m.tools["mark_ready_for_lender"]
    assert (st.calls, st.denied, st.errors) == (1, 0, 0)
    assert m.tools["attach_document"].calls == 4


def test_denegaciones_y_llm_se_cuentan() -> None:
    sc = next(s for s in load_scenarios() if s.id.startswith("09"))
    m = compute_metrics(run_scenario(sc, "llm").events)
    assert m.denials_by_code.get("documents_valid", 0) >= 1
    assert m.llm["ok"] > 0


def test_reporte_es_legible() -> None:
    text = format_report(compute_metrics(events_of("02", "05")))
    assert "REPORTE DE DECISIONES" in text
    assert "VEHICLE_NOT_OWNED: 1" in text
    assert "ingreso: 1" in text


def test_lectura_de_la_bitacora(tmp_path: Path) -> None:
    assert load_events(tmp_path / "no.jsonl") == []
    evs = events_of("02")
    path = tmp_path / "a.jsonl"
    path.write_text("\n".join(e.model_dump_json() for e in evs) + "\n\n")
    loaded = load_events(path)
    assert loaded == evs
    assert set(by_case(loaded)) == {"s02"}


def test_canal_en_memoria() -> None:
    ch = MemoryChannel()
    assert ch.send("c1", "hola") == "msg-mem-0001"
    assert ch.sent == [("c1", "hola")]


def test_validador_de_mocks_como_comando(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert validate_main(["x", "mocks/mappings"]) == 0
    (tmp_path / "mal.json").write_text('{"id": "x"}')
    assert validate_main(["x", str(tmp_path)]) == 1
    assert "ERROR" in capsys.readouterr().out
