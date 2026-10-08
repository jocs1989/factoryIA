import pytest

from domain.case import Case, Stage, StaleVersion, transition
from ports import CaseExists, CaseNotFound, CaseRepositoryPort


def new_case() -> Case:
    return Case(
        case_id="c1",
        stage=Stage.ELIGIBILITY,
        data={"customer_id": "cust-001", "declared_income": "20000.00"},
    )


def test_add_y_get(case_repo: CaseRepositoryPort) -> None:
    case_repo.add(new_case())
    assert case_repo.get("c1") == new_case()


def test_get_inexistente_es_none(case_repo: CaseRepositoryPort) -> None:
    assert case_repo.get("nope") is None


def test_add_duplicado(case_repo: CaseRepositoryPort) -> None:
    case_repo.add(new_case())
    with pytest.raises(CaseExists):
        case_repo.add(new_case())


def test_save_con_version_correcta(case_repo: CaseRepositoryPort) -> None:
    c = new_case()
    case_repo.add(c)
    n = transition(c, Stage.PROFILING)
    case_repo.save(n, expected_version=1)
    got = case_repo.get("c1")
    assert got is not None
    assert (got.stage, got.version) == (Stage.PROFILING, 2)


def test_save_con_version_vieja_falla_y_no_pisa(
    case_repo: CaseRepositoryPort,
) -> None:
    c = new_case()
    case_repo.add(c)
    p = transition(c, Stage.PROFILING)
    case_repo.save(p, expected_version=1)
    # Otro actor, con el estado viejo, intenta escribir.
    r = transition(c, Stage.REJECTED)
    with pytest.raises(StaleVersion):
        case_repo.save(r, expected_version=1)
    got = case_repo.get("c1")
    assert got is not None and got.stage is Stage.PROFILING


def test_save_de_caso_inexistente(case_repo: CaseRepositoryPort) -> None:
    with pytest.raises(CaseNotFound):
        case_repo.save(new_case(), expected_version=1)


def test_conserva_escalated_from(case_repo: CaseRepositoryPort) -> None:
    c = Case(case_id="c2", stage=Stage.DOCUMENTS)
    case_repo.add(c)
    e = transition(c, Stage.ESCALATED)
    case_repo.save(e, expected_version=1)
    got = case_repo.get("c2")
    assert got is not None and got.escalated_from is Stage.DOCUMENTS


def test_el_objeto_guardado_no_se_comparte(
    case_repo: CaseRepositoryPort,
) -> None:
    c = new_case()
    case_repo.add(c)
    c.data["declared_income"] = (
        "999"  # mutar el original no debe afectar lo guardado
    )
    got = case_repo.get("c1")
    assert got is not None and got.data["declared_income"] == "20000.00"
