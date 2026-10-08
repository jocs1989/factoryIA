"""Politica por reglas: determinista, sin LLM. Tambien es el respaldo."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from agent import intent
from agent.types import Action, Policy, Reply, StageView, ToolCall
from domain.case import Stage

DOC_NAMES = {
    "payslip": "recibo de nomina",
    "proof_of_address": "comprobante de domicilio",
    "id_card": "identificacion oficial",
    "vehicle_title": "factura o tarjeta de circulacion",
    "bank_statement": "estados de cuenta",
    "tax_certificate": "constancia de situacion fiscal",
}


def _money(value: str) -> str:
    """Formatea un monto en pesos sin pasar por `float`."""
    return f"${Decimal(value):,.2f}"


class RuleBasedPolicy(Policy):
    name = "rules"

    def next_action(self, view: StageView) -> Action:
        handler = {
            Stage.ELIGIBILITY: self._eligibility,
            Stage.PROFILING: self._profiling,
            Stage.SIMULATION: self._simulation,
            Stage.DOCUMENTS: self._documents,
            Stage.NEEDS_CORRECTION: self._correction,
        }.get(view.stage)
        if handler is None:
            return Reply("Tu caso esta en proceso.")
        return handler(view)

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _last_denied(view: StageView, tool: str) -> Any:
        last = view.last
        if last and last.tool == tool and not last.ok:
            return last
        return None

    # --- etapas -----------------------------------------------------------

    def _eligibility(self, v: StageView) -> Action:
        last = v.last
        if (
            last
            and last.tool == "check_vehicle_eligibility"
            and last.ok
            and last.output
            and last.output["status"] == "NEEDS_INFO"
        ):
            return Reply(
                "Para continuar necesito saber si cuentas con la segunda "
                "llave de tu auto. ¿La tienes?"
            )
        declared = intent.parse_second_key(v.event.text) if v.event else None
        args = {} if declared is None else {"declared_second_key": declared}
        return ToolCall(tool="check_vehicle_eligibility", args=args)

    def _profiling(self, v: StageView) -> Action:
        c = v.case
        if c["needs_second_key_quote"] and not c["second_key_cost"]:
            return ToolCall(tool="quote_second_key")
        if not c["bureau_consent"]:
            consent = intent.parse_consent(v.event.text) if v.event else None
            if consent is True:
                return ToolCall(
                    tool="record_bureau_consent",
                    args={
                        "consent": True,
                        "evidence": (v.event.text[:200] if v.event else ""),
                    },
                )
            if consent is False:
                return Reply(
                    "Sin tu autorizacion para consultar el Buro de Credito "
                    "no podemos continuar con la solicitud."
                )
            extra = ""
            if c["second_key_cost"]:
                extra = (
                    f" Cotizamos tu segunda llave en "
                    f"{_money(c['second_key_cost'])}; se sumara al monto "
                    f"financiado."
                )
            return Reply(
                "Tu auto cumple los requisitos." + extra + " ¿Autorizas que "
                "consultemos tu historial en el Buro de Credito?"
            )
        return ToolCall(tool="query_credit_bureau")

    def _simulation(self, v: StageView) -> Action:
        c = v.case
        denied = self._last_denied(v, "build_simulation")
        if denied is not None:
            return Reply(
                "No pudimos armar esa simulacion: "
                f"{denied.message}. Dime otro monto."
            )
        denied = self._last_denied(v, "record_customer_choice")
        if denied is not None:
            return Reply(
                f"Ese plazo no es posible: {denied.message}. "
                "Elige otro de la lista."
            )
        if not c["simulation_options"]:
            amount = intent.parse_amount(v.event.text) if v.event else None
            if amount is None and c["capacity_note"]:
                note = c["capacity_note"]
                return Reply(
                    "Con el ingreso que comprobaste, la cuota maxima que "
                    f"puedes pagar es {_money(note['max_payment'])} al mes. "
                    "Indica un monto menor para recalcular tu plan."
                )
            if amount is None:
                amount_text = c["requested_amount"]
                if amount_text is None:
                    return Reply("¿Que monto necesitas?")
                return ToolCall(
                    tool="build_simulation",
                    args={"requested_amount": amount_text},
                )
            return ToolCall(
                tool="build_simulation", args={"requested_amount": str(amount)}
            )
        term = intent.parse_term(v.event.text) if v.event else None
        if term is not None:
            return ToolCall(
                tool="record_customer_choice", args={"term_months": term}
            )
        lines = []
        for o in c["simulation_options"]:
            mark = "" if o["affordable"] else " (excede tu capacidad de pago)"
            lines.append(
                f"- {o['term_months']} meses: {_money(o['monthly_payment'])}"
                f" al mes{mark}"
            )
        key = next(
            (
                o["second_key_cost"]
                for o in c["simulation_options"]
                if Decimal(o["second_key_cost"]) > 0
            ),
            None,
        )
        key_line = f"\nIncluye {_money(key)} de segunda llave." if key else ""
        return Reply(
            "Estas son tus opciones:\n"
            + "\n".join(lines)
            + key_line
            + "\n¿Cual plazo prefieres?"
        )

    def _documents(self, v: StageView) -> Action:
        c = v.case
        if v.pending_docs:
            d = v.pending_docs[0]
            return ToolCall(
                tool="attach_document",
                args={"doc_id": d.doc_id, "doc_type": d.doc_type},
            )
        last = v.last
        if last and last.tool == "mark_ready_for_lender" and not last.ok:
            return ToolCall(
                tool="escalate_to_human",
                args={
                    "reason_code": "GATE_NOT_READY",
                    "summary": "El expediente no paso la validacion final: "
                    + (last.message or ""),
                    "suggested_action": "Revisar los hallazgos del caso",
                },
            )
        if c["missing_documents"]:
            names = ", ".join(DOC_NAMES[t] for t in c["missing_documents"])
            return Reply(f"Para continuar envia: {names}.")
        if c["validation"] != "OK":
            return ToolCall(tool="run_document_validations")
        return ToolCall(tool="mark_ready_for_lender")

    def _correction(self, v: StageView) -> Action:
        if v.pending_docs:
            d = v.pending_docs[0]
            return ToolCall(
                tool="attach_document",
                args={"doc_id": d.doc_id, "doc_type": d.doc_type},
            )
        if not v.case["correction_requested"]:
            return ToolCall(tool="request_customer_correction")
        last = v.last
        if last and last.tool == "request_customer_correction" and last.output:
            return Reply(last.output["message"])
        return Reply("Seguimos esperando tu documento corregido.")
