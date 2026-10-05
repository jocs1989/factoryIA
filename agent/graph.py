"""Grafo de LangGraph: controlador de etapas determinista.

El LLM (o las reglas) solo elige la siguiente accion DENTRO de una etapa y
con lista blanca de tools. Que etapa sigue lo decide el dominio: el grafo
relee el caso persistido tras cada accion y enruta por su `stage`.
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent.types import (
    CustomerEvent,
    DocRef,
    Policy,
    Reply,
    StageView,
    ToolCall,
)
from domain.case import Stage
from ports import AuditEvent, AuditPort, CaseRepositoryPort
from tools.catalog import project_case
from tools.executor import Executor, ToolResult, ToolStatus
from tools.principals import Principal
from tools.session import Session

S = Stage

# Lista blanca por etapa: lo unico que el agente puede intentar.
STAGE_TOOLS: dict[Stage, frozenset[str]] = {
    S.ELIGIBILITY: frozenset(
        {"check_vehicle_eligibility", "update_case", "get_case_snapshot"}
    ),
    S.PROFILING: frozenset(
        {
            "quote_second_key",
            "record_bureau_consent",
            "query_credit_bureau",
            "update_case",
            "escalate_to_human",
            "get_case_snapshot",
        }
    ),
    S.SIMULATION: frozenset(
        {
            "build_simulation",
            "record_customer_choice",
            "update_case",
            "get_case_snapshot",
        }
    ),
    S.DOCUMENTS: frozenset(
        {
            "attach_document",
            "read_document",
            "run_document_validations",
            "mark_ready_for_lender",
            "escalate_to_human",
            "get_case_snapshot",
        }
    ),
    S.NEEDS_CORRECTION: frozenset(
        {
            "attach_document",
            "request_customer_correction",
            "read_document",
            "get_case_snapshot",
        }
    ),
}
TERMINAL = frozenset({S.REJECTED, S.DECLINED, S.READY_FOR_LENDER})

ESCALATED_TEXT = (
    "Un asesor revisara tu caso y te contactara. Gracias por tu paciencia."
)
FINAL_TEXT = {
    S.READY_FOR_LENDER: (
        "¡Listo! Tu expediente esta completo y fue enviado a la financiera."
    ),
    S.DECLINED: (
        "Por ahora tu perfil crediticio no cumple las condiciones para "
        "este credito."
    ),
}
REJECT_TEXT = {
    "VEHICLE_NOT_OWNED": (
        "No podemos continuar: el auto no esta a tu nombre."
    ),
    "VEHICLE_ENCUMBERED": (
        "No podemos continuar: el auto tiene adeudos o gravamenes."
    ),
}


class AgentState(TypedDict, total=False):
    case_id: str
    run_id: str
    event: dict[str, Any] | None
    pending_docs: list[dict[str, str]]
    last: dict[str, Any] | None
    replies: list[str]
    history: Annotated[list[dict[str, str]], operator.add]
    steps: int
    violations: int
    waiting: bool
    stage: str
    delivered: int  # respuestas ya entregadas al cliente (pausa)


@dataclass(frozen=True)
class GraphDeps:
    executor: Executor
    repo: CaseRepositoryPort
    audit: AuditPort
    policy: Policy
    principal: Principal
    clock: Callable[[], Any]
    max_steps: int = 12
    max_violations: int = 3


def _final_text(case_data: dict[str, Any], stage: Stage) -> str:
    if stage is S.REJECTED:
        codes = (case_data.get("eligibility") or {}).get("reason_codes") or []
        return REJECT_TEXT.get(
            codes[0] if codes else "", "No podemos continuar con tu solicitud."
        )
    return FINAL_TEXT[stage]


def build_graph(deps: GraphDeps, checkpointer: Any = None) -> Any:
    def case_stage(state: AgentState) -> Stage:
        case = deps.repo.get(state["case_id"])
        if case is None:
            raise RuntimeError("caso inexistente")
        return case.stage

    def load(state: AgentState) -> dict[str, Any]:
        return {"stage": case_stage(state).value}

    def route(state: AgentState) -> str:
        stage = Stage(state["stage"])
        if stage in TERMINAL:
            return "finish"
        if stage is S.ESCALATED:
            return "announce"
        if (
            state.get("steps", 0) >= deps.max_steps
            or state.get("violations", 0) >= deps.max_violations
        ):
            return "limit"
        return "act"

    def act(state: AgentState) -> dict[str, Any]:
        case_id = state["case_id"]
        case = deps.repo.get(case_id)
        assert case is not None
        stage = case.stage
        tools = tuple(
            spec
            for name, spec in deps.executor.catalog.items()
            if name in STAGE_TOOLS[stage]
        )
        event = state.get("event")
        pending = tuple(DocRef(**d) for d in state.get("pending_docs", []))
        last = state.get("last")
        view = StageView(
            case_id=case_id,
            run_id=state["run_id"],
            stage=stage,
            case=project_case(case),
            event=CustomerEvent.model_validate(event) if event else None,
            pending_docs=pending,
            last=ToolResult.model_validate(last) if last else None,
            tools=tools,
            history=tuple(state.get("history", [])[-6:]),
        )
        action = deps.policy.next_action(view)
        steps = state.get("steps", 0) + 1
        if isinstance(action, Reply):
            return {
                "replies": [*state.get("replies", []), action.text],
                "history": [{"role": "agent", "text": action.text}],
                "event": None,
                "waiting": True,
                "steps": steps,
            }
        assert isinstance(action, ToolCall)
        violations = state.get("violations", 0)
        if action.tool not in STAGE_TOOLS[stage]:
            result = ToolResult(
                status=ToolStatus.DENIED,
                tool=action.tool,
                code="TOOL_NOT_WHITELISTED",
                message=f"{action.tool} no esta permitida en {stage.value}",
                reason_codes=("TOOL_NOT_WHITELISTED",),
            )
            deps.audit.record(
                AuditEvent(
                    run_id=state["run_id"],
                    case_id=case_id,
                    principal=deps.principal.id,
                    type="tool",
                    name=action.tool,
                    outcome="denied",
                    reason_codes=("TOOL_NOT_WHITELISTED",),
                    ts=deps.clock(),
                )
            )
            violations += 1
        else:
            result = deps.executor.call(
                deps.principal,
                Session(case_id),
                action.tool,
                {**action.args, "case_id": case_id},
                run_id=state["run_id"],
            )
        remaining = list(state.get("pending_docs", []))
        if action.tool == "attach_document":
            doc_id = action.args.get("doc_id")
            idx = next(
                (i for i, d in enumerate(remaining) if d["doc_id"] == doc_id),
                0,
            )
            if remaining:
                remaining.pop(idx)
        return {
            "last": result.model_dump(mode="json"),
            "event": None,
            "pending_docs": remaining,
            "steps": steps,
            "violations": violations,
        }

    def after_act(state: AgentState) -> str:
        return END if state.get("waiting") else "load"

    def limit(state: AgentState) -> dict[str, Any]:
        stage = Stage(state["stage"])
        if stage in (S.PROFILING, S.DOCUMENTS):
            deps.executor.call(
                deps.principal,
                Session(state["case_id"]),
                "escalate_to_human",
                {
                    "case_id": state["case_id"],
                    "reason_code": "AGENT_LIMIT",
                    "summary": "El agente alcanzo su limite de pasos "
                    "o intentos invalidos en este turno",
                },
                run_id=state["run_id"],
            )
            return {"steps": 0, "violations": 0, "waiting": False}
        text = "Estamos revisando tu caso; te contactaremos pronto."
        return {
            "replies": [*state.get("replies", []), text],
            "history": [{"role": "agent", "text": text}],
            "waiting": True,
        }

    def after_limit(state: AgentState) -> str:
        return END if state.get("waiting") else "load"

    def announce(state: AgentState) -> dict[str, Any]:
        replies = list(state.get("replies", []))
        if ESCALATED_TEXT not in replies:
            replies.append(ESCALATED_TEXT)
        return {
            "replies": replies,
            "delivered": len(replies),
            "history": [{"role": "agent", "text": ESCALATED_TEXT}],
        }

    def await_advisor(state: AgentState) -> dict[str, Any]:
        # Pausa durable: el checkpointer guarda el estado hasta que el
        # asesor resuelva y el runner reanude.
        interrupt({"case_id": state["case_id"], "reason": "advisor_review"})
        return {"waiting": False}

    def finish(state: AgentState) -> dict[str, Any]:
        case = deps.repo.get(state["case_id"])
        assert case is not None
        text = _final_text(case.data, case.stage)
        replies = list(state.get("replies", []))
        if text not in replies:
            replies.append(text)
        return {
            "replies": replies,
            "history": [{"role": "agent", "text": text}],
            "waiting": True,
        }

    g: StateGraph[Any] = StateGraph(AgentState)
    g.add_node("load", load)
    g.add_node("act", act)
    g.add_node("limit", limit)
    g.add_node("announce", announce)
    g.add_node("await_advisor", await_advisor)
    g.add_node("finish", finish)
    g.add_edge(START, "load")
    g.add_conditional_edges(
        "load",
        route,
        {
            "act": "act",
            "finish": "finish",
            "announce": "announce",
            "limit": "limit",
        },
    )
    g.add_conditional_edges("act", after_act, {END: END, "load": "load"})
    g.add_conditional_edges("limit", after_limit, {END: END, "load": "load"})
    g.add_edge("announce", "await_advisor")
    g.add_edge("await_advisor", "load")
    g.add_edge("finish", END)
    return g.compile(checkpointer=checkpointer)
