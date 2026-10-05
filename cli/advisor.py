"""Consola del asesor: cliente HTTP de la API.

  advisor inbox
  advisor show <caso>
  advisor resolve <ticket> --case <caso> --decision resume|reject|decline \\
          --justification "..." [--override CODIGO ...]

Credencial: variable ADVISOR_API_KEY (nunca por argumento: queda en el
historial del shell).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from typing import Any

import httpx


def _fail(res: httpx.Response, out: Callable[[str], None]) -> int:
    try:
        detail = res.json().get("detail", res.text)
    except ValueError:
        detail = res.text
    out(f"error {res.status_code}: {detail}")
    return 1


def main(
    argv: list[str] | None = None,
    client: httpx.Client | None = None,
    out: Callable[[str], None] = print,
) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api-url", default="http://localhost:8000")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inbox")
    show = sub.add_parser("show")
    show.add_argument("case_id")
    res = sub.add_parser("resolve")
    res.add_argument("ticket_id")
    res.add_argument("--case", required=True)
    res.add_argument(
        "--decision", required=True, choices=["resume", "reject", "decline"]
    )
    res.add_argument("--justification", required=True)
    res.add_argument("--override", action="append", default=[])
    args = p.parse_args(argv)

    key = os.environ.get("ADVISOR_API_KEY", "")
    if not key:
        out("falta la variable ADVISOR_API_KEY")
        return 2
    headers = {"X-API-Key": key}
    http = client or httpx.Client(base_url=args.api_url, timeout=15.0)

    if args.cmd == "inbox":
        r = http.get("/advisor/inbox", headers=headers)
        if r.status_code != 200:
            return _fail(r, out)
        tickets: list[dict[str, Any]] = r.json()
        if not tickets:
            out("bandeja vacia")
        for t in tickets:
            out(
                f"{t['ticket_id']}  caso={t['case_id']}  {t['reason_code']}"
                f"  {t['summary']}"
            )
        return 0
    if args.cmd == "show":
        r = http.get(f"/advisor/cases/{args.case_id}", headers=headers)
        if r.status_code != 200:
            return _fail(r, out)
        body = r.json()
        snap = body["snapshot"]
        out(f"caso {args.case_id}: {snap['stage']} (v{snap['version']})")
        for k, v in snap["projection"].items():
            if v not in (None, [], False, ""):
                out(f"  {k}: {v}")
        out("linea de tiempo:")
        for e in body["timeline"]:
            codes = f" {e['reason_codes']}" if e["reason_codes"] else ""
            out(
                f"  {e['ts'][11:19]} {e['principal']:15} {e['name']:26} "
                f"{e['outcome']}{codes}"
            )
        return 0
    r = http.post(
        f"/advisor/tickets/{args.ticket_id}/resolve",
        headers=headers,
        json={
            "case_id": args.case,
            "decision": args.decision,
            "justification": args.justification,
            "override_codes": args.override,
        },
    )
    if r.status_code != 200:
        return _fail(r, out)
    body = r.json()
    out(f"resuelto: {body['result']['stage']}")
    for m in body["agent"]["messages"]:
        out(f"Agente> {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
