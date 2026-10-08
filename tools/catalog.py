"""Registro del catalogo de tools.

Cada tool vive en `tools/handlers/<etapa>.py` con su contrato; aqui solo se
registran con su efecto, riesgo, permiso y etapas permitidas.
"""

from __future__ import annotations

from collections.abc import Mapping

from tools.handlers.case_edit import UpdateIn, UpdateOut, update_case
from tools.handlers.common import ALL_STAGES, CaseOnlyIn, S
from tools.handlers.documents import (
    AttachIn,
    AttachOut,
    CorrectionOut,
    ReadDocIn,
    ReadDocOut,
    ValidationOut,
    attach_document,
    read_document,
    request_customer_correction,
    run_document_validations,
)
from tools.handlers.eligibility import (
    CheckEligibilityIn,
    EligibilityOut,
    check_vehicle_eligibility,
)
from tools.handlers.escalation import (
    EscalateIn,
    EscalateOut,
    ResolveIn,
    ResolveOut,
    escalate_to_human,
    resolve_escalation,
)
from tools.handlers.gate import ReadyOut, mark_ready_for_lender
from tools.handlers.profiling import (
    ConsentIn,
    ConsentOut,
    ProfileOut,
    QuoteOut,
    query_credit_bureau,
    quote_second_key,
    record_bureau_consent,
)
from tools.handlers.simulation import (
    BuildSimIn,
    ChoiceIn,
    ChoiceOut,
    SimulationOut,
    build_simulation_tool,
    record_customer_choice,
)
from tools.handlers.snapshot import (
    SnapshotOut,
    get_case_snapshot,
    project_case,
)
from tools.spec import Effect, Risk, ToolSpec

__all__ = ["build_catalog", "project_case"]

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
