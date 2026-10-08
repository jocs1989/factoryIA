"""Mock standalone (docker-compose): `uvicorn mocks.server:app`."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from mocks.engine import MockEngine


def create_app(engine: MockEngine | None = None) -> FastAPI:
    """Sirve los mappings por HTTP para `docker compose`."""
    directory = Path(os.environ.get("MOCK_MAPPINGS_DIR", "mocks/mappings"))
    state = {"engine": engine or MockEngine.from_dir(directory)}
    app = FastAPI(title="Mocks de proveedores")

    @app.get("/_mock/health")
    async def health() -> dict[str, Any]:
        eng: MockEngine = state["engine"]
        return {"ready": True, "mappings_loaded": eng.mappings_loaded}

    @app.post("/_mock/reload")
    async def reload() -> dict[str, int]:
        state["engine"] = MockEngine.from_dir(directory)
        return {"mappings_loaded": state["engine"].mappings_loaded}

    @app.api_route(
        "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"]
    )
    async def serve(path: str, request: Request) -> JSONResponse:
        raw = await request.body()
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        eng: MockEngine = state["engine"]
        res = eng.handle(request.method, "/" + path, body)
        if res.delay_ms:
            await asyncio.sleep(res.delay_ms / 1000)
        return JSONResponse(res.body, status_code=res.status)

    return app


app = create_app()
