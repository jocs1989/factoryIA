"""Comportamiento de cada tool y el gate, incluso invocado directo."""

import dataclasses
from decimal import Decimal

import pytest

from domain.case import Case, Stage, with_data
from ports import ProviderError
from tests.tools.conftest import BASE_DATA, GOOD_DOCS, Env
from tools.catalog import build_catalog
from tools.executor import Executor, ToolStatus
from tools.session import Session

# --- elegibilidad -----------------------------------------------------------


def test_elegible_pasa_a_perfilamiento(env: Env) -> None:
    env.new_case()
    r = env.call("check_vehicle_eligibility")
    assert r.ok and r.output["status"] == "ELIGIBLE"
    assert env.case().stage is Stage.PROFILING


@pytest.mark.parametrize(
    ("vehicle", "reason"),
    [("veh-s02", "VEHICLE_NOT_OWNED"), ("veh-s03", "VEHICLE_ENCUMBERED")],
)
def test_rechazo_duro(env: Env, vehicle: str, reason: str) -> None:
    env.new_case(vehicle_id=vehicle)
    r = env.call("check_vehicle_eligibility")
    assert r.ok and r.output["reason_codes"] == [reason]
    assert env.case().stage is Stage.REJECTED


def test_dato_faltante_se_pregunta_y_el_cliente_lo_declara(env: Env) -> None:
    env.new_case(vehicle_id="veh-s04")
    r = env.call("check_vehicle_eligibility")
    assert r.output["status"] == "NEEDS_INFO"
    assert r.output["missing"] == ["has_second_key"]
    assert env.case().stage is Stage.ELIGIBILITY
    r = env.call("check_vehicle_eligibility", declared_second_key=False)
    assert r.output["status"] == "ELIGIBLE"
    assert r.output["needs_second_key_quote"] is True


def test_el_registro_manda_sobre_lo_que_dice_el_cliente(env: Env) -> None:
    env.new_case(vehicle_id="veh-nokey")  # el registro dice: sin llave
    r = env.call("check_vehicle_eligibility", declared_second_key=True)
    assert r.output["needs_second_key_quote"] is True


# --- llave, consentimiento y buro ----------------------------------------


def test_cotizacion_solo_si_hace_falta(env: Env) -> None:
    env.new_case()
    env.call("check_vehicle_eligibility")  # veh-s01 tiene llave
    r = env.call("quote_second_key")
    assert r.code == "KEY_QUOTE_NOT_NEEDED"


def test_cotizacion_se_guarda_en_el_caso(env: Env) -> None:
    env.new_case(vehicle_id="veh-s04")
    env.call("check_vehicle_eligibility", declared_second_key=False)
    r = env.call("quote_second_key")
    assert r.ok and r.output["second_key_cost"] == "4200.00"
    assert env.case().data["second_key_cost"] == "4200.00"


