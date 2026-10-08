"""Contrato de una tool."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from domain.case import Case, Stage
from tools.deps import Deps
from tools.principals import Principal


class Effect(StrEnum):
    """Efecto de una tool sobre el sistema."""

    READ = "read"
    COMPUTE = "compute"
    WRITE = "write"
    EXTERNAL_READ = "external_read"


class Risk(StrEnum):
    """Riesgo de una tool; las de riesgo alto tienen controles extra."""

    LOW = "low"
    HIGH = "high"


class ToolInput(BaseModel):
    """Base de las entradas: rechaza campos no declarados."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    expected_version: int | None = None


class ToolRefusal(Exception):
    """El dominio se niega: no es un error, es una decision."""

    def __init__(
        self,
        code: str,
        message: str,
        reason_codes: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.reason_codes = reason_codes or (code,)


@dataclass(frozen=True)
class ToolContext:
    """Lo que recibe un handler: el caso, quien llama y las dependencias."""

    case: Case
    principal: Principal
    deps: Deps


@dataclass
class Outcome:
    """Resultado de un handler.

    Salida, caso nuevo a persistir y efectos tras el commit.
    """

    output: BaseModel
    case: Case | None = None  # se persiste con version optimista
    rule_version: str | None = None
    reason_codes: tuple[str, ...] = ()
    after_commit: tuple[Callable[[], None], ...] = field(default=())


Handler = Callable[[ToolContext, Any], Outcome]


@dataclass(frozen=True)
class ToolSpec:
    """Contrato de una tool.

    Modelos, permiso, etapas, riesgo e idempotencia.
    """

    name: str
    description: str
    input_model: type[ToolInput]
    output_model: type[BaseModel]
    effect: Effect
    risk: Risk
    required_scope: str
    stages: frozenset[Stage]
    handler: Handler
    idempotent: bool = False
    sensitive: bool = False

    def llm_schema(self) -> dict[str, Any]:
        """Lo que ve el modelo: nombre, descripcion y argumentos."""
        schema = self.input_model.model_json_schema()
        props = {
            k: v
            for k, v in schema.get("properties", {}).items()
            if k not in ("case_id", "expected_version")
        }
        return {
            "name": self.name,
            "description": self.description,
            "arguments": props,
            "required": [
                r for r in schema.get("required", []) if r != "case_id"
            ],
        }
