"""Entrada FastAPI: expone el agente y la consola del asesor.

Mismo ejecutor para ambos: el asesor es otro `principal` con otros scopes.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from agent.runner import TurnResult
from agent.runtime import Runtime, build_runtime
from agent.types import CustomerEvent, DocRef
from config.settings import load_settings
from tools.executor import ToolResult, ToolStatus
from tools.principals import Principal
from tools.session import IdentityError, Session

SESSION_TTL_S = 3600
MAX_VERIFY_FAILURES = 5

_STATUS = {
    "SCOPE_DENIED": 403,
    "CASE_MISMATCH": 403,
    "CASE_NOT_FOUND": 404,
    "TICKET_NOT_FOUND": 404,
    "STALE_VERSION": 409,
    "STAGE_NOT_ALLOWED": 409,
    "TICKET_CLOSED": 409,
}


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str | None = None
    customer_id: str
    vehicle_id: str
    customer_name: str
    declared_income: str
    requested_amount: str
    employment_type: str = "salaried"
    address_street: str
    address_postal_code: str = Field(pattern=r"^\d{5}$")
    phone_last4: str = Field(pattern=r"^\d{4}$")


class VerifyIn(BaseModel):
    phone_last4: str = Field(pattern=r"^\d{4}$")


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="", max_length=2000)
    documents: list[DocRef] = Field(default_factory=list, max_length=10)


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    decision: str
    justification: str
    override_codes: list[str] = Field(default_factory=list)


def _http_error(result: ToolResult) -> HTTPException:
    if result.status is ToolStatus.INVALID:
        code = 422
    elif result.status is ToolStatus.ERROR:
        code = 502 if result.code and "PROVIDER" in result.code else 500
    else:
        code = _STATUS.get(result.code or "", 403)
    return HTTPException(
        code, {"code": result.code, "message": result.message}
    )


def create_app(runtime: Runtime | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.runtime = runtime or build_runtime(load_settings())
        app.state.sessions = {}  # token -> (case_id, expira)
        app.state.failures = {}  # case_id -> intentos fallidos
        yield

    app = FastAPI(title="Auto Equity Agent", lifespan=lifespan)

    def rt(request: Request) -> Runtime:
        runtime_: Runtime = request.app.state.runtime
        return runtime_

    def channel_principal(
        request: Request,
        x_api_key: str | None = Header(default=None),
    ) -> Principal:
        """Quien llama a los endpoints de cliente (canal o gateway)."""
        runtime_ = rt(request)
        found = runtime_.principals.resolve(x_api_key)
        if found is not None and "case:write" in found.scopes:
            return found
        if runtime_.settings.allow_anonymous_principal:
            return runtime_.principals.get("customer-agent")
        raise HTTPException(401, "falta X-API-Key valida")

    def advisor(
        request: Request,
        x_api_key: str | None = Header(default=None),
    ) -> Principal:
        """El asesor SIEMPRE se autentica, tambien en `mock`."""
        found = rt(request).principals.resolve(x_api_key)
        if found is None or "ticket:resolve" not in found.scopes:
            raise HTTPException(401, "credencial de asesor requerida")
        return found

    def session_for(
        request: Request,
        case_id: str,
        x_session_token: str | None = Header(default=None),
    ) -> Session:
        entry = request.app.state.sessions.get(x_session_token or "")
        if entry is None or entry[1] < time.time():
            raise HTTPException(401, "sesion invalida o vencida")
        if entry[0] != case_id:
            raise HTTPException(403, "la sesion no corresponde al caso")
        return Session(case_id=case_id)

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        r = rt(request)
        return {
            "status": "ok",
            "env": r.settings.agent_env,
            "policy": r.policy.name,
            "repo": r.settings.repo_backend,
        }

    @app.post("/cases", status_code=201)
    def create_case(
        body: CaseCreate,
        request: Request,
        _: Principal = Depends(channel_principal),
    ) -> dict[str, str]:
        try:
            case = rt(request).create_case(body.model_dump(exclude_none=True))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"case_id": case.case_id, "stage": case.stage.value}

    @app.post("/cases/{case_id}/verify")
    def verify(
        case_id: str,
        body: VerifyIn,
        request: Request,
        _: Principal = Depends(channel_principal),
    ) -> dict[str, Any]:
        failures: dict[str, int] = request.app.state.failures
        if failures.get(case_id, 0) >= MAX_VERIFY_FAILURES:
            raise HTTPException(429, "demasiados intentos; contacta a soporte")
        try:
            rt(request).verify(case_id, body.phone_last4)
        except IdentityError:
            failures[case_id] = failures.get(case_id, 0) + 1
            # Mismo error exista o no el caso: no se revela cual fallo.
            raise HTTPException(403, "verificacion fallida") from None
        failures.pop(case_id, None)
        token = secrets.token_urlsafe(24)
        request.app.state.sessions[token] = (
            case_id,
            time.time() + SESSION_TTL_S,
        )
        return {"session_token": token, "expires_in": SESSION_TTL_S}

    @app.post("/conversations/{case_id}/messages")
    def message(
        case_id: str,
        body: MessageIn,
        request: Request,
        session: Session = Depends(session_for),
        _: Principal = Depends(channel_principal),
    ) -> TurnResult:
        event = CustomerEvent(text=body.text, documents=tuple(body.documents))
        return rt(request).runner.turn(session, event)

    @app.get("/advisor/inbox")
    def inbox(
        request: Request, _: Principal = Depends(advisor)
    ) -> list[dict[str, Any]]:
        return [
            t.model_dump(mode="json")
            for t in rt(request).deps.inbox.list_open()
        ]

    @app.get("/advisor/cases/{case_id}")
    def show_case(
        case_id: str,
        request: Request,
        who: Principal = Depends(advisor),
    ) -> dict[str, Any]:
        r = rt(request)
        res = r.executor.call(
            who, Session(case_id), "get_case_snapshot", {"case_id": case_id}
        )
        if not res.ok:
            raise _http_error(res)
        return {
            "snapshot": res.output,
            "timeline": [
                e.model_dump(mode="json")
                for e in r.deps.audit.list_events(case_id)
            ],
        }

    @app.post("/advisor/tickets/{ticket_id}/resolve")
    def resolve(
        ticket_id: str,
        body: ResolveIn,
        request: Request,
        who: Principal = Depends(advisor),
    ) -> dict[str, Any]:
        r = rt(request)
        session = Session(body.case_id)
        res = r.executor.call(
            who,
            session,
            "resolve_escalation",
            {
                "case_id": body.case_id,
                "ticket_id": ticket_id,
                "decision": body.decision,
                "justification": body.justification,
                "override_codes": body.override_codes,
            },
        )
        if not res.ok:
            raise _http_error(res)
        turn = r.runner.resume_after_advisor(session)
        for text in turn.messages:  # el cliente se entera por el canal
            try:
                r.deps.channel.send(body.case_id, text)
            except Exception:  # noqa: BLE001 - el caso ya avanzo
                break
        return {
            "result": res.model_dump(mode="json"),
            "agent": turn.model_dump(mode="json"),
        }

    return app


app = create_app()
