"""Cash check 3: replay the P9 money decisions through the real MCP server on a fresh copy of the original DB.

Independent of the LLM and of the P9 pages: the same six requests are filed and decided, in
the same order, through the same MCP tools the backend uses (stdio, CAMPUS_HUMAN_TOOLS=1). The
replayed database must end exactly where the working database ended, and the safety refusals
(no negative balance, no paying a blocked vendor, no double pay, no agent approvals, no duplicate
requests) must hold. Run with the project's venv python.

Uses a temporary copy, so neither real database changes:

    .venv/bin/python tests/cash/replay_check.py [--json results.json]
"""

import asyncio
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "mcp_server" / "server.py"
ORIGINAL = ROOT / "data" / "campus_customs.db"
WORKING = ROOT / "data" / "campus_customs_new.db"
HUMAN = "Matthew Agurcia"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def cents(x) -> int:
    return int(round(float(x) * 100))


async def call(client, tool, **args):
    r = await client.call_tool(tool, args, raise_on_error=False)
    text = "".join(getattr(c, "text", "") for c in r.content)
    if r.is_error:
        return None, text
    data = r.structured_content
    if isinstance(data, dict) and set(data) == {"result"}:
        data = data["result"]
    return data, None


def balance(db: Path) -> int:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return cents(c.execute("SELECT balance FROM cash_accounts WHERE name='checking'").fetchone()[0])
    finally:
        c.close()


def payment_count(db: Path) -> int:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return c.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    finally:
        c.close()


def snapshot(db: Path) -> dict:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    q = lambda sql: [tuple(r) for r in c.execute(sql)]
    out = dict(
        cash=q("SELECT name, balance, date FROM cash_accounts"),
        payments=q("SELECT id, kind, ref_id, amount, account, paid_at, approved_by FROM payments ORDER BY id"),
        approvals=q("SELECT id, ticket_id, kind, ref_id, amount, status, decided_by, payment_id FROM approvals ORDER BY id"),
        invoices=q("SELECT id, amount, status FROM invoices"),
        leases=q("SELECT id, monthly_rent, next_due FROM leases"),
        purchase_orders=q("SELECT id, ticket_id, vendor_id, sku, size, qty, unit_cost, total, status, ordered_at, expected_arrival FROM purchase_orders ORDER BY id"),
        inventory=q("SELECT sku, size, qty FROM inventory ORDER BY sku, size"),
    )
    c.close()
    return out


