"""Ensambla puertos, politicas, ejecutor y grafo segun la configuracion."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from adapters.audit_jsonl import JsonlAudit
from adapters.audit_memory import MemoryAudit
from adapters.case_repo_memory import MemoryCaseRepository
from adapters.idempotency_memory import MemoryIdempotency
from adapters.inbox_memory import MemoryInbox
from adapters.llm.registry import create_llm
from adapters.providers import Providers, build_providers
from agent.graph import GraphDeps
from agent.policy_llm import LLMPolicy
from agent.policy_rules import RuleBasedPolicy
from agent.runner import ConversationRunner
from agent.types import Policy
from config.settings import Settings
from domain.case import Case, Stage
from domain.documents import load_document_policy
from domain.profile import load_profile_policy
from ports import LLMPort
from tools.catalog import build_catalog
from tools.deps import Deps, utc_now
from tools.executor import Executor
from tools.principals import PrincipalRegistry
from tools.session import Session, verify_identity

CONFIG = Path("config")
REQUIRED_CASE_FIELDS = (
    "customer_id",
    "vehicle_id",
    "customer_name",
    "declared_income",
    "requested_amount",
    "employment_type",
    "phone_last4",
)


@dataclass
class Runtime:
    settings: Settings
    deps: Deps
    executor: Executor
    runner: ConversationRunner
    principals: PrincipalRegistry
    policy: Policy
    providers: Providers

    def create_case(self, data: dict[str, Any]) -> Case:
        missing = [f for f in REQUIRED_CASE_FIELDS if not data.get(f)]
        if missing:
            raise ValueError(f"faltan campos: {', '.join(missing)}")
        case_id = str(data.get("case_id") or f"C-{uuid.uuid4().hex[:8]}")
        facts = {k: v for k, v in data.items() if k != "case_id"}
        case = Case(case_id=case_id, stage=Stage.ELIGIBILITY, data=facts)
        self.deps.repo.add(case)
        return case

    def verify(self, case_id: str, phone_last4: str) -> Session:
        return verify_identity(self.deps.repo, case_id, phone_last4)


def _clock(fixed_today: str) -> Any:
    if not fixed_today:
        return utc_now
    day = date.fromisoformat(fixed_today)
    fixed = datetime.combine(day, time(12, 0), tzinfo=UTC)
    return lambda: fixed


def _mongo_collections(settings: Settings) -> tuple[Any, Any, Any]:
    from pymongo import MongoClient

    client: MongoClient[dict[str, Any]] = MongoClient(settings.mongo_uri)
    db = client[settings.mongo_db]
    db.idempotency.create_index("_id")
    return db.cases, db.tickets, db.idempotency


def build_runtime(
    settings: Settings,
    *,
    llm: LLMPort | None = None,
    policy: Policy | None = None,
    mappings_dir: Path | None = None,
    checkpointer: Any = None,
) -> Runtime:
    clock = _clock(settings.fixed_today)
    audit = (
        JsonlAudit(Path(settings.audit_path))
        if settings.audit_backend == "jsonl"
        else MemoryAudit()
    )
    if settings.repo_backend == "mongo":
        from adapters.case_repo_mongo import MongoCaseRepository
        from adapters.idempotency_mongo import MongoIdempotency
        from adapters.inbox_mongo import MongoInbox

        cases, tickets, idem = _mongo_collections(settings)
        repo: Any = MongoCaseRepository(cases)
        inbox: Any = MongoInbox(tickets)
        idempotency: Any = MongoIdempotency(idem)
    else:
        repo, inbox, idempotency = (
            MemoryCaseRepository(),
            MemoryInbox(),
            MemoryIdempotency(),
        )
    providers = (
        build_providers(settings.providers_base_url, mappings_dir=mappings_dir)
        if mappings_dir
        else build_providers(settings.providers_base_url)
    )
    deps = Deps(
        repo=repo,
        inbox=inbox,
        audit=audit,
        idempotency=idempotency,
        bureau=providers.bureau,
        key_quote=providers.key_quote,
        vehicles=providers.vehicles,
        reader=providers.reader,
        channel=providers.channel,
        profile_policy=load_profile_policy(CONFIG / "profile_policy.yaml"),
        document_policy=load_document_policy(CONFIG / "document_policy.yaml"),
        clock=clock,
    )
    executor = Executor(deps, build_catalog())
    principals = PrincipalRegistry.from_yaml(
        CONFIG / "principals.yaml", os.environ
    )
    rules = RuleBasedPolicy()
    if policy is None:
        if settings.policy == "llm":
            model = llm or create_llm(
                settings.llm_backend, model=settings.llm_model or None
            )
            policy = LLMPolicy(model, rules, audit, clock=clock)
        else:
            policy = rules
    if checkpointer is None:
        if settings.checkpointer == "mongo":
            from langgraph.checkpoint.mongodb import MongoDBSaver
            from pymongo import MongoClient

            checkpointer = MongoDBSaver(MongoClient(settings.mongo_uri))
        else:
            checkpointer = InMemorySaver()
    graph_deps = GraphDeps(
        executor=executor,
        repo=repo,
        audit=audit,
        policy=policy,
        principal=principals.get("customer-agent"),
        clock=clock,
    )
    return Runtime(
        settings=settings,
        deps=deps,
        executor=executor,
        runner=ConversationRunner(graph_deps, checkpointer),
        principals=principals,
        policy=policy,
        providers=providers,
    )
