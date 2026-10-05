"""Politica con LLM. El modelo PROPONE una accion; el ejecutor la valida.

Si el modelo falla o devuelve algo invalido, la decision cae a la politica
por reglas (el caso no se pierde). Tras `max_failures` fallos seguidos de
un caso, el circuito se abre y ese caso sigue por reglas.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.types import Action, Policy, Reply, StageView, ToolCall
from ports import AuditEvent, AuditPort, LLMError, LLMPort, LLMRequest, Message

PROMPTS = Path(__file__).parent / "prompts"
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class ActionError(ValueError):
    """La respuesta del modelo no es una accion valida."""


def load_prompt(stage: str) -> str:
    system = (PROMPTS / "system.md").read_text(encoding="utf-8")
    extra = PROMPTS / f"{stage}.md"
    if extra.exists():
        return system + "\n" + extra.read_text(encoding="utf-8")
    return system


def build_request(view: StageView) -> LLMRequest:
    last = None
    if view.last is not None:
        last = {
            "tool": view.last.tool,
            "status": view.last.status.value,
            "code": view.last.code,
            "message": view.last.message,
            "output": view.last.output,
        }
    context = {
        "stage": view.stage.value,
        "case": view.case,
        "last_result": last,
        "pending_documents": [d.model_dump() for d in view.pending_docs],
        "tools": [t.llm_schema() for t in view.tools],
        "history": list(view.history),
    }
    text = view.event.text if view.event else ""
    # El texto del cliente va delimitado y sin poder cerrar su propio bloque.
    safe = text.replace("</customer_message>", "")
    user = (
        json.dumps(context, ensure_ascii=False, default=str)
        + "\n<customer_message>\n"
        + safe
        + "\n</customer_message>"
    )
    return LLMRequest(
        system=load_prompt(view.stage.value),
        messages=(Message("user", user),),
        json_mode=True,
        temperature=0.0,
        max_tokens=600,
    )


def parse_action(text: str, view: StageView) -> Action:
    try:
        raw: Any = json.loads(_FENCE.sub("", text.strip()))
    except ValueError as exc:
        raise ActionError("no es JSON") from exc
    if not isinstance(raw, dict):
        raise ActionError("se esperaba un objeto")
    kind = raw.get("action")
    if kind == "reply":
        said = raw.get("text")
        if not isinstance(said, str) or not said.strip():
            raise ActionError("reply sin texto")
        return Reply(text=said.strip()[:1000])
    if kind == "tool":
        name = raw.get("tool")
        allowed = {t.name for t in view.tools}
        if name not in allowed:
            raise ActionError(f"tool fuera de la lista blanca: {name!r}")
        args = raw.get("args", {})
        if not isinstance(args, dict):
            raise ActionError("args debe ser un objeto")
        # El caso lo fija el sistema, nunca el modelo.
        args = {
            k: v
            for k, v in args.items()
            if k not in ("case_id", "expected_version")
        }
        return ToolCall(tool=name, args=args)
    raise ActionError(f"accion desconocida: {kind!r}")


class LLMPolicy(Policy):
    name = "llm"

    def __init__(
        self,
        llm: LLMPort,
        fallback: Policy,
        audit: AuditPort | None = None,
        *,
        max_failures: int = 3,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._llm = llm
        self._fallback = fallback
        self._audit = audit
        self._max = max_failures
        self._clock = clock
        self._failures: dict[str, int] = {}
        self.degraded: set[str] = set()

    def next_action(self, view: StageView) -> Action:
        if self._failures.get(view.case_id, 0) >= self._max:
            self._note(view, "circuit_open", 0)
            self.degraded.add(view.case_id)
            return self._fallback.next_action(view)
        t0 = time.perf_counter()
        try:
            resp = self._llm.complete(build_request(view))
            action = parse_action(resp.text, view)
        except (LLMError, ActionError) as exc:
            self._failures[view.case_id] = (
                self._failures.get(view.case_id, 0) + 1
            )
            label = "error" if isinstance(exc, LLMError) else "invalid"
            self._note(view, label, _ms(t0))
            self.degraded.add(view.case_id)
            return self._fallback.next_action(view)
        self._failures[view.case_id] = 0
        self._note(view, "ok", _ms(t0))
        return action

    def _note(self, view: StageView, outcome: str, ms: int) -> None:
        if self._audit is None:
            return
        self._audit.record(
            AuditEvent(
                run_id=view.run_id,
                case_id=view.case_id,
                principal="policy-llm",
                type="llm",
                name=self._llm.name,
                outcome=outcome,
                reason_codes=()
                if outcome == "ok"
                else ("LLM_FALLBACK_TO_RULES",),
                latency_ms=ms,
                ts=self._clock(),
            )
        )


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)
