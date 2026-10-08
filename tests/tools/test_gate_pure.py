"""El gate como funcion pura: coincide con lo que hace la tool."""

from domain.readiness import ReadinessStatus
from tests.tools.conftest import Env
from tools.handlers.gate import gate_decision


def test_la_funcion_pura_y_la_tool_coinciden() -> None:
    env = Env()
    env.advance_to_documents()
    env.attach_all()
    env.call("run_document_validations")
    before = gate_decision(env.case(), env.deps)
    assert before.status is ReadinessStatus.OK
    assert env.call("mark_ready_for_lender").ok
    # tras marcarlo, recalculado desde cero, sigue siendo OK
    assert gate_decision(env.case(), env.deps).status is ReadinessStatus.OK


def test_sin_documentos_dice_no_listo_y_explica_por_que() -> None:
    env = Env()
    env.advance_to_documents()
    d = gate_decision(env.case(), env.deps)
    assert d.status is ReadinessStatus.NOT_READY
    assert "documents_present" in d.blocking
