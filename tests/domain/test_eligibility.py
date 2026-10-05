import pytest

from domain.eligibility import (
    EligibilityStatus,
    VehicleFacts,
    evaluate_eligibility,
)


def ev(owner: bool | None, liens: bool | None, key: bool | None):  # type: ignore[no-untyped-def]
    return evaluate_eligibility(
        VehicleFacts(owner_matches=owner, has_liens=liens, has_second_key=key)
    )


def test_camino_feliz_con_llave() -> None:
    d = ev(True, False, True)
    assert d.status is EligibilityStatus.ELIGIBLE
    assert d.needs_second_key_quote is False


def test_sin_llave_continua_y_pide_cotizar() -> None:
    d = ev(True, False, False)
    assert d.status is EligibilityStatus.ELIGIBLE
    assert d.needs_second_key_quote is True


def test_auto_de_tercero() -> None:
    d = ev(False, False, True)
    assert d.status is EligibilityStatus.REJECTED
    assert d.reason_codes == ("VEHICLE_NOT_OWNED",)


def test_gravamen() -> None:
    d = ev(True, True, True)
    assert d.status is EligibilityStatus.REJECTED
    assert d.reason_codes == ("VEHICLE_ENCUMBERED",)


def test_ambos_bloqueos_se_reportan() -> None:
    d = ev(False, True, True)
    assert set(d.reason_codes) == {"VEHICLE_NOT_OWNED", "VEHICLE_ENCUMBERED"}


@pytest.mark.parametrize(
    ("owner", "liens", "key", "missing"),
    [
        (None, False, True, ("owner_matches",)),
        (True, None, True, ("has_liens",)),
        (True, False, None, ("has_second_key",)),
        (None, None, None, ("owner_matches", "has_liens", "has_second_key")),
    ],
)
def test_dato_faltante_se_pregunta_nunca_se_asume(
    owner: bool | None,
    liens: bool | None,
    key: bool | None,
    missing: tuple[str, ...],
) -> None:
    d = ev(owner, liens, key)
    assert d.status is EligibilityStatus.NEEDS_INFO
    assert d.missing == missing


def test_rechazo_firme_aunque_falten_otros_datos() -> None:
    d = ev(False, None, None)
    assert d.status is EligibilityStatus.REJECTED
