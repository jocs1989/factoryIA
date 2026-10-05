import pytest

from domain.case import (
    Case,
    InvalidTransition,
    Stage,
    StaleVersion,
    can_transition,
    transition,
)


def case(stage: Stage = Stage.ELIGIBILITY, **kw: object) -> Case:
    return Case(case_id="c1", stage=stage, **kw)  # type: ignore[arg-type]


def test_inicia_en_version_1() -> None:
    assert case().version == 1


def test_transicion_sube_version_y_no_muta_el_original() -> None:
    c = case()
    n = transition(c, Stage.PROFILING)
    assert (n.stage, n.version) == (Stage.PROFILING, 2)
    assert (c.stage, c.version) == (Stage.ELIGIBILITY, 1)


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (Stage.ELIGIBILITY, Stage.REJECTED),
        (Stage.ELIGIBILITY, Stage.PROFILING),
        (Stage.PROFILING, Stage.DECLINED),
        (Stage.PROFILING, Stage.ESCALATED),
        (Stage.PROFILING, Stage.SIMULATION),
        (Stage.SIMULATION, Stage.DOCUMENTS),
        (Stage.DOCUMENTS, Stage.NEEDS_CORRECTION),
        (Stage.NEEDS_CORRECTION, Stage.DOCUMENTS),
        (Stage.DOCUMENTS, Stage.SIMULATION),  # invalidacion por ingreso
        (Stage.DOCUMENTS, Stage.ESCALATED),
        (Stage.DOCUMENTS, Stage.READY_FOR_LENDER),
    ],
)
def test_transiciones_permitidas(src: Stage, dst: Stage) -> None:
    assert can_transition(case(src), dst)


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (Stage.ELIGIBILITY, Stage.READY_FOR_LENDER),
        (Stage.ELIGIBILITY, Stage.SIMULATION),
        (Stage.PROFILING, Stage.READY_FOR_LENDER),
        (Stage.SIMULATION, Stage.READY_FOR_LENDER),
        (Stage.NEEDS_CORRECTION, Stage.READY_FOR_LENDER),
        (Stage.ESCALATED, Stage.READY_FOR_LENDER),
    ],
)
def test_no_se_puede_saltar_a_listo(src: Stage, dst: Stage) -> None:
    c = case(src, escalated_from=Stage.DOCUMENTS)
    assert not can_transition(c, dst)
    with pytest.raises(InvalidTransition):
        transition(c, dst)


@pytest.mark.parametrize(
    "terminal", [Stage.REJECTED, Stage.DECLINED, Stage.READY_FOR_LENDER]
)
def test_terminales_no_salen(terminal: Stage) -> None:
    for dst in Stage:
        assert not can_transition(case(terminal), dst)


def test_escalada_recuerda_de_donde_vino_y_reanuda_ahi() -> None:
    e = transition(case(Stage.DOCUMENTS), Stage.ESCALATED)
    assert e.escalated_from is Stage.DOCUMENTS
    assert can_transition(e, Stage.DOCUMENTS)
    assert not can_transition(e, Stage.PROFILING)
    assert can_transition(e, Stage.REJECTED)  # el asesor puede rechazar
    back = transition(e, Stage.DOCUMENTS)
    assert back.escalated_from is None


def test_version_vieja_falla() -> None:
    c = transition(case(), Stage.PROFILING)  # v2
    with pytest.raises(StaleVersion):
        transition(c, Stage.SIMULATION, expected_version=1)
    assert transition(c, Stage.SIMULATION, expected_version=2).version == 3
