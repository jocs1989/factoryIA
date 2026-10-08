"""Un turno a la vez por caso, y turnos de casos distintos en paralelo."""

import threading
import time
from collections import Counter

from agent.runtime import build_runtime
from agent.types import CustomerEvent
from config.settings import load_settings
from ports import AuditEvent

BASE = {
    "customer_id": "cust-s01",
    "vehicle_id": "veh-s01",
    "customer_name": "Juan Pérez López",
    "declared_income": "20000.00",
    "requested_amount": "50000",
    "employment_type": "salaried",
    "address_street": "Calle Reforma 10",
    "address_postal_code": "06600",
    "phone_last4": "1234",
}


def _dos_turnos_a_la_vez() -> tuple[list[AuditEvent], list[str]]:
    rt = build_runtime(load_settings())
    rt.create_case({**BASE, "case_id": "c"})
    session = rt.verify("c", "1234")
    errors: list[str] = []

    def go(text: str) -> None:
        try:
            rt.runner.turn(session, CustomerEvent(text=text))
        except Exception as exc:  # noqa: BLE001 - se reporta en la prueba
            errors.append(type(exc).__name__)

    threads = [
        threading.Thread(target=go, args=(t,)) for t in ("hola", "sí autorizo")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return rt.deps.audit.list_events("c"), errors


def test_dos_mensajes_simultaneos_al_mismo_caso_se_serializan() -> None:
    for trial in range(15):
        events, errors = _dos_turnos_a_la_vez()
        codes = Counter(c for e in events for c in e.reason_codes)
        assert not errors, errors
        assert codes["STALE_VERSION"] == 0, f"corrida {trial}: {codes}"
        ok = Counter(e.name for e in events if e.outcome == "ok")
        assert ok["check_vehicle_eligibility"] == 1  # no se duplico


def test_casos_distintos_no_se_bloquean_entre_si() -> None:
    rt = build_runtime(load_settings())
    for cid in ("a", "b"):
        rt.create_case({**BASE, "case_id": cid})
    sa, sb = rt.verify("a", "1234"), rt.verify("b", "1234")
    gate = threading.Event()
    inside: list[str] = []

    real = rt.runner._turn  # type: ignore[attr-defined]

    def slow(session, event):  # type: ignore[no-untyped-def]
        inside.append(session.case_id)
        if session.case_id == "a":
            gate.wait(timeout=5)  # "a" se queda dentro de su turno
        return real(session, event)

    rt.runner._turn = slow  # type: ignore[attr-defined,method-assign]
    ta = threading.Thread(
        target=lambda: rt.runner.turn(sa, CustomerEvent(text="x"))
    )
    ta.start()
    while "a" not in inside:
        time.sleep(0.01)
    started = time.monotonic()
    rt.runner.turn(sb, CustomerEvent(text="hola"))  # no espera a "a"
    assert time.monotonic() - started < 3
    gate.set()
    ta.join(timeout=10)
