"""Los clientes HTTP reales contra el motor de mocks, sin red."""

from decimal import Decimal

import pytest

from adapters.providers import Providers, build_providers
from ports import DocumentRef, NotFoundError, ProviderError


@pytest.fixture(scope="module")
def prov() -> Providers:
    return build_providers()


def test_buro_normaliza_el_reporte(prov: Providers) -> None:
    p = prov.bureau.query("cust-s01")
    assert p.score == 650
    assert not p.active_delinquency and not p.thin_file


def test_buro_morosidad_y_expediente_delgado(prov: Providers) -> None:
    assert prov.bureau.query("cust-delinquent").active_delinquency
    assert prov.bureau.query("cust-thin").thin_file
    assert prov.bureau.query("cust-noscore").score is None


def test_buro_cliente_desconocido(prov: Providers) -> None:
    with pytest.raises(NotFoundError):
        prov.bureau.query("nadie")


def test_buro_caido_es_error_reintentable(prov: Providers) -> None:
    with pytest.raises(ProviderError) as exc:
        prov.bureau.query("cust-fail")
    assert exc.value.retryable is True


def test_llave_default_y_override_por_vehiculo(prov: Providers) -> None:
    assert prov.key_quote.quote("veh-s01") == Decimal("3500.00")
    assert prov.key_quote.quote("veh-s04") == Decimal("4200.00")
    assert prov.key_quote.quote("veh-s04") == prov.key_quote.quote("veh-s04")


def test_registro_de_vehiculos(prov: Providers) -> None:
    ok = prov.vehicles.get_vehicle("veh-s01", "cust-s01")
    assert ok.facts.owner_matches is True and ok.appraised_value > 0
    assert (
        prov.vehicles.get_vehicle("veh-s02", "c").facts.owner_matches is False
    )
    assert prov.vehicles.get_vehicle("veh-s03", "c").facts.has_liens is True
    assert (
        prov.vehicles.get_vehicle("veh-s04", "c").facts.has_second_key is None
    )
    assert (
        prov.vehicles.get_vehicle("veh-nokey", "c").facts.has_second_key
        is False
    )
    with pytest.raises(NotFoundError):
        prov.vehicles.get_vehicle("nope", "c")


def test_lector_trae_confianza_por_campo_y_hash_estable(
    prov: Providers,
) -> None:
    ref = DocumentRef(doc_id="doc-good-payslip", doc_type="payslip")
    ex = prov.reader.read(ref)
    assert ex.fields["gross_income"].confidence > 0
    assert ex.content_hash == prov.reader.read(ref).content_hash


def test_hash_distinto_por_documento(prov: Providers) -> None:
    a = prov.reader.read(DocumentRef(doc_id="doc-good-payslip", doc_type="x"))
    b = prov.reader.read(DocumentRef(doc_id="doc-good-address", doc_type="x"))
    assert a.content_hash != b.content_hash


def test_documento_inexistente(prov: Providers) -> None:
    with pytest.raises(NotFoundError):
        prov.reader.read(DocumentRef(doc_id="nope", doc_type="payslip"))


def test_canal(prov: Providers) -> None:
    assert prov.channel.send("case-1", "hola").startswith("msg-")
    with pytest.raises(ProviderError):
        prov.channel.send("case-channel-down", "hola")
