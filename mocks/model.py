"""Schema de un mapping. Estricto: un campo mal escrito falla al validar."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ID_RE = re.compile(r"^[a-zA-Z0-9_]+(\.[a-zA-Z0-9_]+)+$")


class BodyPattern(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jsonPath: str | None = None
    jsonPathConcat: list[str] | None = None
    equalTo: str

    @model_validator(mode="after")
    def _one_selector(self) -> BodyPattern:
        if (self.jsonPath is None) == (self.jsonPathConcat is None):
            raise ValueError("usa jsonPath o jsonPathConcat, no ambos")
        return self


class MockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
    path: str = Field(pattern=r"^/")
    bodyPatterns: list[BodyPattern] = Field(default_factory=list)


class MockReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: int = Field(default=200, ge=100, le=599)
    jsonBody: Any
    # Fault injection: espera artificial antes de responder.
    faultDelayMs: int = Field(default=0, ge=0)


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    domain: str
    priority: int = 100  # menor gana
    request: MockRequest
    response: MockReply

    @model_validator(mode="after")
    def _valid_id(self) -> Mapping:
        if not ID_RE.match(self.id):
            raise ValueError(f"id invalido: {self.id!r}")
        return self