def test_sin_consentimiento_no_se_consulta_el_buro(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.new_case()
    env.call("check_vehicle_eligibility")
    monkeypatch.setattr(
        env.providers.bureau,
        "query",
        lambda cid: pytest.fail("no debio consultarse"),
    )
    r = env.call("query_credit_bureau")
    assert (r.status, r.code) == (ToolStatus.DENIED, "CONSENT_REQUIRED")


def test_consentimiento_negado_no_se_registra(env: Env) -> None:
    env.new_case()
    env.call("check_vehicle_eligibility")
    r = env.call("record_bureau_consent", consent=False)
    assert r.code == "CONSENT_NOT_GIVEN"
    assert "bureau_consent" not in env.case().data


def test_perfil_aprobado_y_sin_score_en_ningun_lado(env: Env) -> None:
    env.advance_to_simulation()
    c = env.case()
    assert c.stage is Stage.SIMULATION
    assert c.data["profile"]["band"] == "B"
    assert "score" not in str(c.data).lower().replace("score_", "")
    snap = env.call("get_case_snapshot")
    assert "650" not in str(snap.output)


@pytest.mark.parametrize(
    ("customer", "stage", "reason"),
    [
        ("cust-decline", Stage.DECLINED, "SCORE_BELOW_MINIMUM"),
        ("cust-delinquent", Stage.DECLINED, "ACTIVE_DELINQUENCY"),
        ("cust-thin", Stage.ESCALATED, "THIN_FILE"),
        ("cust-noscore", Stage.ESCALATED, "SCORE_MISSING"),
    ],
)
def test_perfil_no_aprobado(
    env: Env, customer: str, stage: Stage, reason: str
) -> None:
    env.new_case(customer_id=customer)
    env.call("check_vehicle_eligibility")
    env.call("record_bureau_consent", consent=True)
    r = env.call("query_credit_bureau")
    assert r.ok and reason in r.output["reason_codes"]
    assert env.case().stage is stage
    if stage is Stage.ESCALATED:
        assert len(env.inbox.list_open()) == 1


# --- simulacion --------------------------------------------------------------


def test_simulacion_marca_que_opciones_caben(env: Env) -> None:
    env.advance_to_simulation()
    r = env.call("build_simulation", requested_amount="80000")
    assert r.ok
    by_term = {o["term_months"]: o for o in r.output["options"]}
    assert by_term[24]["monthly_payment"] == "4473.03"
    assert by_term[24]["affordable"] is True
    assert by_term[12]["affordable"] is False  # 7799 > 35 % de 20000


def test_monto_sobre_el_ltv_se_niega(env: Env) -> None:
    env.advance_to_simulation()
    r = env.call("build_simulation", requested_amount="200000")
    assert r.code == "AMOUNT_NOT_ALLOWED"


def test_montos_no_aceptan_flotantes(env: Env) -> None:
    env.advance_to_simulation()
    r = env.call("build_simulation", requested_amount=80000.5)
    assert r.status is ToolStatus.INVALID


def test_la_llave_entra_al_plan_como_renglon(env: Env) -> None:
    env.new_case(vehicle_id="veh-s04")
    env.call("check_vehicle_eligibility", declared_second_key=False)
    r0 = env.call("build_simulation", requested_amount="80000")  # etapa mala
    assert r0.code == "STAGE_NOT_ALLOWED"
    env.call("record_bureau_consent", consent=True)
    env.call("query_credit_bureau")
    assert env.call("build_simulation", requested_amount="80000").code == (
        "KEY_QUOTE_REQUIRED"
    )
    env.call("quote_second_key")
    r = env.call("build_simulation", requested_amount="80000")
    o = {x["term_months"]: x for x in r.output["options"]}[24]
    assert o["second_key_cost"] == "4200.00" and o["principal"] == "84200.00"
    assert Decimal(o["monthly_payment"]) > Decimal("4473.03")


def test_eleccion_valida_y_hash(env: Env) -> None:
    env.advance_to_simulation()
    env.call("build_simulation", requested_amount="80000")
    r = env.call("record_customer_choice", term_months=24)
    assert r.ok and len(r.output["simulation_hash"]) == 64
    assert env.case().stage is Stage.DOCUMENTS


@pytest.mark.parametrize(
    ("term", "code"), [(12, "OPTION_NOT_AFFORDABLE"), (18, "OPTION_NOT_FOUND")]
)
def test_eleccion_invalida(env: Env, term: int, code: str) -> None:
    env.advance_to_simulation()
    env.call("build_simulation", requested_amount="80000")
    assert env.call("record_customer_choice", term_months=term).code == code
    assert env.case().stage is Stage.SIMULATION


def test_sin_simulacion_no_hay_eleccion(env: Env) -> None:
    env.advance_to_simulation()
    assert (
        env.call("record_customer_choice", term_months=24).code
        == "NO_SIMULATION"
    )


# --- update_case -----------------------------------------------------


def test_update_con_lista_blanca_por_etapa(env: Env) -> None:
    env.advance_to_simulation()
    assert env.call(
        "update_case", fields={"declared_income": "99999"}
    ).code == ("FIELD_NOT_ALLOWED")
    assert env.call(
        "update_case", fields={"stage": "READY_FOR_LENDER"}
    ).code == ("FIELD_NOT_ALLOWED")
    env.call("build_simulation", requested_amount="80000")
    r = env.call("update_case", fields={"requested_amount": "70000"})
    assert r.ok
    assert env.case().data["simulation"] is None  # el cambio invalida el plan


def test_update_valida_valores(env: Env) -> None:
    env.new_case()
    assert env.call("update_case", fields={"declared_income": "-5"}).code == (
        "INVALID_FIELD_VALUE"
    )
    assert env.call(
        "update_case", fields={"employment_type": "pirata"}
    ).code == ("INVALID_FIELD_VALUE")
    assert env.call("update_case", fields={"declared_income": "25000"}).ok


def test_en_documentos_ya_no_se_edita_nada(env: Env) -> None:
    env.advance_to_documents()
    assert env.call("update_case", fields={"declared_income": "1"}).code == (
        "STAGE_NOT_ALLOWED"
    )


# --- documentos -------------------------------------------------------------


def test_adjuntar_guarda_hash_y_no_el_texto_crudo(env: Env) -> None:
    env.advance_to_documents()
    r = env.call(
        "attach_document", doc_id="doc-good-payslip", doc_type="payslip"
    )
    assert (
        r.ok and r.output["accepted"] and len(r.output["content_hash"]) == 64
    )
    assert "Recibo de nomina" not in str(env.case().data)


def test_documento_de_otra_persona_se_bloquea_y_escala(env: Env) -> None:
    env.advance_to_documents()
    r = env.call(
        "attach_document", doc_id="doc-s10-payslip", doc_type="payslip"
    )
    assert r.ok and r.output["accepted"] is False
    assert env.case().stage is Stage.ESCALATED
    assert "payslip" not in (env.case().data.get("documents") or {})
    assert env.inbox.list_open()[0].reason_code == "FOREIGN_DOCUMENT"


def test_texto_con_instrucciones_queda_marcado(env: Env) -> None:
    env.advance_to_documents()
    r = env.call(
        "attach_document", doc_id="doc-s09-payslip", doc_type="payslip"
    )
    assert r.output["flags"] == ["PROMPT_INJECTION"]


def test_tipo_de_documento_desconocido(env: Env) -> None:
    env.advance_to_documents()
    r = env.call("attach_document", doc_id="doc-good-payslip", doc_type="meme")
    assert r.code == "UNKNOWN_DOC_TYPE"


def test_doc_id_con_ruta_se_rechaza(env: Env) -> None:
    env.advance_to_documents()
    r = env.call(
        "attach_document", doc_id="../../etc/passwd", doc_type="payslip"
    )
    assert r.status is ToolStatus.INVALID


def test_read_document_no_expone_el_texto_crudo(env: Env) -> None:
    env.advance_to_documents()
    env.call("attach_document", doc_id="doc-s09-payslip", doc_type="payslip")
    r = env.call("read_document", doc_type="payslip")
    assert r.ok and r.output["fields"]["gross_income"]["confidence"]
    assert "raw_text" not in r.output
    assert "IGNORA" not in str(r.output).upper()  # la orden inyectada no sale


def test_validaciones_expediente_correcto(env: Env) -> None:
    env.advance_to_documents()
    env.attach_all()
    r = env.call("run_document_validations")
    assert r.ok and r.output["outcome"] == "OK"
    assert env.case().stage is Stage.DOCUMENTS


def test_validaciones_con_faltantes(env: Env) -> None:
    env.advance_to_documents()
    env.call("attach_document", doc_id="doc-good-payslip", doc_type="payslip")
    r = env.call("run_document_validations")
    assert r.output["outcome"] == "PENDING"
    assert r.output["missing"] == [
        "proof_of_address",
        "id_card",
        "vehicle_title",
    ]


@pytest.mark.parametrize(
    ("doc", "dtype", "stage", "outcome"),
    [
        ("doc-s05-payslip", "payslip", Stage.ESCALATED, "ESCALATE"),
        ("doc-s06-payslip", "payslip", Stage.NEEDS_CORRECTION, "CORRECTION"),
        ("doc-s07-payslip", "payslip", Stage.NEEDS_CORRECTION, "CORRECTION"),
        ("doc-s08-id", "id_card", Stage.ESCALATED, "ESCALATE"),
        ("doc-s09-payslip", "payslip", Stage.ESCALATED, "ESCALATE"),
    ],
)
def test_documentos_problematicos(
    env: Env, doc: str, dtype: str, stage: Stage, outcome: str
) -> None:
    env.advance_to_documents()
    env.attach_all({**GOOD_DOCS, dtype: doc})
    r = env.call("run_document_validations")
    assert r.output["outcome"] == outcome
    assert env.case().stage is stage


def test_correccion_mensaje_y_reenvio(env: Env) -> None:
    env.advance_to_documents()
    env.attach_all({**GOOD_DOCS, "payslip": "doc-s06-payslip"})
    env.call("run_document_validations")
    r = env.call("request_customer_correction")
    assert r.ok and "ingreso" in r.output["message"] and r.output["delivered"]
    # el cliente reenvia: vuelve a DOCUMENTS y se revalida
    a = env.call(
        "attach_document", doc_id="doc-s06-payslip-fixed", doc_type="payslip"
    )
    assert a.output["stage"] == "DOCUMENTS"
    assert env.call("run_document_validations").output["outcome"] == "OK"


def test_correccion_sin_pendientes(env: Env) -> None:
    env.advance_to_documents()
    assert env.call("request_customer_correction").code == "STAGE_NOT_ALLOWED"


class _DownChannel:
    def send(self, case_id: str, text: str) -> str:
        raise ProviderError("canal caido", retryable=True)


def test_canal_caido_no_rompe_la_correccion(env: Env) -> None:
    env.advance_to_documents()
    env.attach_all({**GOOD_DOCS, "payslip": "doc-s06-payslip"})
    env.call("run_document_validations")
    broken = Executor(
        dataclasses.replace(env.deps, channel=_DownChannel()), build_catalog()
    )
    r = broken.call(
        env.agent,
        Session("c1"),
        "request_customer_correction",
        {"case_id": "c1"},
    )
    assert r.ok and r.output["delivered"] is False
    assert r.output["message"]  # igual se muestra en la sesion


def test_ingreso_verificado_invalida_la_cuota_y_vuelve_a_simulacion(
    env: Env,
) -> None:
    env.advance_to_documents(requested_amount="120000")
    env.attach_all({**GOOD_DOCS, "payslip": "doc-s11-payslip"})
    r = env.call("run_document_validations")
    assert r.output["outcome"] == "CAPACITY_EXCEEDED"
    c = env.case()
    assert c.stage is Stage.SIMULATION and c.data["chosen"] is None
    assert c.data["capacity_note"]["max_payment"] == "6475.00"
    # con el ingreso verificado, ya no ofrece lo que no cabe
    r2 = env.call("build_simulation", requested_amount="100000")
    by = {o["term_months"]: o["affordable"] for o in r2.output["options"]}
    assert by[24] is True and by[12] is False


# --- gate: mark_ready_for_lender -------------------------------------------


def test_camino_feliz_llega_a_listo(env: Env) -> None:
    env.advance_to_documents()
    env.attach_all()
    assert env.call("run_document_validations").output["outcome"] == "OK"
    r = env.call("mark_ready_for_lender")
    assert r.ok and r.output["status"] == "OK" and r.output["blocking"] == []
    assert env.case().stage is Stage.READY_FOR_LENDER


def test_gate_se_niega_sin_haber_corrido_validaciones(env: Env) -> None:
    """El agente 'cree' que ya termino: el gate no se fia de el."""
    env.advance_to_documents()
    env.attach_all({**GOOD_DOCS, "payslip": "doc-s09-payslip"})
    r = env.call("mark_ready_for_lender")
    assert (r.status, r.code) == (ToolStatus.DENIED, "NOT_READY")
    assert "docs_valid" in r.message or "documents_valid" in r.message
    assert env.case().stage is Stage.DOCUMENTS


def test_gate_se_niega_con_documentos_faltantes(env: Env) -> None:
    env.advance_to_documents()
    r = env.call("mark_ready_for_lender")
    assert r.code == "NOT_READY" and "documents_present" in r.reason_codes


def test_gate_detecta_documento_cambiado_tras_validar(env: Env) -> None:
    env.advance_to_documents()
    env.attach_all()
    assert env.call("run_document_validations").output["outcome"] == "OK"
    # se adjunta un comprobante peor DESPUES de validar; sin revalidar
    env.call("attach_document", doc_id="doc-s05-payslip", doc_type="payslip")
    r = env.call("mark_ready_for_lender")
    assert r.code == "NOT_READY"


def test_gate_detecta_simulacion_alterada(env: Env) -> None:
    env.advance_to_documents()
    env.attach_all()
    env.call("run_document_validations")
    c = env.case()
    tampered = dict(c.data)
    tampered["simulation"] = {
        **c.data["simulation"],
        "requested_amount": "10000",
    }
    env.repo.save(with_data(c, tampered), expected_version=c.version)
    r = env.call("mark_ready_for_lender")
    assert r.code == "NOT_READY" and "simulation_current" in r.reason_codes


def test_gate_con_el_asesor_tambien_se_niega(env: Env) -> None:
    env.advance_to_documents()
    r = env.as_advisor("mark_ready_for_lender")
    assert r.code == "NOT_READY"  # otro principal, mismo gate


def test_no_se_puede_marcar_listo_desde_otra_etapa(env: Env) -> None:
    env.new_case()
    assert env.call("mark_ready_for_lender").code == "STAGE_NOT_ALLOWED"


# --- escalada y asesor -----------------------------------------------


def test_escalada_manual_crea_ticket(env: Env) -> None:
    env.advance_to_documents()
    r = env.call(
        "escalate_to_human",
        reason_code="CUSTOMER_REQUEST",
        summary="El cliente pide hablar con un asesor",
    )
    assert r.ok and env.case().stage is Stage.ESCALATED
    assert env.inbox.list_open()[0].ticket_id == r.output["ticket_id"]


def _escalated_by_income(env: Env) -> str:
    env.advance_to_documents(requested_amount="50000")
    env.attach_all({**GOOD_DOCS, "payslip": "doc-s05-payslip"})
    env.call("run_document_validations")
    assert env.case().stage is Stage.ESCALATED
    return str(env.case().data["ticket_id"])


def test_asesor_reanuda_con_override_justificado(env: Env) -> None:
    ticket = _escalated_by_income(env)
    r = env.as_advisor(
        "resolve_escalation",
        ticket_id=ticket,
        decision="resume",
        justification="Comprobante validado por telefono",
        override_codes=["INCOME_MISMATCH"],
    )
    assert r.ok and env.case().stage is Stage.DOCUMENTS
    assert env.inbox.list_open() == []
    assert env.case().data["overrides"]["INCOME_MISMATCH"]["by"] == "advisor"
    assert env.call("run_document_validations").output["outcome"] == "OK"
    assert env.call("mark_ready_for_lender").ok


def test_override_no_perdona_la_capacidad_de_pago(env: Env) -> None:
    # 120000 a 24 meses = 6709.54, que no cabe en 35 % de 12000 (4200)
    env.advance_to_documents(requested_amount="120000")
    env.attach_all({**GOOD_DOCS, "payslip": "doc-s05-payslip"})
    env.call("run_document_validations")
    ticket = str(env.case().data["ticket_id"])
    env.as_advisor(
        "resolve_escalation",
        ticket_id=ticket,
        decision="resume",
        justification="Comprobante validado",
        override_codes=["INCOME_MISMATCH"],
    )
    # el ingreso ya no es objecion, pero la cuota debe caber en lo verificado
    r = env.call("run_document_validations")
    assert r.output["outcome"] == "CAPACITY_EXCEEDED"
    assert env.case().stage is Stage.SIMULATION
    assert env.call("mark_ready_for_lender").code == "STAGE_NOT_ALLOWED"


def test_el_agente_no_puede_resolver_tickets(env: Env) -> None:
    ticket = _escalated_by_income(env)
    r = env.call(
        "resolve_escalation",
        ticket_id=ticket,
        decision="resume",
        justification="me autoapruebo",
    )
    assert r.code == "SCOPE_DENIED" and env.case().stage is Stage.ESCALATED


@pytest.mark.parametrize(
    ("decision", "stage"),
    [("reject", Stage.REJECTED), ("decline", Stage.DECLINED)],
)
def test_asesor_cierra_el_caso(env: Env, decision: str, stage: Stage) -> None:
    ticket = _escalated_by_income(env)
    r = env.as_advisor(
        "resolve_escalation",
        ticket_id=ticket,
        decision=decision,
        justification="Documento no confiable",
    )
    assert r.ok and env.case().stage is stage


def test_resolver_exige_justificacion_y_overrides_validos(env: Env) -> None:
    ticket = _escalated_by_income(env)
    assert (
        env.as_advisor(
            "resolve_escalation",
            ticket_id=ticket,
            decision="resume",
            justification="ok",
        ).status
        is ToolStatus.INVALID
    )
    r = env.as_advisor(
        "resolve_escalation",
        ticket_id=ticket,
        decision="resume",
        justification="lo reviso yo",
        override_codes=["LOW_CONFIDENCE"],
    )
    assert r.code == "OVERRIDE_NOT_ALLOWED"


def test_ticket_de_otro_caso_no_se_puede_resolver(env: Env) -> None:
    ticket = _escalated_by_income(env)  # ticket del caso c1
    env.repo.add(
        Case(
            case_id="c2",
            stage=Stage.ESCALATED,
            escalated_from=Stage.DOCUMENTS,
            data=dict(BASE_DATA),
        )
    )
    r = env.as_advisor(
        "resolve_escalation",
        Session("c2"),
        ticket_id=ticket,
        decision="reject",
        justification="intento cruzado",
    )
    assert r.code == "TICKET_NOT_FOUND"
    assert env.case("c2").stage is Stage.ESCALATED
    assert len(env.inbox.list_open()) == 1  # el de c1 sigue abierto


def test_snapshot_no_expone_datos_personales(env: Env) -> None:
    env.advance_to_documents()
    env.attach_all()
    r = env.call("get_case_snapshot")
    text = str(r.output)
    assert "Juan" not in text and "cust-s01" not in text and "1234" not in text


def test_domicilio_de_la_identificacion_distinto_pide_correccion(
    env: Env,
) -> None:
    env.advance_to_documents()
    env.attach_all({**GOOD_DOCS, "id_card": "doc-v13-id-address-other"})
    r = env.call("run_document_validations")
    assert r.output["outcome"] == "CORRECTION"
    assert "ADDRESS_MISMATCH" in r.reason_codes
    msg = env.call("request_customer_correction")
    assert "domicilio" in msg.output["message"]


def test_comprobante_quincenal_se_normaliza_y_llega_a_listo(env: Env) -> None:
    env.advance_to_documents()
    env.attach_all({**GOOD_DOCS, "payslip": "doc-v15-payslip-biweekly"})
    assert env.call("run_document_validations").output["outcome"] == "OK"
    assert env.call("mark_ready_for_lender").ok
    assert env.case().data["verified_income"] == "20000.00"
