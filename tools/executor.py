"""Ejecutor unico de tools: agente y asesor pasan por el mismo pipeline.

1 entrada valida  2 scope  3 caso ligado a la sesion  4 idempotencia
5 etapa permitida  6 ejecutar y validar salida  7 persistir con version
8 bitacora (siempre, tambien en denegaciones).

La idempotencia va antes de la etapa a proposito: el reintento de una
escritura que ya movio el caso llega con la etapa nueva, y debe recibir
el resultado guardado, no una denegacion. Reintentar nunca salta los
pasos 1 a 3. El resultado se reconoce solo si el caso sigue en la version
previa o posterior a esa llamada; si ya avanzo mas, se ejecuta de nuevo.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ValidationError

from domain.case import StaleVersion
from domain.hashing import canonical_hash
from ports import AuditEvent, NotFoundError, ProviderError
from tools.deps import Deps
from tools.principals import Principal
from tools.session import Session
from tools.spec import Outcome, ToolContext, ToolRefusal, ToolSpec


class ToolStatus(StrEnum):
    """Resultado de una llamada: ok, denegada, invalida o con error."""

    OK = "ok"
    DENIED = "denied"
    INVALID = "invalid"
    ERROR = "error"


class ToolResult(BaseModel):
    """Resultado de una tool, tambien cuando se niega."""

    status: ToolStatus
    tool: str
    output: dict[str, Any] | None = None
    code: str | None = None
    message: str | None = None
    reason_codes: tuple[str, ...] = ()
    replayed: bool = False
    stage: str | None = None
    version: int | None = None

    @property
    def ok(self) -> bool:
        """True si la tool se ejecuto."""
        return self.status is ToolStatus.OK


class Executor:
    """Unico camino para ejecutar tools, tanto del agente como del asesor."""

    def __init__(self, deps: Deps, catalog: Mapping[str, ToolSpec]) -> None:
        self._deps = deps
        self._catalog = catalog

    @property
    def catalog(self) -> Mapping[str, ToolSpec]:
        """Tools registradas."""
        return self._catalog

    def call(
        self,
        principal: Principal,
        session: Session,
        tool_name: str,
        args: Mapping[str, Any],
        *,
        run_id: str = "run",
    ) -> ToolResult:
        """Ejecuta una tool.

        Valida entrada, permiso, caso, idempotencia y etapa, y siempre audita.
        """
        t0 = time.perf_counter()
        spec = self._catalog.get(tool_name)
        inputs_hash = canonical_hash(dict(args))
        rule_version: str | None = None
        outcome_codes: tuple[str, ...] = ()

        def finish(result: ToolResult) -> ToolResult:
            label = "replay" if result.replayed else result.status.value
            self._deps.audit.record(
                AuditEvent(
                    run_id=run_id,
                    case_id=session.case_id,
                    principal=principal.id,
                    type="tool",
                    name=tool_name,
                    rule_version=rule_version,
                    inputs_hash=inputs_hash,
                    outcome=label,
                    reason_codes=result.reason_codes
                    or ((result.code,) if result.code else outcome_codes),
                    latency_ms=int((time.perf_counter() - t0) * 1000),
                    stage_after=result.stage,
                    ts=self._deps.clock(),
                )
            )
            return result

        def refuse(
            status: ToolStatus,
            code: str,
            message: str,
            reasons: tuple[str, ...] = (),
        ) -> ToolResult:
            return finish(
                ToolResult(
                    status=status,
                    tool=tool_name,
                    code=code,
                    message=message,
                    reason_codes=reasons or (code,),
                )
            )

        if spec is None:  # deny-by-default
            return refuse(ToolStatus.DENIED, "UNKNOWN_TOOL", "tool no existe")

        # 1. entrada valida
        try:
            inp = spec.input_model.model_validate(dict(args))
        except ValidationError as exc:
            fields = ", ".join(
                ".".join(map(str, e["loc"])) for e in exc.errors()
            )
            return refuse(
                ToolStatus.INVALID, "INVALID_INPUT", f"argumentos: {fields}"
            )
        # 2. scope (minimo privilegio)
        if spec.required_scope not in principal.scopes:
            return refuse(
                ToolStatus.DENIED,
                "SCOPE_DENIED",
                f"falta el permiso {spec.required_scope}",
            )
        # 3. el caso debe ser el ligado a la sesion
        if inp.case_id != session.case_id:
            return refuse(
                ToolStatus.DENIED,
                "CASE_MISMATCH",
                "el caso no corresponde a la sesion",
            )
        case = self._deps.repo.get(inp.case_id)
        if case is None:
            return refuse(
                ToolStatus.DENIED, "CASE_NOT_FOUND", "caso no existe"
            )
        # 4. idempotencia (ventana de versiones, ver docstring)
        key = ""
        if spec.idempotent:
            key = canonical_hash(
                {
                    "case": case.case_id,
                    "tool": spec.name,
                    "args": inp.model_dump(
                        mode="json", exclude={"expected_version"}
                    ),
                }
            )
            stored = self._deps.idempotency.get(key)
            if stored is not None and case.version in (
                stored["before"],
                stored["after"],
            ):
                return finish(
                    ToolResult.model_validate(stored["result"]).model_copy(
                        update={"replayed": True}
                    )
                )
        # 5. etapa permitida (+ version esperada si el llamador la trae)
        if case.stage not in spec.stages:
            return refuse(
                ToolStatus.DENIED,
                "STAGE_NOT_ALLOWED",
                f"{spec.name} no se permite en {case.stage.value}",
            )
        if (
            inp.expected_version is not None
            and inp.expected_version != case.version
        ):
            return refuse(
                ToolStatus.DENIED,
                "STALE_VERSION",
                "el caso cambio; relee el estado",
            )
        # 6. ejecutar y validar salida
        ctx = ToolContext(case=case, principal=principal, deps=self._deps)
        try:
            outcome: Outcome = spec.handler(ctx, inp)
            output = spec.output_model.model_validate(
                outcome.output.model_dump()
            )
        except ToolRefusal as exc:
            return refuse(
                ToolStatus.DENIED, exc.code, exc.message, exc.reason_codes
            )
        except NotFoundError as exc:
            return refuse(ToolStatus.ERROR, "NOT_FOUND", str(exc))
        except ProviderError as exc:
            code = (
                "PROVIDER_UNAVAILABLE" if exc.retryable else "PROVIDER_ERROR"
            )
            return refuse(ToolStatus.ERROR, code, str(exc))
        except ValidationError:
            return refuse(
                ToolStatus.ERROR, "INVALID_OUTPUT", "salida fuera de contrato"
            )
        rule_version = outcome.rule_version
        outcome_codes = outcome.reason_codes
        # 7. persistir con control optimista de version
        new_case = outcome.case
        if new_case is not None:
            try:
                self._deps.repo.save(new_case, expected_version=case.version)
            except StaleVersion:
                return refuse(
                    ToolStatus.DENIED,
                    "STALE_VERSION",
                    "otro actor modifico el caso; reintenta con el estado "
                    "fresco",
                )
            for effect in outcome.after_commit:
                try:
                    effect()
                except Exception:  # el caso ya se guardo; se deja rastro
                    self._deps.audit.record(
                        AuditEvent(
                            run_id=run_id,
                            case_id=case.case_id,
                            principal=principal.id,
                            type="tool",
                            name=tool_name,
                            outcome="after_commit_failed",
                            reason_codes=("AFTER_COMMIT_FAILED",),
                            ts=self._deps.clock(),
                        )
                    )
        final = new_case or case
        result = ToolResult(
            status=ToolStatus.OK,
            tool=spec.name,
            output=output.model_dump(mode="json"),
            reason_codes=outcome.reason_codes,
            stage=final.stage.value,
            version=final.version,
        )
        if spec.idempotent:
            self._deps.idempotency.put(
                key,
                {
                    "result": result.model_dump(mode="json"),
                    "before": case.version,
                    "after": final.version,
                },
            )
        return finish(result)