async def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="cash_replay_"))
    db = tmp / "replay.db"
    shutil.copyfile(ORIGINAL, db)
    start = balance(db)
    check("replay starts from the original's checking balance", start == 340000, f"${start / 100:,.2f}")

    env = {"CAMPUS_DB_PATH": str(db), "CAMPUS_HUMAN_TOOLS": "1", "PATH": "/usr/bin:/bin"}
    transport = StdioTransport(command=sys.executable, args=[str(SERVER)], env=env, cwd=str(ROOT), keep_alive=False)
    async with Client(transport) as client:
        tools = {t.name for t in await client.list_tools()}
        check("human tools are present only because CAMPUS_HUMAN_TOOLS=1", {"approve_request", "reject_request"} <= tools)

        # The five requests the agents filed in P9, in the same order.
        r1, err = await call(client, "request_payment", ticket_id=101, kind="invoice", ref_id=501, reason="replay", actor="Accounting")
        check("request 1: invoice 501 for $840.00", r1 and r1["approval"]["approval_id"] == 1 and cents(r1["approval"]["amount"]) == 84000, err or "")
        r2, err = await call(client, "create_purchase_order", ticket_id=101, vendor_id=1, sku="CC-TEE-WHITE", size="S", qty=1, reason="replay", actor="Accounting")
        check("request 2: PO 1, 1 tee at $8.00", r2 and r2["approval"]["approval_id"] == 2 and cents(r2["approval"]["amount"]) == 800, err or "")
        r3, err = await call(client, "request_payment", ticket_id=102, kind="rent", ref_id=1, reason="replay", actor="Accounting")
        check("request 3: rent for lease 1, $2,400.00", r3 and r3["approval"]["approval_id"] == 3 and cents(r3["approval"]["amount"]) == 240000, err or "")
        r4, err = await call(client, "request_price_override", ticket_id=103, sku="CC-HOOD-NAVY", qty=20, unit_price=49.0, reason="replay", actor="Accounting")
        check("request 4: price override $49 x 20, $0.00 cash", r4 and r4["approval"]["approval_id"] == 4 and cents(r4["approval"]["amount"]) == 0, err or "")
        r5, err = await call(client, "create_purchase_order", ticket_id=103, vendor_id=1, sku="CC-HOOD-NAVY", size="M", qty=12, reason="replay", actor="Accounting")
        check("request 5: PO 2, 12 hoodies at $264.00", r5 and r5["approval"]["approval_id"] == 5 and cents(r5["approval"]["amount"]) == 26400, err or "")
        check("filing requests moved no cash", balance(db) == start and payment_count(db) == 0)

        cash, _ = await call(client, "check_cash")
        check("check_cash before decisions: pending $3,512.00, short $112.00",
              cents(cash["pending_total"]) == 351200 and cents(cash["balance_if_all_pending_paid"]) == -11200,
              f"pending ${cash['pending_total']:,.2f}, if all paid ${cash['balance_if_all_pending_paid']:,.2f}")

        # Refusals before any payment.
        _, err = await call(client, "request_payment", ticket_id=103, kind="invoice", ref_id=501, reason="dup", actor="Accounting")
        check("duplicate invoice request refused (as in the run)", err is not None and "already pending" in err, (err or "")[:90])
        _, err = await call(client, "approve_request", approval_id=2, approved_by=HUMAN)
        check("tee PO refused while invoice 501 is unpaid", err is not None and balance(db) == start, (err or "")[:90])
        _, err = await call(client, "approve_request", approval_id=3, approved_by="Accounting")
        check("an agent name cannot approve", err is not None and balance(db) == start, (err or "")[:90])

        # The decisions, in the order they were made on the board.
        expect = [(3, 100000), (1, 16000), (2, 15200), (4, 15200)]
        for aid, after in expect:
            d, err = await call(client, "approve_request", approval_id=aid, approved_by=HUMAN)
            got = cents(d["cash_balance_after"]) if d and d.get("cash_balance_after") is not None else balance(db)
            check(f"approve request {aid}: checking ${after / 100:,.2f}", err is None and got == after == balance(db), err or f"${got / 100:,.2f}")

        _, err = await call(client, "approve_request", approval_id=5, approved_by=HUMAN)
        check("$264.00 hoodie PO refused with $152.00 left (no negative balance)",
              err is not None and "Not enough cash" in err and balance(db) == 15200 and payment_count(db) == 3, (err or "")[:90])
        _, err = await call(client, "approve_request", approval_id=3, approved_by=HUMAN)
        check("approving rent a second time is refused (no double pay)", err is not None and balance(db) == 15200, (err or "")[:90])
        d, err = await call(client, "reject_request", approval_id=5, decided_by=HUMAN, note="replay")
        check("reject request 5: nothing paid", err is None and balance(db) == 15200 and payment_count(db) == 3, err or "")

        # Request 6 was filed in #103's first close run, after the decisions above, and approved before its second.
        r6, err = await call(client, "request_price_override", ticket_id=103, sku="CC-HOOD-NAVY", qty=8, unit_price=49.0, reason="replay", actor="Accounting")
        check("request 6: price override $49 x 8 (the hoodies in stock), $0.00 cash", r6 and r6["approval"]["approval_id"] == 6 and cents(r6["approval"]["amount"]) == 0, err or "")
        d, err = await call(client, "approve_request", approval_id=6, approved_by=HUMAN)
        check("approve request 6: no cash moves, checking stays $152.00", err is None and balance(db) == 15200 and payment_count(db) == 3, err or "")
        cash, _ = await call(client, "check_cash")
        check("final check_cash reads $152.00 with 3 payments", cents(cash["total_balance"]) == 15200 and len(cash["payments"]) == 3)

    rep, work = snapshot(db), snapshot(WORKING)
    for table in rep:
        check(f"replayed {table} equal the working database's", rep[table] == work[table],
              "" if rep[table] == work[table] else f"replay={rep[table]} working={work[table]}")
    paid = sum(cents(p[3]) for p in rep["payments"])
    check("start - payments = end, in cents", start - paid == balance(db) == 15200, f"{start} - {paid} = {balance(db)}")
    shutil.rmtree(tmp)

    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps([{"name": n, "passed": ok, "detail": str(d)} for n, ok, d in results], indent=1, ensure_ascii=False))
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
