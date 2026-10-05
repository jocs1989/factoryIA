"""Corre un turno de conversacion sobre el grafo."""

from __future__ import annotations

import uuid
from typing import Any

from langgraph.types import Command
from pydantic import BaseModel

from agent.graph import ESCALATED_TEXT, TERMINAL, GraphDeps, build_graph
from agent.types import CustomerEvent
from domain.case import Case, Stage
from ports import AuditEvent
from tools.session import Session


class TurnResult(BaseModel):
    messages: list[str]
    stage: str
    version: int
    outcome: str | None = None  # etapa terminal, si ya se alcanzo
    steps: int = 0
    awaiting_advisor: bool = False


class ConversationRunner:
    def __init__(self, deps: GraphDeps, checkpointer: Any) -> None:
        self._deps = deps
        self._graph = build_graph(deps, checkpointer)

    def _config(self, case_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": case_id}}

    def _load(self, case_id: str) -> Case:
        case = self._deps.repo.get(case_id)
        if case is None:
            raise LookupError(case_id)
        return case

    def turn(self, session: Session, event: CustomerEvent) -> TurnResult:
        case = self._load(session.case_id)
        if case.stage is Stage.ESCALATED:
            # Un asesor ya tiene el caso: no se corre el agente.
            return self._result(case, [ESCALATED_TEXT], 0, awaiting=True)
        text = event.text.strip()
        state = {
            "case_id": session.case_id,
            "run_id": uuid.uuid4().hex[:12],
            "event": event.model_dump(mode="json"),
            "pending_docs": [d.model_dump() for d in event.documents],
            "last": None,
            "replies": [],
            "history": [{"role": "customer", "text": text}] if text else [],
            "steps": 0,
            "violations": 0,
            "waiting": False,
        }
        return self._finish(
            session.case_id,
            self._graph.invoke(state, self._config(session.case_id)),
        )

    def resume_after_advisor(self, session: Session) -> TurnResult:
        """El asesor ya resolvio el ticket: el agente continua."""
        config = self._config(session.case_id)
        snapshot = self._graph.get_state(config)
        since = 0
        if snapshot.next:  # pausado en await_advisor
            # Lo anterior ya se entrego al cliente antes de la pausa.
            since = int(snapshot.values.get("delivered", 0))
            out = self._graph.invoke(
                Command(resume={"resolved": True}), config
            )
        else:  # p. ej. reinicio del proceso: arranque limpio
            out = self._graph.invoke(
                {
                    "case_id": session.case_id,
                    "run_id": uuid.uuid4().hex[:12],
                    "event": None,
                    "pending_docs": [],
                    "last": None,
                    "replies": [],
                    "steps": 0,
                    "violations": 0,
                    "waiting": False,
                },
                config,
            )
        return self._finish(session.case_id, out, since)

    def _finish(
        self, case_id: str, out: dict[str, Any], since: int = 0
    ) -> TurnResult:
        case = self._load(case_id)
        result = self._result(
            case,
            list(out.get("replies", []))[since:],
            int(out.get("steps", 0)),
            awaiting="__interrupt__" in out,
        )
        self._check_invariants(case, out, result)
        return result

    @staticmethod
    def _result(
        case: Case, messages: list[str], steps: int, awaiting: bool
    ) -> TurnResult:
        return TurnResult(
            messages=messages,
            stage=case.stage.value,
            version=case.version,
            outcome=case.stage.value if case.stage in TERMINAL else None,
            steps=steps,
            awaiting_advisor=awaiting or case.stage is Stage.ESCALATED,
        )

    def _check_invariants(
        self, case: Case, out: dict[str, Any], result: TurnResult
    ) -> None:
        """Revisa coherencias al cerrar cada turno; deja rastro si fallan."""
        problems: list[str] = []
        if case.stage is Stage.READY_FOR_LENDER and not case.data.get(
            "readiness"
        ):
            problems.append("READY_WITHOUT_GATE_EVIDENCE")
        if result.steps > self._deps.max_steps + 1:
            problems.append("STEP_BUDGET_EXCEEDED")
        if any(m[:1] == "_" for m in result.messages):
            problems.append("INTERNAL_KEY_IN_REPLY")
        for code in problems:
            self._deps.audit.record(
                AuditEvent(
                    run_id=str(out.get("run_id", "")),
                    case_id=case.case_id,
                    principal="runner",
                    type="invariant",
                    name="turn_close",
                    outcome="violation",
                    reason_codes=(code,),
                    ts=self._deps.clock(),
                )
            )
