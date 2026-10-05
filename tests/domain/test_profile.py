from pathlib import Path

import pytest

from domain.profile import (
    BureauProfile,
    ProfileStatus,
    evaluate_profile,
    load_profile_policy,
)

POLICY = load_profile_policy(Path("config/profile_policy.yaml"))


def run(score: int | None, **kw: bool) -> object:
    return evaluate_profile(POLICY, BureauProfile(score=score, **kw))


@pytest.mark.parametrize(
    ("score", "band"),
    [(850, "A"), (700, "A"), (699, "B"), (640, "B"), (639, "C"), (580, "C")],
)
def test_bandas_en_los_limites(score: int, band: str) -> None:
    d = evaluate_profile(POLICY, BureauProfile(score=score))
    assert d.status is ProfileStatus.APPROVED
    assert d.band == band


def test_579_no_aprobado() -> None:
    d = evaluate_profile(POLICY, BureauProfile(score=579))
    assert d.status is ProfileStatus.DECLINED
    assert d.max_ltv is None and d.annual_rate is None


def test_condiciones_banda_b() -> None:
    d = evaluate_profile(POLICY, BureauProfile(score=650))
    assert str(d.max_ltv) == "0.50"
    assert str(d.annual_rate) == "0.30"


def test_morosidad_activa_rechaza_aun_con_score_alto() -> None:
    d = evaluate_profile(
        POLICY, BureauProfile(score=800, active_delinquency=True)
    )
    assert d.status is ProfileStatus.DECLINED
    assert "ACTIVE_DELINQUENCY" in d.reason_codes


@pytest.mark.parametrize("score", [None, 399, 851])
def test_score_ausente_o_fuera_de_rango_escala(score: int | None) -> None:
    d = evaluate_profile(POLICY, BureauProfile(score=score))
    assert d.status is ProfileStatus.ESCALATE


def test_expediente_delgado_escala_aunque_haya_score() -> None:
    d = evaluate_profile(POLICY, BureauProfile(score=720, thin_file=True))
    assert d.status is ProfileStatus.ESCALATE
    assert "THIN_FILE" in d.reason_codes


def test_decision_lleva_version_de_regla() -> None:
    d = evaluate_profile(POLICY, BureauProfile(score=700))
    assert d.rule_version == POLICY.version
