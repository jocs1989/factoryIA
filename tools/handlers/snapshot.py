"""Proyeccion compacta del caso: lo unico que ve el agente."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from domain.case import Case
from domain.doc_review import (
    REQUIRED_DOCS,
)
from tools.handlers.common import (
    CaseOnlyIn,
)
from tools.spec import (
    Outcome,
    ToolContext,
)


class SnapshotOut(BaseModel):
    """Resumen del caso para el agente."""

    stage: str
    version: int
    projection: dict[str, Any]


def project_case(case: Case) -> dict[str, Any]:
    """Proyeccion compacta y sin datos personales.

    Lo unico que ve el modelo.
    """
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


def get_case_snapshot(ctx: ToolContext, inp: CaseOnlyIn) -> Outcome:
    """Devuelve la etapa, la version y la proyeccion del caso."""
    c = ctx.case
    return Outcome(
        SnapshotOut(
            stage=c.stage.value, version=c.version, projection=project_case(c)
        )
    )
