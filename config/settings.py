"""Configuracion: env > .env > config/<AGENT_ENV>.yaml > defaults."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).parent


def _yaml_defaults(env: str) -> dict[str, Any]:
    path = CONFIG_DIR / f"{env}.yaml"
    if not path.exists():
        raise RuntimeError(f"AGENT_ENV={env!r} sin archivo {path.name}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(data)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    agent_env: str = "dev"
    log_format: str = "console"
    log_level: str = "INFO"
    allow_anonymous_principal: bool = False
    llm_backend: str = "scripted"
    llm_model: str = ""
    repo_backend: str = "memory"
    policy: str = "rules"  # rules | llm
    audit_backend: str = "memory"  # memory | jsonl
    audit_path: str = "reports/audit.jsonl"
    checkpointer: str = "memory"  # memory | mongo
    fixed_today: str = ""  # fecha fija (YYYY-MM-DD) para demos reproducibles
    demo_endpoints: bool = (
        False  # /demo/scenarios, solo para la interfaz de prueba
    )
    providers_base_url: str = ""  # vacio = motor de mocks en proceso
    mongo_uri: str = ""
    mongo_db: str = "auto_equity"
    agent_max_tool_calls: int = 50
    agent_client_api_key: str = ""


def load_settings() -> Settings:
    env = os.environ.get("AGENT_ENV", "dev")
    base = _yaml_defaults(env)
    base["agent_env"] = env
    # Los valores de YAML son defaults; env y .env ganan.
    defaults = Settings(**{})
    merged = {
        k: v for k, v in base.items() if k not in defaults.model_fields_set
    }
    return Settings(**merged)
