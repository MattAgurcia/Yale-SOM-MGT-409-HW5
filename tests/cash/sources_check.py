"""Cash check 2: every place that states a cash figure agrees with the working database.

Written separately from the page generators (no shared code). Sources compared:
  the working DB (cash_accounts, payments, approvals), the original DB (start),
  the live API (/api/cash, /api/approvals on localhost:8000), the audit trail
  (db_reset, human_decision balances, agents' check_cash reads), and the three
  P9 deliverables (desk_tickets.html Actual + Cash, resolved_tickets.json,
  resolved_board.html).

Needs the backend running on port 8000 for the API part:

    python3 tests/cash/sources_check.py [--json results.json]
"""

import json
import re
import sqlite3
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "output"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def c(x):
    return int(round(float(x) * 100))


def dollars(s):
    """'−$2,400.00' / '-$8.00' / '$152.00' -> cents."""
    s = s.strip().replace("−", "-").replace(",", "")
    m = re.fullmatch(r"(-?)\$(\d+)\.(\d\d)", s)
    assert m, s
    v = int(m.group(2)) * 100 + int(m.group(3))
    return -v if m.group(1) else v


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, d):
        self.parts.append(d)


def text_of(fragment):
    p = Text()
    p.feed(fragment)
    return re.sub(r"\s+", " ", "".join(p.parts)).strip()


# ---- the database ----------------------------------------------------------
orig = sqlite3.connect(f"file:{ROOT / 'data/campus_customs.db'}?mode=ro&immutable=1", uri=True)
START = c(orig.execute("SELECT balance FROM cash_accounts WHERE name='checking'").fetchone()[0])
orig.close()
w = sqlite3.connect(f"file:{ROOT / 'data/campus_customs_new.db'}?mode=ro", uri=True)
END = c(w.execute("SELECT balance FROM cash_accounts WHERE name='checking'").fetchone()[0])
pays = w.execute("SELECT id, kind, ref_id, amount FROM payments ORDER BY id").fetchall()
apps = w.execute("SELECT id, ticket_id, kind, amount, status, payment_id FROM approvals ORDER BY id").fetchall()
w.close()
PAID = sum(c(p[3]) for p in pays)
TICKET_OF_PAYMENT = {a[5]: a[1] for a in apps if a[5] is not None}
PER = {101: 0, 102: 0, 103: 0}
for p in pays:
    PER[TICKET_OF_PAYMENT[p[0]]] += c(p[3])
check("DB: start - sum(payments) = cash_accounts", START - PAID == END, f"{START} - {PAID} = {END}")
check("DB: values are $3,400.00 / $3,248.00 / $152.00", (START, PAID, END) == (340000, 324800, 15200))
check("DB: per ticket 101 $848, 102 $2,400, 103 $0", PER == {101: 84800, 102: 240000, 103: 0}, str(PER))

# ---- the live API ----------------------------------------------------------
try:
    cash = json.load(urllib.request.urlopen("http://localhost:8000/api/cash", timeout=10))
    check("API /api/cash balance = DB", c(cash["balance"]) == END, f"${cash['balance']:,.2f}")
    check("API /api/cash payments = DB rows", [(p["payment_id"], p["kind"], p["ref_id"], c(p["amount"])) for p in cash["payments"]]
          == [(p[0], p[1], p[2], c(p[3])) for p in pays])
    check("API /api/cash nothing pending", c(cash["pending_total"]) == 0)
    api_apps = json.load(urllib.request.urlopen("http://localhost:8000/api/approvals", timeout=10))
    check("API /api/approvals = DB (status, amount, payment)",
          sorted((a["approval_id"], a["status"], c(a["amount"]), a["payment_id"]) for a in api_apps)
          == sorted((a[0], a[4], c(a[3]), a[5]) for a in apps))
except OSError as err:
    check("API reachable on localhost:8000", False, str(err))

# ---- the audit trail -------------------------------------------------------
trail = json.loads((OUT / "audit_trail.json").read_text())
check("audit: seq continuous", [e["seq"] for e in trail] == list(range(1, len(trail) + 1)))
resets = [e for e in trail if e["event"] == "db_reset"]
reset = resets[-1]
check("audit: last reset is seq 323 (the second full run), from the original's hash", reset["seq"] == 323 and reset["sha256"].startswith("23686a90d698f7fa"))
after = [e for e in trail if e["seq"] > reset["seq"]]
bal = START
chain = []
for e in after:
    if e["event"] == "human_decision" and e.get("payment"):
        bal -= c(e["payment"]["amount"])
        chain.append((e["approval_id"], bal, c(e["cash_balance_after"])))
check("audit: every human_decision balance = running balance", all(a == b for _, a, b in chain), str(chain))
check("audit: balances go 1,000 -> 160 -> 152", [b for _, b, _ in chain] == [100000, 16000, 15200])
check("audit: final running balance = DB", bal == END)
reads = [e for e in after if e["event"] == "tool_call" and e["tool"] == "check_cash"]
paid_seqs = [(e["seq"], c(e["cash_balance_after"])) for e in after if e["event"] == "human_decision" and e.get("payment")]
def balance_at(seq):
    done = [b for s, b in paid_seqs if s < seq]
    return done[-1] if done else START
