"""Fabricas de adaptadores: cada puerto se prueba con todos los suyos."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import mongomock
import pytest

from adapters.audit_jsonl import JsonlAudit
from adapters.audit_memory import MemoryAudit
from adapters.case_repo_memory import MemoryCaseRepository
from adapters.case_repo_mongo import MongoCaseRepository
from adapters.inbox_memory import MemoryInbox
from adapters.inbox_mongo import MongoInbox
from ports import AuditPort, CaseRepositoryPort, InboxPort


@pytest.fixture(params=["memory", "mongo"])
def case_repo(request: pytest.FixtureRequest) -> CaseRepositoryPort:
    if request.param == "memory":
        return MemoryCaseRepository()
    db = mongomock.MongoClient().db
    return MongoCaseRepository(db.cases)


@pytest.fixture(params=["memory", "mongo"])
def inbox(request: pytest.FixtureRequest) -> InboxPort:
    if request.param == "memory":
        return MemoryInbox()
    return MongoInbox(mongomock.MongoClient().db.tickets)


@pytest.fixture(params=["memory", "jsonl"])
def audit(request: pytest.FixtureRequest, tmp_path: Path) -> AuditPort:
    if request.param == "memory":
        return MemoryAudit()
    return JsonlAudit(tmp_path / "audit.jsonl")


@pytest.fixture
def fixtures_dir() -> Path:
    return Path("fixtures")


Factory = Callable[[], object]
