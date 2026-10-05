from datetime import UTC, datetime
from pathlib import Path

from adapters.audit_jsonl import JsonlAudit
from ports import AuditEvent, AuditPort


def ev(case_id: str, name: str, n: int = 0) -> AuditEvent:
    return AuditEvent(
        run_id="r1",
        case_id=case_id,
        principal="customer-agent",
        type="tool",
        name=name,
        rule_version="1.0.0",
        inputs_hash="ab" * 32,
        outcome="allow",
        reason_codes=("OK",),
        latency_ms=n,
        ts=datetime(2026, 10, 5, 12, 0, n, tzinfo=UTC),
    )


def test_linea_de_tiempo_en_orden_y_aislada_por_caso(
    audit: AuditPort,
) -> None:
    audit.record(ev("c1", "a", 1))
    audit.record(ev("c2", "x", 2))
    audit.record(ev("c1", "b", 3))
    assert [e.name for e in audit.list_events("c1")] == ["a", "b"]
    assert [e.name for e in audit.list_events("c2")] == ["x"]
    assert audit.list_events("nada") == []


def test_roundtrip_conserva_todo(audit: AuditPort) -> None:
    audit.record(ev("c1", "a", 5))
    assert audit.list_events("c1") == [ev("c1", "a", 5)]


def test_jsonl_persiste_entre_instancias(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "audit.jsonl"
    JsonlAudit(path).record(ev("c1", "a"))
    assert [e.name for e in JsonlAudit(path).list_events("c1")] == ["a"]


def test_jsonl_es_una_linea_por_evento_y_sin_datos_crudos(
    tmp_path: Path,
) -> None:
    path = tmp_path / "audit.jsonl"
    log = JsonlAudit(path)
    log.record(ev("c1", "a"))
    log.record(ev("c1", "b"))
    lines = path.read_text().splitlines()
    assert len(lines) == 2
    assert "inputs_hash" in lines[0] and "inputs" not in lines[0].replace(
        "inputs_hash", ""
    )
