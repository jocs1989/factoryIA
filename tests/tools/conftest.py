from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from adapters.audit_memory import MemoryAudit
from adapters.case_repo_memory import MemoryCaseRepository
from adapters.idempotency_memory import MemoryIdempotency
from adapters.inbox_memory import MemoryInbox
from adapters.providers import Providers, build_providers
from domain.case import Case, Stage
from domain.documents import load_document_policy
from domain.profile import load_profile_policy
from tools.catalog import build_catalog
from tools.deps import Deps
from tools.executor import Executor
from tools.principals import PrincipalRegistry
from tools.session import Session

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

BASE_DATA: dict[str, Any] = {
    "customer_id": "cust-s01",
    "vehicle_id": "veh-s01",
    "customer_name": "Juan Pérez López",
    "declared_income": "20000.00",
    "requested_amount": "80000",
    "employment_type": "salaried",
    "phone_last4": "1234",
    "address_street": "Calle Reforma 10",
    "address_postal_code": "06600",
}
GOOD_DOCS = {
    "payslip": "doc-good-payslip",
    "proof_of_address": "doc-good-address",
    "id_card": "doc-good-id",
    "vehicle_title": "doc-good-title",
}


class Env:
    """Entorno completo en memoria con los mocks de proveedores."""

    def __init__(self) -> None:
        self.providers: Providers = build_providers()
        self.repo = MemoryCaseRepository()
        self.inbox = MemoryInbox()
        self.audit = MemoryAudit()
        self.deps = Deps(
            repo=self.repo,
            inbox=self.inbox,
            audit=self.audit,
            idempotency=MemoryIdempotency(),
            bureau=self.providers.bureau,
            key_quote=self.providers.key_quote,
            vehicles=self.providers.vehicles,
            reader=self.providers.reader,
            channel=self.providers.channel,
            profile_policy=load_profile_policy(
                Path("config/profile_policy.yaml")
            ),
            document_policy=load_document_policy(
                Path("config/document_policy.yaml")
            ),
            clock=lambda: NOW,
        )
        self.executor = Executor(self.deps, build_catalog())
        reg = PrincipalRegistry.from_yaml(Path("config/principals.yaml"), {})
        self.agent = reg.get("customer-agent")
        self.advisor = reg.get("advisor")

    def new_case(
        self,
        case_id: str = "c1",
        stage: Stage = Stage.ELIGIBILITY,
        **data: Any,
    ) -> Session:
        self.repo.add(
            Case(case_id=case_id, stage=stage, data={**BASE_DATA, **data})
        )
        return Session(case_id)

    def call(self, tool: str, session: Session | None = None, **args: Any):  # type: ignore[no-untyped-def]
        session = session or Session("c1")
        args.setdefault("case_id", session.case_id)
        return self.executor.call(self.agent, session, tool, args)

    def as_advisor(
        self, tool: str, session: Session | None = None, **args: Any
    ):  # type: ignore[no-untyped-def]
        session = session or Session("c1")
        args.setdefault("case_id", session.case_id)
        return self.executor.call(self.advisor, session, tool, args)

    def case(self, case_id: str = "c1") -> Case:
        found = self.repo.get(case_id)
        assert found is not None
        return found

    def advance_to_simulation(self, **data: Any) -> Session:
        s = self.new_case(**data)
        assert self.call("check_vehicle_eligibility").ok
        assert self.call("record_bureau_consent", consent=True).ok
        assert self.call("query_credit_bureau").ok
        return s

    def advance_to_documents(self, term: int = 24, **data: Any) -> Session:
        s = self.advance_to_simulation(**data)
        amount = self.case().data["requested_amount"]
        assert self.call("build_simulation", requested_amount=amount).ok
        assert self.call("record_customer_choice", term_months=term).ok
        return s

    def attach_all(self, docs: dict[str, str] | None = None) -> None:
        for dtype, doc_id in (docs or GOOD_DOCS).items():
            r = self.call("attach_document", doc_id=doc_id, doc_type=dtype)
            assert r.ok, r


@pytest.fixture
def env() -> Env:
    return Env()
