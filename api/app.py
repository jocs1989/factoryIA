"""Entrada FastAPI: expone el agente y la consola del asesor.

Mismo ejecutor para ambos: el asesor es otro `principal` con otros scopes.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent.runner import TurnResult
from agent.runtime import Runtime, build_runtime
from agent.scenarios import load_scenarios
from agent.types import CustomerEvent, DocRef
from api.security import AttemptLimiter, RateLimiter, SessionStore
from config.settings import load_settings
from config.validation import ensure_valid
from observability.logging import (
    configure_logging,
    get_logger,
    log_fields,
    reset_correlation_id,
    set_correlation_id,
)
from ports import CaseExists
from tools.executor import ToolResult, ToolStatus
from tools.principals import Principal
from tools.session import IdentityError, Session

SESSION_TTL_S = 3600
MAX_VERIFY_FAILURES = 5
MESSAGES_PER_MINUTE = 30  # por sesion: protege el costo del LLM
MAX_BODY_BYTES = 64 * 1024  # nada legitimo de esta API pesa mas
_CORRELATION_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

log = get_logger("api")

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
    """Datos para abrir un caso; los aporta el canal, no el cliente."""

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
    """Verificacion de identidad: ultimos cuatro digitos del telefono."""

    phone_last4: str = Field(pattern=r"^\d{4}$")


class MessageIn(BaseModel):
    """Un mensaje del cliente, con sus documentos adjuntos (acotado)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(default="", max_length=2000)
    documents: list[DocRef] = Field(default_factory=list, max_length=10)


class ResolveIn(BaseModel):
    """Resolucion de un ticket por el asesor, con justificacion obligatoria."""

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
    """Crea la API.

    Arrancar valida la configuracion y se niega si es insegura.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        rt_ = runtime or build_runtime(load_settings())
        configure_logging(rt_.settings.log_level, rt_.settings.log_format)
        # Fail-fast: un ambiente inseguro o incompleto no arranca.
        ensure_valid(rt_.settings, rt_.principals)
        try:
            rt_.check_ready()
        except Exception as exc:
            # Mejor no arrancar (y que el orquestador reinicie) que servir
            # errores: p. ej. sin poder escribir la bitacora no se opera.
            raise RuntimeError(
                f"dependencia no lista al arrancar: {type(exc).__name__}"
            ) from None
        app.state.runtime = rt_
        app.state.sessions = SessionStore(SESSION_TTL_S)
        app.state.attempts = AttemptLimiter(MAX_VERIFY_FAILURES)
        app.state.limiter = RateLimiter(MESSAGES_PER_MINUTE, 60)
        log.info("api lista", extra=log_fields(env=rt_.settings.agent_env))
        yield

    app = FastAPI(title="Auto Equity Agent", lifespan=lifespan)

    @app.middleware("http")
    async def observe(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Correlacion, tope de cuerpo, cabeceras seguras y log."""
        sent = request.headers.get("x-correlation-id", "")
        cid = sent if _CORRELATION_OK.match(sent) else uuid.uuid4().hex[:16]
        token = set_correlation_id(cid)
        t0 = time.perf_counter()
        try:
            length = int(request.headers.get("content-length") or 0)
            if length > MAX_BODY_BYTES:
                response: Response = JSONResponse(
                    {"detail": "cuerpo demasiado grande"}, status_code=413
                )
            else:
                try:
                    response = await call_next(request)
                except Exception:
                    # Sin traza ni datos hacia el cliente; la traza (ya
                    # redactada) queda en el log con el id de correlacion.
                    log.exception("error no controlado")
                    response = JSONResponse(
                        {"detail": "error interno", "correlation_id": cid},
                        status_code=500,
                    )
            response.headers["X-Correlation-ID"] = cid
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            log.info(
                "peticion",
                extra=log_fields(
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    ms=int((time.perf_counter() - t0) * 1000),
                ),
            )
            return response
        finally:
            reset_correlation_id(token)

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
        store: SessionStore = request.app.state.sessions
        owner = store.get(x_session_token or "")
        if owner is None:
            raise HTTPException(401, "sesion invalida o vencida")
        if owner != case_id:
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

    @app.get("/ready")
    def ready(request: Request) -> dict[str, str]:
        """Readiness: el servicio puede atender (p. ej. Mongo responde)."""
        try:
            rt(request).check_ready()
        except Exception as exc:
            log.warning(
                "no esta listo", extra=log_fields(error=type(exc).__name__)
            )
            raise HTTPException(503, "dependencia no disponible") from None
        return {"status": "ready"}

    @app.get("/demo/scenarios")
    def demo_scenarios(request: Request) -> list[dict[str, Any]]:
        """Escenarios de demostracion para la interfaz de prueba.

        Son datos ficticios; solo se exponen donde `demo_endpoints` esta
        activo (mock y dev), nunca en prod.
        """
        if not rt(request).settings.demo_endpoints:
            raise HTTPException(404, "no disponible en este ambiente")
        return [s.model_dump(mode="json") for s in load_scenarios()]

    @app.post("/cases", status_code=201)
    def create_case(
        body: CaseCreate,
        request: Request,
        _: Principal = Depends(channel_principal),
    ) -> dict[str, str]:
        try:
            case = rt(request).create_case(body.model_dump(exclude_none=True))
        except CaseExists:
            raise HTTPException(409, "el caso ya existe") from None
        except ValidationError as exc:
            # Solo los nombres de los campos: nunca se devuelven los valores.
            fields = ", ".join(
                ".".join(map(str, e["loc"])) for e in exc.errors()
            )
            raise HTTPException(422, f"campos invalidos: {fields}") from None
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
        attempts: AttemptLimiter = request.app.state.attempts
        wait = attempts.retry_after(case_id)
        if wait:
            raise HTTPException(
                429,
                "demasiados intentos; vuelve a intentar mas tarde",
                headers={"Retry-After": str(wait)},
            )
        try:
            rt(request).verify(case_id, body.phone_last4)
        except IdentityError:
            attempts.record_failure(case_id)
            log.warning(
                "verificacion fallida", extra=log_fields(case_id=case_id)
            )
            # Mismo error exista o no el caso: no se revela cual fallo.
            raise HTTPException(403, "verificacion fallida") from None
        attempts.reset(case_id)
        store: SessionStore = request.app.state.sessions
        return {
            "session_token": store.create(case_id),
            "expires_in": SESSION_TTL_S,
        }

    @app.post("/conversations/{case_id}/messages")
    def message(
        case_id: str,
        body: MessageIn,
        request: Request,
        session: Session = Depends(session_for),
        _: Principal = Depends(channel_principal),
    ) -> TurnResult:
        limiter: RateLimiter = request.app.state.limiter
        if not limiter.allow(session.case_id):
            raise HTTPException(
                429,
                "demasiados mensajes; espera un momento",
                headers={"Retry-After": "60"},
            )
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
