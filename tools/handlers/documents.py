"""Etapa de datos y comprobantes: adjuntar, leer y validar."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from domain.case import transition, with_data
from domain.doc_review import (
    CRITICAL_FIELDS,
    DocumentReview,
    ReviewOutcome,
    Severity,
)
from domain.documents import looks_like_injection, match_names
from domain.loan import (
    money,
)
from ports import DocumentRef, ProviderError
from tools.casedata import (
    review_case,
)
from tools.handlers.common import (
    MAX_PAYMENT_RATIO,
    CaseOnlyIn,
    S,
    copy_data,
    open_ticket,
)
from tools.spec import (
    Outcome,
    ToolContext,
    ToolInput,
    ToolRefusal,
)

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


def attach_document(ctx: ToolContext, inp: AttachIn) -> Outcome:
    if inp.doc_type not in DOC_TYPES:
        raise ToolRefusal(
            "UNKNOWN_DOC_TYPE", f"tipo no soportado: {inp.doc_type}"
        )
    ex = ctx.deps.reader.read(
        DocumentRef(doc_id=inp.doc_id, doc_type=inp.doc_type)
    )
    d = copy_data(ctx.case)
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
            ticket = open_ticket(
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
    d = copy_data(ctx.case)
    d["verified_income"] = (
        None if review.verified_income is None else str(review.verified_income)
    )
    d["validation"] = {"outcome": review.outcome.value}
    codes = tuple(f.code for f in review.active())
    if review.outcome is ReviewOutcome.ESCALATE:
        first = next(
            f for f in review.active() if f.severity is Severity.ESCALATE
        )
        d["ticket_id"] = open_ticket(
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
    d = copy_data(ctx.case)
    d["correction_requested"] = True
    return Outcome(
        CorrectionOut(message=message, delivered=delivered),
        with_data(ctx.case, d),
    )
