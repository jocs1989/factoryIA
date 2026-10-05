"""`make eval`: 0 falsos OK sobre el set etiquetado, y el set tiene dientes."""

import pytest

from domain.readiness import ReadinessDecision, ReadinessStatus
from observability.evaluation import build_eval_set, evaluate

pytestmark = pytest.mark.eval


def test_el_set_etiquetado_pasa_sin_falsos_ok() -> None:
    report = evaluate()
    assert not report.false_ok, report.format()
    assert not report.false_reject, report.format()
    assert not report.bypasses, report.format()
    assert report.passed


def test_el_set_cubre_lo_que_dice_el_reto() -> None:
    ids = {c.id for c in build_eval_set()}
    for needed in (
        "05-ingreso-40-menor",
        "07-baja-confianza",
        "08-identidad-no-coincide",
        "09-inyeccion-en-documento",
        "10-documento-ajeno",
        "v-payslip-vencido",
        "v-curp-distinta",
        "v-neto-no-cuadra",
        "v-ingreso-10-5-por-ciento",
    ):
        assert needed in ids
    positives = [c for c in build_eval_set() if c.should_be_ready]
    assert len(positives) >= 5  # tambien se mide el falso rechazo


def test_la_evaluacion_detecta_un_gate_roto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si alguien rompiera el gate, esta evaluacion debe ponerse en rojo."""
    monkeypatch.setattr(
        "tools.catalog.evaluate_readiness",
        lambda inputs: ReadinessDecision(
            status=ReadinessStatus.OK,
            checks={},
            blocking=(),
            rule_version="roto",
            inputs_hash="x",
        ),
    )
    chosen = [
        c
        for c in build_eval_set()
        if c.id in {"v-falta-la-factura", "v-payslip-vencido"}
    ]
    report = evaluate(chosen)
    assert report.false_ok, "el gate roto paso desapercibido"
    assert not report.passed
