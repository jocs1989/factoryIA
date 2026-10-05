"""Tipos que comparten politicas, grafo y ejecutor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from domain.case import Stage
from tools.executor import ToolResult
from tools.spec import ToolSpec


class DocRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc_id: str
    doc_type: str


class CustomerEvent(BaseModel):
    """Lo que el cliente manda en un turno. Es DATO, no instruccion."""

    model_config = ConfigDict(frozen=True)

    text: str = Field(default="", max_length=2000)
    documents: tuple[DocRef, ...] = ()


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class Reply:
    """Mensaje al cliente; cierra el turno (se espera su respuesta)."""

    text: str


Action = ToolCall | Reply


@dataclass(frozen=True)
class StageView:
    case_id: str
    run_id: str
    stage: Stage
    case: dict[str, Any]  # proyeccion compacta, sin PII
    event: CustomerEvent | None  # None si ya se consumio
    pending_docs: tuple[DocRef, ...]
    last: ToolResult | None
    tools: tuple[ToolSpec, ...]  # lista blanca de esta etapa
    history: tuple[dict[str, str], ...] = field(default=())


class Policy:
    """Decide la siguiente accion acotada; el ejecutor la valida."""

    name = "policy"

    def next_action(self, view: StageView) -> Action:
        raise NotImplementedError
