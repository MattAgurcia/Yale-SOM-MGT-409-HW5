"""Cash check 1: the ledger reconciles inside the database.

Reads the original and the working database (read-only) and the audit trail.
Every amount is compared in whole cents. Run from anywhere:

    python3 tests/cash/ledger_check.py [--json results.json]
"""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "data" / "campus_customs.db"
WORKING = ROOT / "data" / "campus_customs_new.db"
TRAIL = ROOT / "output" / "audit_trail.json"
KIND = {"invoice_payment": "invoice", "rent_payment": "rent", "purchase_order": "purchase_order"}
results = []


def check(name, ok, detail=""):
    results.append({"name": name, "passed": bool(ok), "detail": str(detail)})
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def c(x):
    return int(round(float(x) * 100))


def usd(cents):
    return ("−" if cents < 0 else "") + f"${abs(cents) / 100:,.2f}"


def rows(path, sql, immutable=False):
    uri = f"file:{path}?mode=ro" + ("&immutable=1" if immutable else "")
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql)]
    finally:
        conn.close()


def main():
    start = c(rows(ORIGINAL, "SELECT balance FROM cash_accounts WHERE name='checking'", True)[0]["balance"])
    check("original: checking starts at $3,400.00", start == 340000, usd(start))
    check("original: no payments", rows(ORIGINAL, "SELECT * FROM payments", True) == [])
    end = c(rows(WORKING, "SELECT balance FROM cash_accounts WHERE name='checking'")[0]["balance"])
    pays = rows(WORKING, "SELECT * FROM payments ORDER BY id")
    apps = rows(WORKING, "SELECT * FROM approvals ORDER BY id")
    by_pay = {}
    for a in apps:
        if a["payment_id"] is not None:
            by_pay.setdefault(a["payment_id"], []).append(a)

    for p in pays:
        linked = by_pay.get(p["id"], [])
        a = linked[0] if len(linked) == 1 else None
        ok = (a is not None and p["account"] == "checking" and c(p["amount"]) > 0 and a["status"] == "approved"
              and c(a["amount"]) == c(p["amount"]) and KIND[a["kind"]] == p["kind"] and a["ref_id"] == p["ref_id"]
              and p["approved_by"] == a["decided_by"])
        check(f"payment {p['id']} ({p['kind']} {p['ref_id']}, {usd(c(p['amount']))}) matches exactly one approved request",
              ok, f"approval {a['id'] if a else '?'}, ticket {a['ticket_id'] if a else '?'}")
    check("no payment points at a missing row", set(by_pay) == {p["id"] for p in pays})
    check("no rejected request or price override carries a payment",
          all(a["payment_id"] is None for a in apps if a["status"] != "approved" or a["kind"] == "price_override"))
    check("no request is still pending", all(a["status"] in ("approved", "rejected") for a in apps),
          ", ".join(f"{a['id']}:{a['status']}" for a in apps))

    paid = sum(c(p["amount"]) for p in pays)
    check("start − payments = cash_accounts (to the cent)", start - paid == end, f"{usd(start)} − {usd(paid)} = {usd(end)}")
    per = {101: 0, 102: 0, 103: 0}
    for p in pays:
        per[by_pay[p["id"]][0]["ticket_id"]] += c(p["amount"])
    check("per ticket: #101 $848.00, #102 $2,400.00, #103 $0.00", per == {101: 84800, 102: 240000, 103: 0},
          {k: usd(v) for k, v in per.items()})
    check("per-ticket amounts add up to the total paid out", sum(per.values()) == paid, usd(paid))

    # Walk the human decisions in time order: never negative, and each audit balance matches.
    trail = json.loads(TRAIL.read_text())
    reset = [e for e in trail if e["event"] == "db_reset"][-1]
    check("audit: the run starts from a reset with the original's hash",
          reset["sha256"].startswith("23686a90d698f7fa"), f"seq {reset['seq']}")
    after = [e for e in trail if e["seq"] > reset["seq"]]
    decisions = [e for e in after if e["event"] == "human_decision" and e.get("outcome") == "done"]
    bal, ok, steps = start, True, []
    for d in decisions:
        if d.get("payment"):
            bal -= c(d["payment"]["amount"])
            ok = ok and bal >= 0 and c(d["cash_balance_after"]) == bal
            steps.append(usd(bal))
    check("decisions in order: balance never negative and matches each audit balance", ok and bal == end,
          " → ".join([usd(start)] + steps))
    check("every payment row has its decision in the audit trail",
          sorted(d["payment"]["payment_id"] for d in decisions if d.get("payment")) == [p["id"] for p in pays])
    check("no agent approved or rejected anything",
          not any(e["event"] == "tool_call" and e.get("tool") in ("approve_request", "reject_request") for e in after))
    reads = [e for e in after if e["event"] == "tool_call" and e.get("tool") == "check_cash" and e.get("status") == "ok"]
    first_decision = min((d["seq"] for d in decisions), default=10**9)
    check("every agent cash read before the decisions saw the starting balance",
          all(c(e["result"]["total_balance"]) == start for e in reads if e["seq"] < first_decision), f"{len(reads)} reads")

    # The tables each payment must also change.
    inv = rows(WORKING, "SELECT status FROM invoices WHERE id = 501")[0]["status"]
    check("invoice 501 is paid", inv == "paid", inv)
    lease = rows(WORKING, "SELECT next_due FROM leases WHERE id = 1")[0]["next_due"]
    check("lease 1 moved one month on (2026-09-02 → 2026-10-02)", lease == "2026-10-02", lease)
    pos = {p["id"]: p for p in rows(WORKING, "SELECT * FROM purchase_orders")}
    check("PO 1 ordered ($8.00, arriving 2026-09-05); PO 2 rejected ($264.00, nothing paid)",
          pos[1]["status"] == "ordered" and c(pos[1]["total"]) == 800 and pos[1]["expected_arrival"] == "2026-09-05"
          and pos[2]["status"] == "rejected" and c(pos[2]["total"]) == 26400)
    check("stock is unchanged (no delivery is recorded)",
          rows(WORKING, "SELECT sku, size, qty FROM inventory ORDER BY sku, size")
          == rows(ORIGINAL, "SELECT sku, size, qty FROM inventory ORDER BY sku, size", True))

    failed = [r for r in results if not r["passed"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(results, indent=1, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
