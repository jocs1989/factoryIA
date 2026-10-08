"""Revision documental completa: funcion pura sobre hechos ya extraidos.

El LLM extrae; aqui se compara con umbrales versionados. La usan tanto
`run_document_validations` como el gate, que la repite desde cero.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from domain.documents import (
    DocumentPolicy,
    IncomeResult,
    NameMatch,
    check_income,
    extraction_trusted,
    id_not_expired,
    is_vigent,
    match_address,
    match_names,
    net_matches,
    payment_capacity_ok,
    to_monthly,
    valid_curp,
    valid_rfc,
)

REQUIRED_DOCS: dict[str, tuple[str, ...]] = {
    "salaried": ("payslip", "proof_of_address", "id_card", "vehicle_title"),
    "self_employed": (
        "bank_statement",
        "tax_certificate",
        "proof_of_address",
        "id_card",
        "vehicle_title",
    ),
}
INCOME_DOC = {"salaried": "payslip", "self_employed": "bank_statement"}
INCOME_FIELD = {
    "payslip": "gross_income",
    "bank_statement": "average_monthly_income",
}
CRITICAL_FIELDS: dict[str, tuple[str, ...]] = {
    "payslip": (
        "full_name",
        "gross_income",
        "deductions",
        "net_income",
        "issue_date",
        "currency",
        "pay_period",
    ),
    "proof_of_address": ("full_name", "street", "postal_code", "issue_date"),
    "id_card": (
        "full_name",
        "curp",
        "expiry_date",
        "street",
        "postal_code",
    ),
    "vehicle_title": ("full_name", "plates"),
    "bank_statement": (
        "full_name",
        "average_monthly_income",
        "issue_date",
    ),
    "tax_certificate": ("full_name", "rfc", "issue_date"),
}
VALIDITY_KEY = {
    "payslip": "payslip",
    "proof_of_address": "proof_of_address",
    "bank_statement": "bank_statement",
    "tax_certificate": "tax_certificate",
}

# Que significa cada codigo para el gate.
DOC_QUALITY = frozenset(
    {
        "WRONG_DOCUMENT_TYPE",
        "LOW_CONFIDENCE",
        "DOCUMENT_EXPIRED",
        "SUSPICIOUS_CONTENT",
    }
)
INCOME_IDENTITY = frozenset(
    {
        "INCOME_MISMATCH",
        "IDENTITY_MISMATCH",
        "NAME_SIMILAR",
        "FOREIGN_DOCUMENT",
        "ADDRESS_MISMATCH",
        "ADDRESS_SIMILAR",
        "CURRENCY_MISMATCH",
        "UNSUPPORTED_PERIOD",
    }
)
OWNERSHIP = frozenset({"VEHICLE_TITLE_MISMATCH"})
OVERRIDABLE = frozenset(
    {
        "INCOME_MISMATCH",
        "IDENTITY_MISMATCH",
        "SUSPICIOUS_CONTENT",
        "VEHICLE_TITLE_MISMATCH",
    }
)


class Severity(StrEnum):
    """Gravedad de un hallazgo: pedir correccion o escalar a un asesor."""

    CORRECTION = "CORRECTION"
    ESCALATE = "ESCALATE"


class ReviewOutcome(StrEnum):
    """Resultado global de la revision documental."""

    OK = "OK"
    PENDING = "PENDING"  # faltan documentos
    CORRECTION = "CORRECTION"
    ESCALATE = "ESCALATE"
    CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"


class DocField(BaseModel):
    """Campo extraido de un documento y su confianza."""

    model_config = ConfigDict(frozen=True)

    value: str
    confidence: Decimal


class DocFacts(BaseModel):
    """Documento ligado con su tipo declarado, el detectado y sus campos."""

    model_config = ConfigDict(frozen=True)

    declared_type: str
    extracted_type: str
    fields: dict[str, DocField]
    flags: tuple[str, ...] = ()


class Finding(BaseModel):
    """Hallazgo de la revision; un asesor puede levantarlo si es escalable."""

    model_config = ConfigDict(frozen=True)

    code: str
    severity: Severity
    doc_type: str | None = None
    message: str
    overridden: bool = False


class ReviewInput(BaseModel):
    """Todo lo que la revision necesita; se recalcula desde cero cada vez."""

    model_config = ConfigDict(frozen=True)

    customer_name: str
    address_street: str
    address_postal_code: str
    declared_income: Decimal
    employment_type: str
    documents: dict[str, DocFacts]
    chosen_payment: Decimal | None
    today: date
    overrides: frozenset[str] = frozenset()


class DocumentReview(BaseModel):
    """Resultado de revisar el expediente.

    Faltantes, hallazgos e ingreso verificado.
    """

    model_config = ConfigDict(frozen=True)

    outcome: ReviewOutcome
    missing: tuple[str, ...]
    findings: tuple[Finding, ...]
    verified_income: Decimal | None
    payment_capacity_ok: bool | None

    def active(self, codes: frozenset[str] | None = None) -> list[Finding]:
        """Hallazgos vigentes (no levantados), opcional por codigos."""
        return [
            f
            for f in self.findings
            if not f.overridden and (codes is None or f.code in codes)
        ]


def _date(doc: DocFacts, name: str) -> date | None:
    field = doc.fields.get(name)
    try:
        return date.fromisoformat(field.value) if field else None
    except ValueError:
        return None


def _decimal(doc: DocFacts, name: str) -> Decimal | None:
    field = doc.fields.get(name)
    try:
        return Decimal(field.value) if field else None
    except InvalidOperation:
        return None


def _validators_ok(doc_type: str, doc: DocFacts) -> bool:
    """Validadores objetivos: formato y aritmetica."""
    ok = True
    for name in ("curp",):
        f = doc.fields.get(name)
        if f is not None and not valid_curp(f.value):
            ok = False
    f = doc.fields.get("rfc")
    if f is not None and not valid_rfc(f.value):
        ok = False
    if doc_type == "payslip":
        gross = _decimal(doc, "gross_income")
        ded = _decimal(doc, "deductions")
        net = _decimal(doc, "net_income")
        if (
            gross is None
            or ded is None
            or net is None
            or not net_matches(gross, ded, net)
        ):
            ok = False
    return ok


def review_documents(
    inp: ReviewInput, policy: DocumentPolicy
) -> DocumentReview:
    """Valida el expediente en codigo.

    El modelo extrae, aqui se compara con umbrales.
    """
    findings: list[Finding] = []

    def add(code: str, sev: Severity, doc_type: str | None, msg: str) -> None:
        overridden = sev is Severity.ESCALATE and code in inp.overrides
        findings.append(
            Finding(
                code=code,
                severity=sev,
                doc_type=doc_type,
                message=msg,
                overridden=overridden,
            )
        )

    required = REQUIRED_DOCS.get(inp.employment_type)
    if required is None:
        raise ValueError(f"tipo de empleo desconocido: {inp.employment_type}")
    missing = tuple(t for t in required if t not in inp.documents)

    for doc_type, doc in inp.documents.items():
        if doc.extracted_type != doc.declared_type:
            add(
                "WRONG_DOCUMENT_TYPE",
                Severity.CORRECTION,
                doc_type,
                f"se esperaba {doc.declared_type} y parece "
                f"{doc.extracted_type}",
            )
            continue
        if "PROMPT_INJECTION" in doc.flags:
            add(
                "SUSPICIOUS_CONTENT",
                Severity.ESCALATE,
                doc_type,
                "el documento contiene texto que intenta dar instrucciones",
            )

        critical = CRITICAL_FIELDS.get(doc_type, ())
        absent = [n for n in critical if n not in doc.fields]
        validators = _validators_ok(doc_type, doc)
        weak = [
            n
            for n in critical
            if n in doc.fields
            and not extraction_trusted(
                doc.fields[n].confidence, policy, validators
            )
        ]
        if absent or weak or not validators:
            add(
                "LOW_CONFIDENCE",
                Severity.CORRECTION,
                doc_type,
                "no se pudo leer con certeza: "
                + ", ".join(absent + weak or ["formato"]),
            )
            continue

        key = VALIDITY_KEY.get(doc_type)
        if key is not None:
            issued = _date(doc, "issue_date")
            if issued is None or not is_vigent(
                issued, inp.today, policy.validity_days[key]
            ):
                add(
                    "DOCUMENT_EXPIRED",
                    Severity.CORRECTION,
                    doc_type,
                    "el documento no esta vigente",
                )
        if doc_type == "id_card":
            expiry = _date(doc, "expiry_date")
            if expiry is None or not id_not_expired(expiry, inp.today):
                add(
                    "DOCUMENT_EXPIRED",
                    Severity.CORRECTION,
                    doc_type,
                    "la identificacion esta vencida",
                )

        currency = doc.fields.get("currency")
        if currency is not None and (
            currency.value.strip().upper() != policy.expected_currency
        ):
            add(
                "CURRENCY_MISMATCH",
                Severity.CORRECTION,
                doc_type,
                f"la moneda del documento no es {policy.expected_currency}",
            )

        if "street" in doc.fields and "postal_code" in doc.fields:
            addr = match_address(
                doc.fields["street"].value,
                doc.fields["postal_code"].value,
                inp.address_street,
                inp.address_postal_code,
                policy.address_similarity_min,
            )
            if addr is NameMatch.SIMILAR:
                add(
                    "ADDRESS_SIMILAR",
                    Severity.CORRECTION,
                    doc_type,
                    "el domicilio no coincide exactamente con el declarado",
                )
            elif addr is NameMatch.MISMATCH:
                add(
                    "ADDRESS_MISMATCH",
                    Severity.CORRECTION,
                    doc_type,
                    "el domicilio no coincide con el declarado",
                )

        match = match_names(
            doc.fields["full_name"].value,
            inp.customer_name,
            policy.name_similarity_min,
        )
        if match is NameMatch.SIMILAR:
            add(
                "NAME_SIMILAR",
                Severity.CORRECTION,
                doc_type,
                "el nombre no coincide exactamente",
            )
        elif match is NameMatch.MISMATCH:
            if doc_type == "id_card":
                add(
                    "IDENTITY_MISMATCH",
                    Severity.ESCALATE,
                    doc_type,
                    "el nombre de la identificacion no coincide",
                )
            elif doc_type == "vehicle_title":
                add(
                    "VEHICLE_TITLE_MISMATCH",
                    Severity.ESCALATE,
                    doc_type,
                    "el titular de la factura no coincide con el cliente",
                )
            else:
                add(
                    "FOREIGN_DOCUMENT",
                    Severity.ESCALATE,
                    doc_type,
                    "el documento parece ser de otra persona",
                )

    # Coherencia entre documentos: la CURP debe ser la misma.
    curps = {
        d.fields["curp"].value.upper()
        for d in inp.documents.values()
        if "curp" in d.fields
    }
    if len(curps) > 1:
        add(
            "IDENTITY_MISMATCH",
            Severity.ESCALATE,
            None,
            "la CURP difiere entre documentos",
        )

    # Ingreso verificado contra el declarado.
    verified: Decimal | None = None
    income_doc = inp.documents.get(INCOME_DOC[inp.employment_type])
    if income_doc is not None:
        raw = _decimal(income_doc, INCOME_FIELD[income_doc.declared_type])
        period = income_doc.fields.get("pay_period")
        if raw is not None and period is not None:
            verified = to_monthly(raw, period.value, policy)
            if verified is None:
                add(
                    "UNSUPPORTED_PERIOD",
                    Severity.CORRECTION,
                    income_doc.declared_type,
                    f"periodo de pago no reconocido: {period.value}",
                )
        else:
            verified = raw  # estados de cuenta: ya es un promedio mensual
        if verified is not None:
            check = check_income(inp.declared_income, verified, policy)
            if check.result is IncomeResult.CORRECTION:
                add(
                    "INCOME_MISMATCH",
                    Severity.CORRECTION,
                    income_doc.declared_type,
                    "el ingreso comprobado es menor al declarado",
                )
            elif check.result is IncomeResult.ESCALATE:
                add(
                    "INCOME_MISMATCH",
                    Severity.ESCALATE,
                    income_doc.declared_type,
                    "el ingreso comprobado difiere demasiado del declarado",
                )

    active = [f for f in findings if not f.overridden]
    capacity: bool | None = None
    if not active and verified is not None and inp.chosen_payment is not None:
        capacity = payment_capacity_ok(inp.chosen_payment, verified, policy)

    if any(f.severity is Severity.ESCALATE for f in active):
        outcome = ReviewOutcome.ESCALATE
    elif any(f.severity is Severity.CORRECTION for f in active):
        outcome = ReviewOutcome.CORRECTION
    elif missing:
        outcome = ReviewOutcome.PENDING
    elif capacity is False:
        outcome = ReviewOutcome.CAPACITY_EXCEEDED
    else:
        outcome = ReviewOutcome.OK
    return DocumentReview(
        outcome=outcome,
        missing=missing,
        findings=tuple(findings),
        verified_income=verified,
        payment_capacity_ok=capacity,
    )
