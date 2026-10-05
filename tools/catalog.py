"""Catalogo de tools. Cada una valida su contrato; el dominio decide."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from domain.case import Case, Stage, transition, with_data
from domain.doc_review import (
    CRITICAL_FIELDS,
    DOC_QUALITY,
    INCOME_IDENTITY,
    OVERRIDABLE,
    OWNERSHIP,
    REQUIRED_DOCS,
    DocumentReview,
    ReviewOutcome,
    Severity,
)
from domain.documents import looks_like_injection, match_names
from domain.eligibility import (
    EligibilityStatus,
    evaluate_eligibility,
)
from domain.loan import (
    LoanError,
    SimulationOption,
    build_simulation,
    money,
    simulation_hash,
)
from domain.profile import ProfileStatus, evaluate_profile
from domain.readiness import (
    ReadinessInputs,
    ReadinessStatus,
    evaluate_readiness,
)
from ports import DocumentRef, ProviderError, Ticket, TicketError
from tools.casedata import (
    fresh_chosen_hash,
    money_of,
    review_case,
)
from tools.spec import (
    Effect,
    Outcome,
    Risk,
    ToolContext,
    ToolInput,
    ToolRefusal,
    ToolSpec,
)

S = Stage
ALL_STAGES = frozenset(Stage)
MAX_PAYMENT_RATIO = Decimal("0.35")
TERMINAL = frozenset({S.REJECTED, S.DECLINED, S.READY_FOR_LENDER})

CORRECTION_TEXT = {
    "WRONG_DOCUMENT_TYPE": (
        "El archivo no corresponde al tipo de documento pedido."
    ),
    "LOW_CONFIDENCE": (
        "No pudimos leer el documento con claridad; por favor envialo de "
        "nuevo, con buena luz y completo."
    ),
    "DOCUMENT_EXPIRED": (
        "El documento no esta vigente; envia uno mas reciente."
    ),
    "NAME_SIMILAR": (
        "El nombre del documento no coincide exactamente con el de tu "
        "solicitud; confirma o envia el documento correcto."
    ),
    "ADDRESS_SIMILAR": (
        "El domicilio del documento no coincide exactamente con el que "
        "declaraste; confirma o envia un documento actualizado."
    ),
    "ADDRESS_MISMATCH": (
        "El domicilio del documento no coincide con el que declaraste; "
        "confirmalo o envia un comprobante a tu domicilio actual."
    ),
    "CURRENCY_MISMATCH": (
        "El documento no esta en pesos mexicanos; envia uno en MXN."
    ),
    "UNSUPPORTED_PERIOD": (
        "No pudimos reconocer el periodo de pago del comprobante; envia "
        "uno mensual, quincenal o semanal."
    ),
    "INCOME_MISMATCH": (
        "El ingreso que comprueba el documento es menor al que declaraste; "
        "envia un comprobante que lo respalde o corrige tu ingreso."
    ),
}
DOC_TYPES = frozenset(CRITICAL_FIELDS)


# --- entradas / salidas ----------------------------------------------------


def _no_float(v: Any) -> Any:
    if isinstance(v, float):
        raise ValueError("usa texto o entero para montos, no decimales")
    return v


class CaseOnlyIn(ToolInput):
    pass


class SnapshotOut(BaseModel):
    stage: str
    version: int
    projection: dict[str, Any]


class CheckEligibilityIn(ToolInput):
    declared_second_key: bool | None = None


class EligibilityOut(BaseModel):
    status: str
    reason_codes: list[str]
    missing: list[str]
    needs_second_key_quote: bool
    stage: str


class QuoteOut(BaseModel):
    second_key_cost: str


class ConsentIn(ToolInput):
    consent: bool
    evidence: str = Field(default="", max_length=500)


class ConsentOut(BaseModel):
    recorded: bool


class ProfileOut(BaseModel):
    status: str
    band: str | None
    profile: str | None
    max_ltv: str | None
    annual_rate: str | None
    reason_codes: list[str]
    stage: str


class BuildSimIn(ToolInput):
    requested_amount: Decimal = Field(gt=0)

    _v = field_validator("requested_amount", mode="before")(_no_float)


class OptionOut(BaseModel):
    term_months: int
    principal: str
    second_key_cost: str
    monthly_payment: str
    total_to_pay: str
    affordable: bool


class SimulationOut(BaseModel):
    max_amount: str
    options: list[OptionOut]
    stage: str


class ChoiceIn(ToolInput):
    term_months: int = Field(gt=0)


class ChoiceOut(BaseModel):
    term_months: int
    simulation_hash: str
    stage: str


class AttachIn(ToolInput):
    doc_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    doc_type: str


class AttachOut(BaseModel):
    doc_type: str
    doc_id: str
    accepted: bool
    content_hash: str | None
    flags: list[str]
    stage: str


class ReadDocIn(ToolInput):
    doc_type: str


class ReadDocOut(BaseModel):
    doc_type: str
    fields: dict[str, dict[str, str]]
    flags: list[str]


class ValidationOut(BaseModel):
    outcome: str
    missing: list[str]
    findings: list[dict[str, Any]]
    stage: str


class CorrectionOut(BaseModel):
    message: str
    delivered: bool


class UpdateIn(ToolInput):
    fields: dict[str, str]


class UpdateOut(BaseModel):
    updated: list[str]
    stage: str


class ReadyOut(BaseModel):
    status: str
    checks: dict[str, bool]
    blocking: list[str]
    inputs_hash: str
    rule_version: str
    stage: str


class EscalateIn(ToolInput):
    reason_code: str = Field(pattern=r"^[A-Z_]{3,40}$")
    summary: str = Field(min_length=3, max_length=1000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    suggested_action: str = Field(default="Revisar el caso", max_length=500)


class EscalateOut(BaseModel):
    ticket_id: str
    stage: str


class ResolveIn(ToolInput):
    ticket_id: str
    decision: Literal["resume", "reject", "decline"]
    justification: str = Field(min_length=5, max_length=1000)
    override_codes: list[str] = Field(default_factory=list)


class ResolveOut(BaseModel):
    ticket_id: str
    decision: str
    stage: str


# --- utilidades -------------------------------------------------------------


def _ticket_id(case: Case) -> str:
    return f"T-{case.case_id}-{case.version}"


def _open_ticket(
    ctx: ToolContext,
    reason: str,
    summary: str,
    evidence: dict[str, Any],
    action: str,
) -> str:
    """Id determinista por (caso, version): un reintento no duplica."""
    ticket = Ticket(
        ticket_id=_ticket_id(ctx.case),
        case_id=ctx.case.case_id,
        reason_code=reason,
        summary=summary,
        evidence=evidence,
        suggested_action=action,
        created_at=ctx.deps.clock(),
    )
    try:
        ctx.deps.inbox.create(ticket)
    except TicketError:
        if ctx.deps.inbox.get(ticket.ticket_id) is None:
            raise
    return ticket.ticket_id


def _data(case: Case) -> dict[str, Any]:
    return dict(case.data)


def _need(case: Case, key: str, code: str, message: str) -> Any:
    value = case.data.get(key)
    if value in (None, "", {}):
        raise ToolRefusal(code, message)
    return value


def project_case(case: Case) -> dict[str, Any]:
    d = case.data
    sim = d.get("simulation") or {}
    return {
        "eligibility": (d.get("eligibility") or {}).get("status"),
        "needs_second_key_quote": (d.get("eligibility") or {}).get(
            "needs_second_key_quote"
        ),
        "second_key_cost": d.get("second_key_cost"),
        "bureau_consent": bool((d.get("bureau_consent") or {}).get("given")),
        "profile_band": (d.get("profile") or {}).get("band"),
        "profile_status": (d.get("profile") or {}).get("status"),
        "requested_amount": d.get("requested_amount"),
        "employment_type": d.get("employment_type"),
        "simulation_options": [
            {
                "term_months": o["term_months"],
                "monthly_payment": o["monthly_payment"],
                "principal": o["principal"],
                "second_key_cost": o["second_key_cost"],
                "affordable": o["term_months"]
                in sim.get("affordable_terms", []),
            }
            for o in sim.get("options", [])
        ],
        "max_amount": sim.get("max_amount"),
        "chosen_term": (d.get("chosen") or {}).get("term_months"),
        "documents": sorted((d.get("documents") or {}).keys()),
        "missing_documents": [
            t
            for t in REQUIRED_DOCS.get(
                str(d.get("employment_type", "salaried")), ()
            )
            if t not in (d.get("documents") or {})
        ],
        "validation": (d.get("validation") or {}).get("outcome"),
        "correction_requested": bool(d.get("correction_requested")),
        "open_corrections": [c["code"] for c in d.get("open_corrections", [])],
        "capacity_note": d.get("capacity_note"),
        "escalated_from": case.escalated_from.value
        if case.escalated_from
        else None,
    }


# --- handlers -----------------------------------------------------------


def get_case_snapshot(ctx: ToolContext, inp: CaseOnlyIn) -> Outcome:
    c = ctx.case
    return Outcome(
        SnapshotOut(
            stage=c.stage.value, version=c.version, projection=project_case(c)
        )
    )


def check_vehicle_eligibility(
    ctx: ToolContext, inp: CheckEligibilityIn
) -> Outcome:
    d = _data(ctx.case)
    record = ctx.deps.vehicles.get_vehicle(
        str(d["vehicle_id"]), str(d["customer_id"])
    )
    facts = record.facts
    # La declaracion del cliente solo llena lo que el registro no sabe.
    if facts.has_second_key is None and inp.declared_second_key is not None:
        facts = facts.model_copy(
            update={"has_second_key": inp.declared_second_key}
        )
    decision = evaluate_eligibility(facts)
    d["eligibility"] = decision.model_dump(mode="json")
    d["vehicle_value"] = str(record.appraised_value)
    if decision.status is EligibilityStatus.REJECTED:
        case = transition(with_data(ctx.case, d), S.REJECTED)
    elif decision.status is EligibilityStatus.ELIGIBLE:
        case = transition(with_data(ctx.case, d), S.PROFILING)
    else:
        case = with_data(ctx.case, d)
    return Outcome(
        EligibilityOut(
            status=decision.status.value,
            reason_codes=list(decision.reason_codes),
            missing=list(decision.missing),
            needs_second_key_quote=decision.needs_second_key_quote,
            stage=case.stage.value,
        ),
        case,
        reason_codes=decision.reason_codes,
    )


def quote_second_key(ctx: ToolContext, inp: CaseOnlyIn) -> Outcome:
    d = _data(ctx.case)
    if not (d.get("eligibility") or {}).get("needs_second_key_quote"):
        raise ToolRefusal(
            "KEY_QUOTE_NOT_NEEDED", "no se requiere cotizar llave"
        )
    cost = money(ctx.deps.key_quote.quote(str(d["vehicle_id"])))
    d["second_key_cost"] = str(cost)
    # Cambiar el capital invalida una simulacion previa.
    d["simulation"] = None
    d["chosen"] = None
    return Outcome(QuoteOut(second_key_cost=str(cost)), with_data(ctx.case, d))


def record_bureau_consent(ctx: ToolContext, inp: ConsentIn) -> Outcome:
    if not inp.consent:
        raise ToolRefusal(
            "CONSENT_NOT_GIVEN", "sin autorizacion no se consulta"
        )
    d = _data(ctx.case)
    d["bureau_consent"] = {
        "given": True,
        "at": ctx.deps.clock().isoformat(),
        "evidence": inp.evidence,
    }
    return Outcome(ConsentOut(recorded=True), with_data(ctx.case, d))


def query_credit_bureau(ctx: ToolContext, inp: CaseOnlyIn) -> Outcome:
    d = _data(ctx.case)
    if not (d.get("bureau_consent") or {}).get("given"):
        raise ToolRefusal(
            "CONSENT_REQUIRED", "falta la autorizacion expresa del titular"
        )
    if d.get("profile"):
        raise ToolRefusal("PROFILE_ALREADY_DONE", "el perfil ya se calculo")
    bureau = ctx.deps.bureau.query(str(d["customer_id"]))
    decision = evaluate_profile(ctx.deps.profile_policy, bureau)
    # Se guarda la decision, no el reporte ni el score.
    d["profile"] = decision.model_dump(mode="json")
    base = with_data(ctx.case, d)
    if decision.status is ProfileStatus.APPROVED:
        case = transition(base, S.SIMULATION)
    elif decision.status is ProfileStatus.DECLINED:
        case = transition(base, S.DECLINED)
    else:
        ticket = _open_ticket(
            ctx,
            decision.reason_codes[0],
            "Perfil crediticio sin informacion suficiente",
            {"reason_codes": list(decision.reason_codes)},
            "Revisar el expediente de credito",
        )
        d["ticket_id"] = ticket
        case = transition(with_data(ctx.case, d), S.ESCALATED)
    return Outcome(
        ProfileOut(
            status=decision.status.value,
            band=decision.band,
            profile=decision.profile,
            max_ltv=None
            if decision.max_ltv is None
            else str(decision.max_ltv),
            annual_rate=None
            if decision.annual_rate is None
            else str(decision.annual_rate),
            reason_codes=list(decision.reason_codes),
            stage=case.stage.value,
        ),
        case,
        rule_version=decision.rule_version,
        reason_codes=decision.reason_codes,
    )


def build_simulation_tool(ctx: ToolContext, inp: BuildSimIn) -> Outcome:
    d = _data(ctx.case)
    profile = d.get("profile") or {}
    if profile.get("status") != ProfileStatus.APPROVED.value:
        raise ToolRefusal("PROFILE_NOT_APPROVED", "el perfil no esta aprobado")
    needs_key = (d.get("eligibility") or {}).get("needs_second_key_quote")
    key_cost = money_of(d, "second_key_cost")
    if needs_key and key_cost is None:
        raise ToolRefusal(
            "KEY_QUOTE_REQUIRED", "falta cotizar la segunda llave"
        )
    try:
        sim = build_simulation(
            vehicle_value=Decimal(str(d["vehicle_value"])),
            requested_amount=inp.requested_amount,
            max_ltv=Decimal(str(profile["max_ltv"])),
            annual_rate=Decimal(str(profile["annual_rate"])),
            terms=ctx.deps.profile_policy.terms_months,
            second_key_cost=key_cost if needs_key and key_cost else Decimal(0),
        )
    except LoanError as exc:
        raise ToolRefusal("AMOUNT_NOT_ALLOWED", str(exc)) from exc
    income = money_of(d, "verified_income") or Decimal(
        str(d["declared_income"])
    )
    cap = income * MAX_PAYMENT_RATIO
    options = [
        OptionOut(
            term_months=o.term_months,
            principal=str(o.principal),
            second_key_cost=str(o.second_key_cost),
            monthly_payment=str(o.monthly_payment),
            total_to_pay=str(o.total_to_pay),
            affordable=o.monthly_payment <= cap,
        )
        for o in sim.options
    ]
    d["simulation"] = {
        "requested_amount": str(inp.requested_amount),
        "max_amount": str(sim.max_amount),
        "options": [o.model_dump(mode="json") for o in sim.options],
        "affordable_terms": [o.term_months for o in options if o.affordable],
    }
    d["requested_amount"] = str(inp.requested_amount)
    d["chosen"] = None
    d.pop("capacity_note", None)
    return Outcome(
        SimulationOut(
            max_amount=str(sim.max_amount),
            options=options,
            stage=ctx.case.stage.value,
        ),
        with_data(ctx.case, d),
        rule_version=ctx.deps.profile_policy.version,
    )


def record_customer_choice(ctx: ToolContext, inp: ChoiceIn) -> Outcome:
    d = _data(ctx.case)
    sim = d.get("simulation")
    if not sim:
        raise ToolRefusal("NO_SIMULATION", "no hay simulacion vigente")
    option = next(
        (o for o in sim["options"] if o["term_months"] == inp.term_months),
        None,
    )
    if option is None:
        raise ToolRefusal(
            "OPTION_NOT_FOUND", "ese plazo no esta en la simulacion"
        )
    if inp.term_months not in sim["affordable_terms"]:
        raise ToolRefusal(
            "OPTION_NOT_AFFORDABLE", "la cuota supera el 35 % del ingreso"
        )
    digest = simulation_hash(SimulationOption.model_validate(option))
    d["chosen"] = {"term_months": inp.term_months, "hash": digest}
    case = transition(with_data(ctx.case, d), S.DOCUMENTS)
    return Outcome(
        ChoiceOut(
            term_months=inp.term_months,
            simulation_hash=digest,
            stage=case.stage.value,
        ),
        case,
    )


def attach_document(ctx: ToolContext, inp: AttachIn) -> Outcome:
    if inp.doc_type not in DOC_TYPES:
        raise ToolRefusal(
            "UNKNOWN_DOC_TYPE", f"tipo no soportado: {inp.doc_type}"
        )
    ex = ctx.deps.reader.read(
        DocumentRef(doc_id=inp.doc_id, doc_type=inp.doc_type)
    )
    d = _data(ctx.case)
    name = ex.fields.get("full_name")
    texts = [ex.raw_text, *(f.value for f in ex.fields.values())]
    flags = ["PROMPT_INJECTION"] if looks_like_injection(*texts) else []
    base = ctx.case
    if base.stage is S.NEEDS_CORRECTION:
        base = transition(base, S.DOCUMENTS)  # el cliente reenvio
    # Un documento de otra persona se bloquea (no se liga) y se escala.
    if inp.doc_type != "id_card" and name is not None:
        sim_min = ctx.deps.document_policy.name_similarity_min
        if (
            match_names(
                name.value, str(d.get("customer_name", "")), sim_min
            ).value
            == "MISMATCH"
        ):
            ticket = _open_ticket(
                ctx,
                "FOREIGN_DOCUMENT",
                "Se adjunto un documento de otra persona",
                {"doc_type": inp.doc_type, "doc_id": inp.doc_id},
                "Confirmar con el cliente y pedir el documento correcto",
            )
            d["ticket_id"] = ticket
            case = transition(with_data(base, d), S.ESCALATED)
            return Outcome(
                AttachOut(
                    doc_type=inp.doc_type,
                    doc_id=inp.doc_id,
                    accepted=False,
                    content_hash=None,
                    flags=["FOREIGN_DOCUMENT"],
                    stage=case.stage.value,
                ),
                case,
                reason_codes=("FOREIGN_DOCUMENT",),
            )
    docs = dict(d.get("documents") or {})
    docs[inp.doc_type] = {
        "doc_id": inp.doc_id,
        "declared_type": inp.doc_type,
        "extracted_type": ex.doc_type,
        "content_hash": ex.content_hash,
        "fields": {
            n: {"value": f.value, "confidence": str(f.confidence)}
            for n, f in ex.fields.items()
        },
        "flags": flags,
    }
    d["documents"] = docs
    d["validation"] = None  # lo anterior ya no vale
    case = with_data(base, d)
    return Outcome(
        AttachOut(
            doc_type=inp.doc_type,
            doc_id=inp.doc_id,
            accepted=True,
            content_hash=ex.content_hash,
            flags=flags,
            stage=case.stage.value,
        ),
        case,
        reason_codes=tuple(flags),
    )


def read_document(ctx: ToolContext, inp: ReadDocIn) -> Outcome:
    doc = (ctx.case.data.get("documents") or {}).get(inp.doc_type)
    if doc is None:
        raise ToolRefusal(
            "DOCUMENT_NOT_ATTACHED", "ese documento no esta ligado"
        )
    # Solo campos estructurados: el texto crudo nunca llega al modelo.
    return Outcome(
        ReadDocOut(
            doc_type=inp.doc_type,
            fields={
                n: {"value": f["value"], "confidence": f["confidence"]}
                for n, f in doc["fields"].items()
            },
            flags=list(doc.get("flags", [])),
        )
    )


def _findings(review: DocumentReview) -> list[dict[str, Any]]:
    return [f.model_dump(mode="json") for f in review.findings]


def run_document_validations(ctx: ToolContext, inp: CaseOnlyIn) -> Outcome:
    review = review_case(ctx.case, ctx.deps)
    d = _data(ctx.case)
    d["verified_income"] = (
        None if review.verified_income is None else str(review.verified_income)
    )
    d["validation"] = {"outcome": review.outcome.value}
    codes = tuple(f.code for f in review.active())
    if review.outcome is ReviewOutcome.ESCALATE:
        first = next(
            f for f in review.active() if f.severity is Severity.ESCALATE
        )
        d["ticket_id"] = _open_ticket(
            ctx,
            first.code,
            first.message,
            {"findings": _findings(review)},
            "Revisar la evidencia y decidir",
        )
        case = transition(with_data(ctx.case, d), S.ESCALATED)
    elif review.outcome is ReviewOutcome.CORRECTION:
        d["open_corrections"] = [
            {"code": f.code, "doc_type": f.doc_type, "message": f.message}
            for f in review.active()
        ]
        d["correction_requested"] = False
        case = transition(with_data(ctx.case, d), S.NEEDS_CORRECTION)
    elif review.outcome is ReviewOutcome.CAPACITY_EXCEEDED:
        cap = (review.verified_income or Decimal(0)) * MAX_PAYMENT_RATIO
        d["simulation"] = None
        d["chosen"] = None
        d["capacity_note"] = {
            "verified_income": str(review.verified_income),
            "max_payment": str(money(cap)),
        }
        case = transition(with_data(ctx.case, d), S.SIMULATION)
    else:
        d["open_corrections"] = []
        case = with_data(ctx.case, d)
    return Outcome(
        ValidationOut(
            outcome=review.outcome.value,
            missing=list(review.missing),
            findings=_findings(review),
            stage=case.stage.value,
        ),
        case,
        rule_version=ctx.deps.document_policy.version,
        reason_codes=codes,
    )


def request_customer_correction(ctx: ToolContext, inp: CaseOnlyIn) -> Outcome:
    pending = ctx.case.data.get("open_corrections") or []
    if not pending:
        raise ToolRefusal("NOTHING_TO_CORRECT", "no hay correcciones abiertas")
    lines = [CORRECTION_TEXT.get(c["code"], c["message"]) for c in pending]
    message = "Necesitamos una correccion:\n- " + "\n- ".join(lines)
    try:
        ctx.deps.channel.send(ctx.case.case_id, message)
        delivered = True
    except ProviderError:
        delivered = False  # el mensaje igual se muestra en la sesion
    d = _data(ctx.case)
    d["correction_requested"] = True
    return Outcome(
        CorrectionOut(message=message, delivered=delivered),
        with_data(ctx.case, d),
    )


_FIELDS_BY_STAGE: dict[Stage, frozenset[str]] = {
    S.ELIGIBILITY: frozenset(
        {
            "customer_name",
            "vehicle_id",
            "declared_income",
            "employment_type",
            "requested_amount",
        }
    ),
    S.PROFILING: frozenset(
        {"declared_income", "employment_type", "requested_amount"}
    ),
    # Tras elegir plazo ya no se puede tocar el ingreso declarado.
    S.SIMULATION: frozenset({"requested_amount", "employment_type"}),
}


def _clean(field: str, raw: str) -> str:
    if field in ("declared_income", "requested_amount"):
        value = Decimal(raw)
        if value <= 0:
            raise ValueError
        return str(value)
    if field == "employment_type":
        if raw not in ("salaried", "self_employed"):
            raise ValueError
        return raw
    if not raw.strip():
        raise ValueError
    return raw.strip()


def update_case(ctx: ToolContext, inp: UpdateIn) -> Outcome:
    allowed = _FIELDS_BY_STAGE.get(ctx.case.stage, frozenset())
    bad = sorted(set(inp.fields) - allowed)
    if bad:
        raise ToolRefusal(
            "FIELD_NOT_ALLOWED",
            f"campos no editables en {ctx.case.stage.value}: {', '.join(bad)}",
        )
    d = _data(ctx.case)
    try:
        for name, raw in inp.fields.items():
            d[name] = _clean(name, raw)
    except (ValueError, ArithmeticError) as exc:
        raise ToolRefusal("INVALID_FIELD_VALUE", "valor invalido") from exc
    if "requested_amount" in inp.fields:
        d["simulation"] = None
        d["chosen"] = None
    return Outcome(
        UpdateOut(updated=sorted(inp.fields), stage=ctx.case.stage.value),
        with_data(ctx.case, d),
    )


def mark_ready_for_lender(ctx: ToolContext, inp: CaseOnlyIn) -> Outcome:
    """Reevalua el gate COMPLETO desde los datos, sin confiar en banderas
    guardadas ni en lo que haya dicho el agente."""
    d = ctx.case.data
    review = review_case(ctx.case, ctx.deps)
    chosen = d.get("chosen") or {}
    inputs = ReadinessInputs(
        eligibility_ok=(d.get("eligibility") or {}).get("status")
        == EligibilityStatus.ELIGIBLE.value,
        profile_approved=(d.get("profile") or {}).get("status")
        == ProfileStatus.APPROVED.value,
        chosen_simulation_hash=chosen.get("hash"),
        current_simulation_hash=fresh_chosen_hash(ctx.case),
        required_docs_present=not review.missing,
        docs_valid_and_vigent=not review.active(DOC_QUALITY),
        income_identity_match=not review.active(INCOME_IDENTITY),
        ownership_coherent=not review.active(OWNERSHIP),
        payment_capacity_ok=review.payment_capacity_ok is True,
        open_corrections=len(
            [f for f in review.active() if f.severity is Severity.CORRECTION]
        ),
    )
    decision = evaluate_readiness(inputs)
    if decision.status is not ReadinessStatus.OK:
        raise ToolRefusal(
            "NOT_READY",
            "el expediente no cumple: " + ", ".join(decision.blocking),
            decision.blocking,
        )
    nd = dict(d)
    nd["readiness"] = {
        "inputs_hash": decision.inputs_hash,
        "rule_version": decision.rule_version,
    }
    case = transition(with_data(ctx.case, nd), S.READY_FOR_LENDER)
    return Outcome(
        ReadyOut(
            status=decision.status.value,
            checks=decision.checks,
            blocking=list(decision.blocking),
            inputs_hash=decision.inputs_hash,
            rule_version=decision.rule_version,
            stage=case.stage.value,
        ),
        case,
        rule_version=decision.rule_version,
    )


def escalate_to_human(ctx: ToolContext, inp: EscalateIn) -> Outcome:
    ticket = _open_ticket(
        ctx, inp.reason_code, inp.summary, inp.evidence, inp.suggested_action
    )
    d = _data(ctx.case)
    d["ticket_id"] = ticket
    case = transition(with_data(ctx.case, d), S.ESCALATED)
    return Outcome(
        EscalateOut(ticket_id=ticket, stage=case.stage.value),
        case,
        reason_codes=(inp.reason_code,),
    )


def resolve_escalation(ctx: ToolContext, inp: ResolveIn) -> Outcome:
    ticket = ctx.deps.inbox.get(inp.ticket_id)
    if ticket is None or ticket.case_id != ctx.case.case_id:
        raise ToolRefusal("TICKET_NOT_FOUND", "el ticket no es de este caso")
    if ticket.status.value != "OPEN":
        raise ToolRefusal("TICKET_CLOSED", "el ticket ya fue resuelto")
    d = _data(ctx.case)
    if inp.decision == "resume":
        bad = sorted(set(inp.override_codes) - OVERRIDABLE)
        if bad:
            raise ToolRefusal(
                "OVERRIDE_NOT_ALLOWED",
                f"no se puede perdonar: {', '.join(bad)}",
            )
        overrides = dict(d.get("overrides") or {})
        for code in inp.override_codes:
            overrides[code] = {
                "by": ctx.principal.id,
                "justification": inp.justification,
                "ticket": inp.ticket_id,
            }
        d["overrides"] = overrides
        target = ctx.case.escalated_from or S.DOCUMENTS
    else:
        target = S.REJECTED if inp.decision == "reject" else S.DECLINED
    case = transition(with_data(ctx.case, d), target)
    inbox = ctx.deps.inbox
    resolver = ctx.principal.id

    def close_ticket() -> None:
        inbox.resolve(
            inp.ticket_id, resolution=inp.justification, resolved_by=resolver
        )

    return Outcome(
        ResolveOut(
            ticket_id=inp.ticket_id,
            decision=inp.decision,
            stage=case.stage.value,
        ),
        case,
        reason_codes=tuple(inp.override_codes),
        after_commit=(close_ticket,),
    )


# --- registro ------------------------------------------------------------

_E = Effect
_R = Risk
_PRE_DOCS = frozenset({S.ELIGIBILITY, S.PROFILING, S.SIMULATION})


def build_catalog() -> Mapping[str, ToolSpec]:
    specs = [
        ToolSpec(
            "get_case_snapshot",
            "Resumen compacto del caso y su etapa.",
            CaseOnlyIn,
            SnapshotOut,
            _E.READ,
            _R.LOW,
            "case:read",
            ALL_STAGES,
            get_case_snapshot,
        ),
        ToolSpec(
            "check_vehicle_eligibility",
            "Consulta el registro del vehiculo; el veredicto lo calcula el "
            "sistema. declared_second_key solo llena lo que el registro "
            "no sabe.",
            CheckEligibilityIn,
            EligibilityOut,
            _E.EXTERNAL_READ,
            _R.LOW,
            "vehicle:read",
            frozenset({S.ELIGIBILITY}),
            check_vehicle_eligibility,
        ),
        ToolSpec(
            "quote_second_key",
            "Cotiza la segunda llave (se suma al plan).",
            CaseOnlyIn,
            QuoteOut,
            _E.EXTERNAL_READ,
            _R.LOW,
            "quote:read",
            frozenset({S.PROFILING, S.SIMULATION}),
            quote_second_key,
            idempotent=True,
        ),
        ToolSpec(
            "record_bureau_consent",
            "Registra la autorizacion expresa para consultar el Buro.",
            ConsentIn,
            ConsentOut,
            _E.WRITE,
            _R.LOW,
            "consent:write",
            frozenset({S.PROFILING}),
            record_bureau_consent,
        ),
        ToolSpec(
            "query_credit_bureau",
            "Consulta el Buro (exige consentimiento) y devuelve el perfil.",
            CaseOnlyIn,
            ProfileOut,
            _E.EXTERNAL_READ,
            _R.LOW,
            "bureau:query",
            frozenset({S.PROFILING}),
            query_credit_bureau,
            idempotent=True,
            sensitive=True,
        ),
        ToolSpec(
            "build_simulation",
            "Calcula las opciones de credito para un monto.",
            BuildSimIn,
            SimulationOut,
            _E.COMPUTE,
            _R.LOW,
            "simulation:run",
            frozenset({S.SIMULATION}),
            build_simulation_tool,
        ),
        ToolSpec(
            "record_customer_choice",
            "Guarda el plazo que elige el cliente.",
            ChoiceIn,
            ChoiceOut,
            _E.WRITE,
            _R.LOW,
            "case:write",
            frozenset({S.SIMULATION}),
            record_customer_choice,
        ),
        ToolSpec(
            "attach_document",
            "Liga un documento al caso (hash, titular, texto sospechoso).",
            AttachIn,
            AttachOut,
            _E.WRITE,
            _R.LOW,
            "document:write",
            frozenset({S.DOCUMENTS, S.NEEDS_CORRECTION}),
            attach_document,
        ),
        ToolSpec(
            "read_document",
            "Campos extraidos de un documento ligado, con su confianza.",
            ReadDocIn,
            ReadDocOut,
            _E.READ,
            _R.LOW,
            "case:read",
            frozenset({S.DOCUMENTS, S.NEEDS_CORRECTION, S.ESCALATED}),
            read_document,
        ),
        ToolSpec(
            "run_document_validations",
            "Ejecuta las reglas documentales y mueve el caso segun el "
            "resultado.",
            CaseOnlyIn,
            ValidationOut,
            _E.COMPUTE,
            _R.LOW,
            "document:validate",
            frozenset({S.DOCUMENTS}),
            run_document_validations,
        ),
        ToolSpec(
            "request_customer_correction",
            "Genera el mensaje de correccion para el cliente.",
            CaseOnlyIn,
            CorrectionOut,
            _E.WRITE,
            _R.LOW,
            "case:write",
            frozenset({S.NEEDS_CORRECTION}),
            request_customer_correction,
        ),
        ToolSpec(
            "update_case",
            "Edita campos permitidos segun la etapa.",
            UpdateIn,
            UpdateOut,
            _E.WRITE,
            _R.LOW,
            "case:write",
            _PRE_DOCS,
            update_case,
        ),
        ToolSpec(
            "mark_ready_for_lender",
            "Marca el expediente listo. Reevalua el gate completo y se "
            "niega si algo falla.",
            CaseOnlyIn,
            ReadyOut,
            _E.WRITE,
            _R.HIGH,
            "case:mark_ready",
            frozenset({S.DOCUMENTS}),
            mark_ready_for_lender,
        ),
        ToolSpec(
            "escalate_to_human",
            "Crea un ticket para el asesor.",
            EscalateIn,
            EscalateOut,
            _E.WRITE,
            _R.LOW,
            "case:escalate",
            frozenset({S.PROFILING, S.DOCUMENTS}),
            escalate_to_human,
        ),
        ToolSpec(
            "resolve_escalation",
            "El asesor resuelve un ticket: reanudar, rechazar o declinar.",
            ResolveIn,
            ResolveOut,
            _E.WRITE,
            _R.HIGH,
            "ticket:resolve",
            frozenset({S.ESCALATED}),
            resolve_escalation,
        ),
    ]
    return {s.name: s for s in specs}
