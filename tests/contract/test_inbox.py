from datetime import UTC, datetime

import pytest

from ports import InboxPort, Ticket, TicketError, TicketStatus


def ticket(tid: str = "t1", case_id: str = "c1") -> Ticket:
    return Ticket(
        ticket_id=tid,
        case_id=case_id,
        reason_code="INCOME_MISMATCH",
        summary="Ingreso 40 % menor",
        evidence={"declared": "20000", "verified": "12000"},
        suggested_action="Revisar comprobante",
        created_at=datetime(2026, 10, 5, tzinfo=UTC),
    )


def test_create_get_y_list_open(inbox: InboxPort) -> None:
    inbox.create(ticket("t1"))
    inbox.create(ticket("t2", "c2"))
    assert inbox.get("t1") == ticket("t1")
    assert {t.ticket_id for t in inbox.list_open()} == {"t1", "t2"}


def test_get_inexistente(inbox: InboxPort) -> None:
    assert inbox.get("nope") is None


def test_resolver_lo_saca_de_abiertos(inbox: InboxPort) -> None:
    inbox.create(ticket())
    r = inbox.resolve("t1", resolution="Comprobante valido", resolved_by="ana")
    assert r.status is TicketStatus.RESOLVED
    assert (r.resolution, r.resolved_by) == ("Comprobante valido", "ana")
    assert inbox.list_open() == []
    assert inbox.get("t1") == r


@pytest.mark.parametrize("motivo", ["", "   "])
def test_resolver_exige_justificacion(inbox: InboxPort, motivo: str) -> None:
    inbox.create(ticket())
    with pytest.raises(TicketError):
        inbox.resolve("t1", resolution=motivo, resolved_by="ana")
    assert len(inbox.list_open()) == 1


def test_no_se_resuelve_dos_veces(inbox: InboxPort) -> None:
    inbox.create(ticket())
    inbox.resolve("t1", resolution="ok", resolved_by="ana")
    with pytest.raises(TicketError):
        inbox.resolve("t1", resolution="otra vez", resolved_by="luis")


def test_resolver_inexistente(inbox: InboxPort) -> None:
    with pytest.raises(TicketError):
        inbox.resolve("nope", resolution="x", resolved_by="ana")


def test_ticket_duplicado(inbox: InboxPort) -> None:
    inbox.create(ticket())
    with pytest.raises(TicketError):
        inbox.create(ticket())