check("audit: every agent cash read saw the balance of that moment ($3,400.00 before the decisions, $152.00 after)",
      all(c(e["result"]["total_balance"]) == balance_at(e["seq"]) for e in reads),
      ", ".join(f"seq {e['seq']}: ${e['result']['total_balance']:,.2f}" for e in reads))
check("audit: no agent called approve/reject after the reset",
      not any(e["event"] == "tool_call" and e["tool"] in ("approve_request", "reject_request") for e in after))

# ---- desk_tickets.html -----------------------------------------------------
page = (OUT / "desk_tickets.html").read_text()
cash_panel = re.search(r'<section id="panel-Cash".*?</section>', page, re.S).group(0)
tiles = [text_of(x) for x in re.findall(r'<span class="tile-num">(.*?)</span>', cash_panel)]
check("desk Cash tiles: start / paid / end", [dollars(t) for t in tiles] == [START, -PAID, END], str(tiles))
rows = re.findall(r"<tr><th scope='row'>#(\d+).*?<td class='num-cell big'>(.*?)</td></tr>", cash_panel, re.S)
check("desk Cash per-ticket changes = DB", {int(t): -dollars(v) for t, v in rows} == PER, str(rows))
amts = re.findall(r"<span class='amt'>(−\$[\d,]+\.\d\d)</span>", cash_panel)
check("desk Cash itemized payments = DB amounts", sorted(-dollars(a) for a in amts) == sorted(c(p[3]) for p in pays), str(amts))
total = re.search(r"Total paid out</th><td class=\"num-cell big\">(.*?)</td>", cash_panel)
check("desk Cash total row = paid out", total and -dollars(total.group(1)) == PAID)
ledger = re.search(r'<table class="ledger">(.*?)</table>', cash_panel, re.S).group(1)
after_cells = [dollars(text_of(x)) for x in re.findall(r"<td class='num-cell'><strong>(.*?)</strong></td>", ledger)]
check("desk ledger running balance 3,400 -> 1,000 -> 160 -> 152 -> 152 -> 152 -> 152",
      after_cells == [340000, 100000, 16000, 15200, 15200, 15200, 15200], str(after_cells))
eq = text_of(re.search(r'<p class="equation">(.*?)</p>', cash_panel).group(1))
nums = [dollars(x) for x in re.findall(r"\$[\d,]+\.\d\d", eq)]
check("desk equation adds up", nums[0] - sum(nums[1:-1]) == nums[-1] == END and nums[0] == START, eq)
check("desk names the cash_accounts row", "checking · 152.0 · 2026-08-31" in cash_panel)
for tid in (101, 102, 103):
    panel = re.search(rf'<section id="panel-{tid}".*?</section>', page, re.S).group(0)
    m = re.search(r"<dt>Cash</dt><dd><strong>(.*?)</strong>", panel)
    v = 0 if m and m.group(1) == "$0.00" else -dollars(m.group(1)) if m else None
    check(f"desk #{tid} Actual cash line = DB", v == PER[tid], m.group(1) if m else "missing")

# ---- resolved_tickets.json -------------------------------------------------
rt = json.loads((OUT / "resolved_tickets.json").read_text())
check("json cash start/paid/end = DB", (c(rt["cash"]["start"]), c(rt["cash"]["paid_out"]), c(rt["cash"]["end"])) == (START, PAID, END))
check("json cash_accounts_checking = DB", c(rt["cash"]["cash_accounts_checking"]) == END and rt["cash"]["end_matches_cash_accounts"] is True)
check("json per-ticket cash_change = DB", {t["id"]: -c(t["cash_change"]) for t in rt["tickets"]} == PER)
check("json payments = DB rows", [(p["payment_id"], p["kind"], p["ref_id"], c(p["amount"])) for p in rt["cash"]["payments"]]
      == [(p[0], p[1], p[2], c(p[3])) for p in pays])
ap_json = {a["approval_id"]: a for t in rt["tickets"] for a in t["human_approvals"]}
check("json approvals = DB (status, amount, payment)",
      sorted((k, a["decision"], c(a["amount"]), a["payment_id"]) for k, a in ap_json.items()) == sorted((a[0], a[4], c(a[3]), a[5]) for a in apps))
check("json checking_after per approval follows the decision order",
      {k: c(a["checking_after"]) for k, a in ap_json.items()} == {3: 100000, 1: 16000, 2: 15200, 4: 15200, 5: 15200, 6: 15200})

# ---- resolved_board.html ---------------------------------------------------
board = (OUT / "resolved_board.html").read_text()
cards = re.findall(r'<span class="tid">#(\d+)</span>.*?<span class="chg">Cash (.*?)</span>', board, re.S)
check("board cards cash = DB", {int(t): (0 if v == "$0.00" else -dollars(v)) for t, v in cards} == PER, str(cards))
line = text_of(re.search(r'<p class="cash">(.*?)</p>', board, re.S).group(1))
nums = [dollars(x) for x in re.findall(r"\$[\d,]+\.\d\d", line)]
check("board cash line start/end/paid = DB", nums == [START, END, PAID], line[:120])

if "--json" in sys.argv:
    Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps([{"name": n, "passed": ok, "detail": str(d)} for n, ok, d in results], indent=1, ensure_ascii=False))
failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
raise SystemExit(1 if failed else 0)
