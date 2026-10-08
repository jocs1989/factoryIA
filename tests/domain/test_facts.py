"""El esquema de `Case.data`: lo mal puesto falla al instante."""

import pytest
from pydantic import ValidationError

from domain.case import Case, Stage, with_data
from domain.facts import CaseFacts


def case(**data: object) -> Case:
    return Case(case_id="c", stage=Stage.ELIGIBILITY, data=dict(data))


def test_un_caso_vacio_o_con_datos_validos_se_crea() -> None:
    assert case().data == {}
    assert case(customer_id="c1", declared_income="20000.00").data


def test_una_clave_mal_escrita_falla_al_crear() -> None:
    with pytest.raises(ValidationError, match="customer_idd"):
        case(customer_idd="x")


def test_una_clave_mal_escrita_falla_al_escribir_y_no_se_persiste() -> None:
    c = case()
    with pytest.raises(ValidationError, match="verifed_income"):
        with_data(c, {"verifed_income": "1"})
    assert c.data == {} and c.version == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"declared_income": 20000},  # int, no str
        {"chosen": {"term_months": "veinticuatro", "hash": "h"}},
        {"documents": {"payslip": {"doc_id": "d"}}},  # faltan campos
        {"bureau_consent": {"given": True}},  # falta `at`
        {"overrides": {"X": {"by": "a"}}},
    ],
)
def test_los_tipos_anidados_se_validan(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        case(**bad)


def test_el_score_del_buro_no_tiene_donde_guardarse() -> None:
    """Privacidad por diseno: el esquema no admite el score ni el reporte."""
    for forbidden in ("score", "bureau_report", "raw_text"):
        with pytest.raises(ValidationError):
            case(**{forbidden: "x"})
    assert "score" not in CaseFacts.model_fields


def test_los_datos_de_un_caso_real_cumplen_el_esquema() -> None:
    from tests.tools.conftest import Env

    env = Env()
    env.advance_to_documents()
    env.attach_all()
    env.call("run_document_validations")
    assert env.call("mark_ready_for_lender").ok
    CaseFacts.model_validate(env.case().data)  # no lanza
