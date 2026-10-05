import pytest

from domain.readiness import (
    ReadinessInputs,
    ReadinessStatus,
    evaluate_readiness,
)


def good(**over: object) -> ReadinessInputs:
    base: dict[str, object] = dict(
        eligibility_ok=True,
        profile_approved=True,
        chosen_simulation_hash="abc",
        current_simulation_hash="abc",
        required_docs_present=True,
        docs_valid_and_vigent=True,
        income_identity_match=True,
        ownership_coherent=True,
        payment_capacity_ok=True,
        open_corrections=0,
    )
    base.update(over)
    return ReadinessInputs(**base)  # type: ignore[arg-type]


def test_todo_en_orden_es_ok() -> None:
    d = evaluate_readiness(good())
    assert d.status is ReadinessStatus.OK
    assert d.blocking == ()


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("eligibility_ok", False, "eligibility"),
        ("profile_approved", False, "profile"),
        ("chosen_simulation_hash", None, "simulation_current"),
        ("current_simulation_hash", "otro", "simulation_current"),
        ("required_docs_present", False, "documents_present"),
        ("docs_valid_and_vigent", False, "documents_valid"),
        ("income_identity_match", False, "income_identity"),
        ("ownership_coherent", False, "ownership"),
        ("payment_capacity_ok", False, "payment_capacity"),
        ("open_corrections", 1, "no_open_corrections"),
    ],
)
def test_cualquier_falla_bloquea(
    field: str, value: object, blocker: str
) -> None:
    d = evaluate_readiness(good(**{field: value}))
    assert d.status is ReadinessStatus.NOT_READY
    assert blocker in d.blocking


def test_hash_ausente_en_ambos_lados_no_cuenta_como_vigente() -> None:
    d = evaluate_readiness(
        good(chosen_simulation_hash=None, current_simulation_hash=None)
    )
    assert d.status is ReadinessStatus.NOT_READY


def test_inputs_hash_estable_y_trae_version() -> None:
    a, b = evaluate_readiness(good()), evaluate_readiness(good())
    assert a.inputs_hash == b.inputs_hash
    assert (
        a.inputs_hash
        != evaluate_readiness(good(open_corrections=1)).inputs_hash
    )
    assert a.rule_version
