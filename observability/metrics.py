"""Metricas del reto, calculadas solo desde la bitacora."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from ports import AuditEvent

REJECTION_CODES = {"VEHICLE_NOT_OWNED", "VEHICLE_ENCUMBERED"}
MISMATCH_CODES = {
    "INCOME_MISMATCH": "ingreso",
    "IDENTITY_MISMATCH": "identidad",
    "NAME_SIMILAR": "nombre",
    "FOREIGN_DOCUMENT": "documento ajeno",
    "VEHICLE_TITLE_MISMATCH": "titularidad del vehiculo",
    "DOCUMENT_EXPIRED": "vigencia",
    "LOW_CONFIDENCE": "baja confianza",
    "WRONG_DOCUMENT_TYPE": "tipo de documento",
    "SUSPICIOUS_CONTENT": "contenido sospechoso",
}


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


@dataclass
class ToolStats:
    calls: int = 0
    denied: int = 0
    errors: int = 0
    latencies: list[int] = field(default_factory=list)

    @property
    def p95_ms(self) -> int:
        return _p95(self.latencies)


@dataclass
class Metrics:
    cases: int
    rejections_by_reason: dict[str, int]
    mismatches_by_type: dict[str, int]
    key_quoted_cases: list[str]
    escalated_cases: int
    escalation_rate: float
    ready_cases: int
    denials_by_code: dict[str, int]
    tools: dict[str, ToolStats]
    llm: dict[str, int]
    llm_p95_ms: int
    invariant_violations: int


def compute_metrics(events: Iterable[AuditEvent]) -> Metrics:
    evs = list(events)
    cases = {e.case_id for e in evs}
    rejections: Counter[str] = Counter()
    mismatches: Counter[str] = Counter()
    denials: Counter[str] = Counter()
    keys: set[str] = set()
    escalated: set[str] = set()
    ready: set[str] = set()
    llm: Counter[str] = Counter()
    llm_lat: list[int] = []
    tools: dict[str, ToolStats] = defaultdict(ToolStats)
    violations = 0
    seen_mismatch: set[tuple[str, str]] = set()

    for e in evs:
        if e.type == "llm":
            llm[e.outcome] += 1
            llm_lat.append(e.latency_ms)
            continue
        if e.type == "invariant":
            violations += 1
            continue
        if e.type != "tool":
            continue
        st = tools[e.name]
        st.calls += 1
        st.latencies.append(e.latency_ms)
        if e.outcome == "denied":
            st.denied += 1
            for c in e.reason_codes:
                denials[c] += 1
        elif e.outcome == "error":
            st.errors += 1
        if e.outcome not in ("ok", "replay"):
            continue
        if e.name == "check_vehicle_eligibility":
            for c in e.reason_codes:
                if c in REJECTION_CODES:
                    rejections[c] += 1
        if e.name in ("run_document_validations", "attach_document"):
            for c in e.reason_codes:
                key = (e.case_id, c)
                if c in MISMATCH_CODES and key not in seen_mismatch:
                    seen_mismatch.add(key)  # un caso cuenta una vez por tipo
                    mismatches[MISMATCH_CODES[c]] += 1
        if e.name == "quote_second_key":
            keys.add(e.case_id)
        if e.stage_after == "ESCALATED":
            escalated.add(e.case_id)
        if e.stage_after == "READY_FOR_LENDER":
            ready.add(e.case_id)
    total = len(cases)
    return Metrics(
        cases=total,
        rejections_by_reason=dict(rejections),
        mismatches_by_type=dict(mismatches),
        key_quoted_cases=sorted(keys),
        escalated_cases=len(escalated),
        escalation_rate=len(escalated) / total if total else 0.0,
        ready_cases=len(ready),
        denials_by_code=dict(denials),
        tools=dict(tools),
        llm=dict(llm),
        llm_p95_ms=_p95(llm_lat),
        invariant_violations=violations,
    )


def format_report(m: Metrics) -> str:
    lines = [
        "REPORTE DE DECISIONES",
        f"  casos: {m.cases}   listos para financiera: {m.ready_cases}   "
        f"escalados: {m.escalated_cases} ({m.escalation_rate:.0%})",
        "",
        "Rechazos por motivo (auto):",
        *_kv(m.rejections_by_reason),
        "Mismatches documentales por tipo:",
        *_kv(m.mismatches_by_type),
        f"Casos con segunda llave cotizada: {len(m.key_quoted_cases)}"
        + (
            f" ({', '.join(m.key_quoted_cases)})" if m.key_quoted_cases else ""
        ),
        "Denegaciones por codigo:",
        *_kv(m.denials_by_code),
        "Tools (llamadas / negadas / errores / p95 ms):",
    ]
    for name, st in sorted(m.tools.items()):
        lines.append(
            f"  {name:28} {st.calls:4} {st.denied:4} "
            f"{st.errors:4} {st.p95_ms:5}"
        )
    lines.append(
        "LLM: "
        + (
            ", ".join(f"{k}={v}" for k, v in sorted(m.llm.items()))
            or "sin uso"
        )
        + f"   p95={m.llm_p95_ms} ms"
    )
    lines.append(f"Violaciones de invariantes: {m.invariant_violations}")
    return "\n".join(lines)


def _kv(d: dict[str, int]) -> list[str]:
    return [f"  {k}: {v}" for k, v in sorted(d.items())] or ["  (ninguno)"]
