# HARNESS — Campus Customs Multi-Agent Operations

**What this is.** Campus Customs is a Yale merch shop. HW 5 builds the shop's
Multi-Agent Operations team. Tickets (customer orders, rent, unpaid bills,
discount requests) land on a board. Five agents (Boss, Inventory, Accounting,
Facilities, Customer service) work them in a FastAPI backend, using tools
served by a separate MCP server, while a human watches and approves on a React
dashboard. This document describes the system around those agents and grows
problem by problem.

| § | Covers |
|---|---|
| 1 | Problem 2: the database, every table and field, and how the open tickets link to it |
| 2 | Problem 3: the MCP server and its first three tools |
| 3 | Problem 5: the agent team, every MCP tool and the tables it uses, the audit trail, and safety |
| 4 | Problem 7: the backend API routes (`backend/main.py`) |
| 5 | Problem 8: the operations dashboard (`frontend/`) |
| 6 | Problem 9: the full run over tickets 101-103, the cash, and the audit trail |

**Where to find each part of the system**

| Part | Where |
|---|---|
| Tables: every field, how they link, and the four tables the server adds | §1.2–1.4, §3.3 |
| MCP tools: all 17, the tables each uses, and who may call it | §2, §3.2 (arguments and refusals in `mcp_server/README.md`) |
| The five agents: job, prompt, tools, and delegation rules | §3, §3.1 |
| API routes | §4 |
| The dashboard | §5 (the look and why: `output/design.md`) |
| Safety: the shop rules and where each is enforced, guardrails, token limits | §3.5 |
| The full run: what happened, the cash, the audit trail | §6 |

---

## 1. The database (Problem 2)

### 1.1 The original and the working copy

| File | Role |
|---|---|
| `data/campus_customs.db` | The original. Never written to. It is the reset source. |
| `data/campus_customs_new.db` | The working copy. Every tool uses this file. Lookup tools only read it; the Problem 5 write tools change it (§3.2). |

The working copy was made with `cp -p data/campus_customs.db
data/campus_customs_new.db`. When it was made, both files had the same SHA-256
hash, and `PRAGMA integrity_check` on the copy returned `ok`. The working copy
changes as tickets are worked. Each reset (`POST /api/reset` or
`backend/agents.py --reset`) restores the original's hash and logs it in a
`db_reset` entry. `cp -p` keeps the original's timestamps, so compare
the SHA-256 hashes, not file dates, to confirm a reset.

The MCP server (§2) uses the working copy by default. The `CAMPUS_DB_PATH`
setting can point it at another file, but it refuses to open the original. The
agent backend (§3) reads and changes the database only through the MCP
server's tools, and `backend/agents.py --reset` performs the reset.

### 1.2 Tables and fields

Nine tables. The values shown are the **starting values**, which the tools will
change in the working copy. "Today" for the shop is `desk.date_today` =
**2026-08-31**.

**Dates.** `desk.date_today`, `invoices.due_date`, `leases.next_due` and
`cash_accounts.date` are `YYYY-MM-DD` text, so they compare correctly as
strings. `tickets.created_at` is a timestamp with a time-zone offset, so only
its first 10 characters (`date(created_at)`) should be compared with
`date_today`.

#### `desk` (1 row, no primary key)

| Field | Type | Starting value / notes |
|---|---|---|
| `date_today` | TEXT, required | `2026-08-31` |
| `notes` | TEXT | NULL |

**Why it matters:** every agent judges "overdue" and "days until due" against this date, never the computer's clock.

Nothing in the schema limits `desk` to one row, so tools only read it and never insert into it.

#### `tickets` (3 rows)

| Field | Type | Starting value / notes |
|---|---|---|
| `id` | INTEGER, primary key | 101, 102, 103 |
| `type` | TEXT, required | `customer_order`, `rent_notice`, `price_override` |
| `requester` | TEXT, required | Who opened it: a customer, the landlord, a student org |
| `subject` | TEXT, required | Short title for the board |
| `sku` | TEXT | Product involved, if any |
| `size` | TEXT | Size involved, if any |
| `qty` | INTEGER | Units asked for |
| `lease_id` | INTEGER | Lease involved, if any |
| `invoice_id` | INTEGER | Invoice involved, if any |
| `status` | TEXT, required | All `open` |
| `notes` | TEXT | Free-text summary of the request |
| `created_at` | TEXT, required | Timestamp with offset, e.g. `2026-08-31T09:15:00-04:00` |

**Why it matters:** this is the board the Boss reads, and its link fields send each agent to the stock, lease or invoice involved.

#### `inventory` (10 rows, primary key `sku` + `size`)

| Field | Type | Starting value / notes |
|---|---|---|
| `sku` | TEXT, required | 4 products, e.g. `CC-TEE-WHITE` |
| `name` | TEXT, required | e.g. `Classic Bulldog Tee` |
| `size` | TEXT, required | `S`, `M`, `L`, `XL`, or `OS` (one size) |
| `qty` | INTEGER, required | Units on hand |
| `location` | TEXT, required | Aisle in the shop |

**Why it matters:** the Inventory agent checks stock here by SKU and size to spot shortfalls.

#### `pricing` (4 rows)

| Field | Type | Starting value / notes |
|---|---|---|
| `sku` | TEXT, primary key | One row per product, not per size |
| `unit_cost` | REAL, required | What the shop pays per unit |
| `list_price` | REAL, required | What the shop charges per unit |

**Why it matters:** Accounting compares cost with price here to check margins and to cost any purchase order.

#### `vendors` (3 rows)

| Field | Type | Starting value / notes |
|---|---|---|
| `id` | INTEGER, primary key | 1, 2, 3 |
| `name` | TEXT, required | Bulldog Print Co, Elm City Gifts, QuickShip CT |
| `specialty` | TEXT, required | `apparel reprint`, `mugs and small goods`, `local courier` |
| `lead_days` | INTEGER, required | 5, 3, 1 |

**Why it matters:** the Inventory agent picks a restock vendor here and takes the lead time from `lead_days`.

#### `invoices` (1 row)

| Field | Type | Starting value / notes |
|---|---|---|
| `id` | INTEGER, primary key | 501 |
| `vendor_id` | INTEGER, required | 1 (Bulldog Print Co) |
| `amount` | REAL, required | 840.00 |
| `due_date` | TEXT, required | `2026-08-28` |
| `status` | TEXT, required | `open`. Free text with no list of allowed values. The tools treat any status other than `paid` as unpaid (§2). |
| `description` | TEXT | `Rush reprint CC-TEE-WHITE S` |

**Why it matters:** Accounting tracks what the shop owes here, and an open invoice stops that vendor shipping anything new.

#### `leases` (1 row)

| Field | Type | Starting value / notes |
|---|---|---|
| `id` | INTEGER, primary key | 1 |
| `space_name` | TEXT, required | `Chapel Street shop` |
| `landlord` | TEXT, required | `Elm City Properties` |
| `monthly_rent` | REAL, required | 2400.00 |
| `next_due` | TEXT, required | `2026-09-02` |
| `notes` | TEXT | NULL |

**Why it matters:** Facilities reads the rent and its due date here, and a rent payment has to update this row.

#### `cash_accounts` (1 row)

| Field | Type | Starting value / notes |
|---|---|---|
| `name` | TEXT, primary key | `checking` |
| `balance` | REAL, required | 3400.00 |
| `date` | TEXT, required | `2026-08-31`, the as-of date of the balance (same as `desk.date_today`) |

**Why it matters:** Accounting checks this balance before any payment; it is the only money the shop has, and it can never go negative.

#### `payments` (0 rows)

| Field | Type | Starting value / notes |
|---|---|---|
| `id` | INTEGER, primary key | |
| `kind` | TEXT, required | What was paid (values set by our tools, e.g. invoice or rent) |
| `ref_id` | INTEGER | Id of the paid invoice or lease, depending on `kind` |
| `amount` | REAL, required | |
| `account` | TEXT, required | Which cash account paid |
| `paid_at` | TEXT, required | When it was paid (format set by our tools) |
| `approved_by` | TEXT, required | Who approved it. It is required, so only approved payments can be stored here. |

**Why it matters:** a payment is written here only when a human approves a request on the dashboard (`approve_request`). The same transaction lowers `cash_accounts.balance` by the same amount. Accounting can only file the request; it cannot write to this table.

### 1.3 How the tables link

```
tickets.invoice_id ──▶ invoices.id                   (foreign key, not enforced)
invoices.vendor_id ──▶ vendors.id                    (foreign key, not enforced)
tickets.lease_id   ──▶ leases.id                     (foreign key, not enforced)
tickets.sku + size ──▶ inventory (sku, size)         (no foreign key)
tickets.sku        ──▶ pricing.sku                   (no foreign key)
inventory.sku      ──▶ pricing.sku                   (no foreign key)
payments.ref_id    ──▶ invoices.id or leases.id      (no foreign key; picked by payments.kind)
payments.account   ──▶ cash_accounts.name            (no foreign key)
desk.date_today        the date every due-date check uses
```

**Gaps the tools have to cover.** These were noted in Problem 2; Problem 5
closes most of them (§3.3).

- **Links are not checked by the database.** Only three links have a declared
  foreign key, and SQLite does not enforce even those unless each connection
  runs `PRAGMA foreign_keys = ON`. The setting does not persist in the file.
  The other links have no key, so the tools must check that an id exists before
  acting on it.
- **No SKU-to-vendor column.** The only data link is invoice 501's description,
  which names `CC-TEE-WHITE S` on a Bulldog Print Co bill. For any other SKU the
  vendor has to be inferred from `vendors.specialty`:
  - The hoodie fits "apparel reprint" (Bulldog Print Co).
  - The mug fits "mugs and small goods" (Elm City Gifts).
  - The cap could fit either.
  - QuickShip CT is a "local courier" with `lead_days` 1. Whether it can supply
    stock or only deliver it is an open question.
- **No purchase-order table.** Accounting prepares purchase orders, but there is
  nowhere to store one yet.
- **No pending-approval state.** `payments.approved_by` is required, so a
  payment waiting for a human cannot be stored in `payments`.
- **No place for customer-message drafts.** `tickets.notes` is the only free
  text on a ticket.
- **No discount policy.** `pricing` gives only cost and list price.

### 1.4 The three open tickets

All three were opened on 2026-08-31, the shop's today.

**Ticket 101: customer order** (Tauhid Zaman, "Bulldog tee")
- Wants 1 `CC-TEE-WHITE` (Classic Bulldog Tee) in size **S**. Inventory has
  **0** in S (M 5, L 3, XL 2), so it is short 1. Cost $8.00, list price $28.00.
- Links to invoice **501**: Bulldog Print Co, **$840**, due 2026-08-28, still
  `open`, so **3 days overdue**.
- Invoice 501 is itself for a "Rush reprint CC-TEE-WHITE S", the exact item and
  size this customer wants. The data does not say whether that reprint has
  arrived or is waiting on payment.
- Bulldog Print Co will not ship anything new while invoice 501 is open. Its
  lead time is 5 days, so an order placed today (2026-08-31) would arrive
  2026-09-05 at the earliest.

**Ticket 102: rent notice** (Elm City Properties, "Rent due")
- Links to lease **1**: Chapel Street shop, **$2,400**, next due
  **2026-09-02**. That is 2 days after today, so it is not yet overdue, which
  matches the note "rent due in 2 days".
- Not paid yet. The only cash account is `checking`, holding $3,400.

**Ticket 103: price override** (Yale AI Club, "Bulk hoodie discount")
- Wants 20 `CC-HOOD-NAVY` (Basic Hoodie Big Yale) in size **M** at a bulk
  discount. Inventory has **8** in M (S 4, L 14, XL 6), so it is short 12.
- Cost $22.00, list price $58.00: a $36.00 (62%) margin per unit at list. The
  data sets no discount limit.
- No link to a vendor or invoice. By specialty the likely restock vendor is
  Bulldog Print Co, which would also be blocked by invoice 501.

**What ties them together.**
- **One vendor.** Tickets 101 and 103 both lead to Bulldog Print Co, which is
  blocked while invoice 501 is open.
- **One cash account.** Every payment comes from the same $3,400, and the
  tickets add up to more than that:

  | Item | Cost |
  |---|---|
  | Rent | $2,400 |
  | Invoice 501 | $840 |
  | 12 hoodies at unit cost | $264 |
  | 1 tee at unit cost | $8 |
  | **Total** | **$3,512** |

  The total is $112 more than the shop has. Even if invoice 501 already covers
  the tee, the total is $3,504. Which to pay first is a decision for later
  problems.
- **Human approval.** Any payment (rent, invoice 501 or a purchase order) needs
  a human's sign-off on the dashboard.

The Crest Mug (`CC-MUG-CREST`) is also at 0, but no ticket asks for it.

---

## 2. The MCP server (Problem 3)

`mcp_server/server.py` is a FastMCP server that every agent uses for shop data
(see `mcp_server/README.md`). It speaks MCP over stdio.

**How it handles data**
- **Which file:** it opens `data/campus_customs_new.db`, or the file named in
  `CAMPUS_DB_PATH` (a relative path is read from the project root). It refuses
  to open the original `data/campus_customs.db`, even under a different-case
  spelling or a hard link. A missing file is reported, never created empty.
- **Read-only:** the three tools only look things up, so each opens the
  database read-only (`mode=ro`) and cannot change it. Each connection also
  turns on `PRAGMA foreign_keys` (§1.3).
- **No invented data:** a tool returns database values plus simple arithmetic
  on them: shortfall, margin, days overdue, days until due.
  - The one value that applies a rule is `vendor_blocked`. It encodes the shop
    rule that a vendor will not ship while it has an unpaid invoice.
  - `invoices.status` is free text, so any status other than `paid` counts as
    unpaid. A typo can never unblock a vendor.
  - A missing SKU, size, invoice or lease returns an error that names it and
    lists the valid SKUs or sizes. A missing pricing or vendor row comes back
    as `null`. No value is ever filled in.
- **Dates:** "overdue" and "days until due" use `desk.date_today`, never the
  computer's clock, and both dated tools return it.

### 2.1 The three tools

**`check_invoice(invoice_id)`**
- **Reads:** `invoices`, `vendors`, `desk`
- **Ticket:** 101 (customer order for 1 Classic Bulldog Tee, size S)
- **Why it is the right tool:** Ticket 101 links to invoice 501, and this tool
  shows that the $840 Bulldog Print Co bill for the "Rush reprint CC-TEE-WHITE
  S" is unpaid and 3 days overdue, with `vendor_blocked: true`, meaning the tee
  reprint vendor will not ship anything new until that bill is paid.

**`check_lease(lease_id)`**
- **Reads:** `leases`, `desk`
- **Ticket:** 102 (rent notice from Elm City Properties)
- **Why it is the right tool:** Ticket 102 is only an email saying rent is due
  in 2 days, and this tool checks it against lease 1 itself ($2,400 to Elm City
  Properties, due 2026-09-02, 2 days after the shop's today, not overdue), so
  Facilities acts on the lease record rather than the email.

**`check_stock_and_price(sku, size, qty_needed)`**
- **Reads:** `inventory`, `pricing`
- **Ticket:** 103 (Yale AI Club wants 20 Basic Hoodie Big Yale, size M, at a
  bulk discount)
- **Why it is the right tool:** Ticket 103 cannot be answered until the team
  knows whether 20 size M hoodies exist (only 8 do, so it is 12 short) and how
  far the $58 list price can drop before it reaches the $22 unit cost, and this
  one call returns both.

### 2.2 What each tool returns

These are the starting values, from calling each tool on the working copy.
The last row shows the same stock tool also confirming ticket 101's shortfall.

| Call | Key result |
|---|---|
| `check_invoice(501)` | status `open`, `is_overdue: true`, `days_overdue: 3`, vendor Bulldog Print Co (lead 5 days), `vendor_unpaid_total: 840.0`, `vendor_blocked: true` |
| `check_lease(1)` | `monthly_rent: 2400.0`, `next_due: 2026-09-02`, `days_until_due: 2`, `is_overdue: false` |
| `check_stock_and_price("CC-HOOD-NAVY", "M", 20)` | `qty_on_hand: 8`, `shortfall: 12`, `can_fill_from_stock: false`, cost 22.0, list 58.0, margin 36.0 (62.1%) |
| `check_stock_and_price("CC-TEE-WHITE", "S", 1)` | `qty_on_hand: 0`, `shortfall: 1`, `can_fill_from_stock: false` |

**What else was tested**
- **Errors:** unknown ids, SKUs and sizes all returned errors.
- **Bad data on scratch copies:** odd invoice statuses, bad dates, a second
  `desk` row, and empty or non-database files each gave the expected result or
  a clear error.
- **Database files:** they had the same SHA-256 before and after every test.
- **Stdio:** the server also answered over a real stdio connection.

**Not covered yet.** These three tools do not read the ticket board, look up a
vendor without an invoice id (ticket 103's restock), read cash, or write
anything (payments, purchase orders, drafts). Problem 5 added them (§3.2).

---

## 3. The agent team (Problem 5)

Five PydanticAI agents work the tickets. Every agent uses **gpt-6-luna through
Portkey** (`PORTKEY_API_KEY`, read from the nearest `.env`). Every shop fact
comes from the MCP server (§2) over `data/campus_customs_new.db`, and the
backend adds no shop tools of its own.

The agents call the model through OpenAI's Responses API with reasoning effort
`low`. Portkey's gpt-6-luna refuses tool calls combined with reasoning on the
chat-completions endpoint, so the Responses API is needed.

| File | What it holds |
|---|---|
| `backend/agents.py` | The five agents, the Portkey model, the per-run MCP connection, `ask_agent` (delegation), the audit hooks, the limits, `run_ticket()`, and the command line |
| `backend/models.py` | The data types: `AgentReport`, `BossDecision`, `Fact`, `TeamDeps`, `RunState`, `TicketRun` |
| `backend/audit.py` | The append-only audit trail (`output/audit_trail.json`) |
| `backend/prompts/*.md` | One system prompt per agent |

**How a ticket runs.** `run_ticket(ticket_id)` starts its own MCP server
process, which exits when the run ends, and gives the ticket to the Boss. The
Boss reads it with `get_ticket` and delegates with `ask_agent`. Each teammate
runs its own loop (model call, tool calls, repeat) and hands back an
`AgentReport`. The Boss sets the board status and returns a `BossDecision`.

**A full run starts from the original data**, as the shop rules require:

```bash
.venv/bin/python backend/agents.py --reset 101 102 103
```

- **Reset:** `--reset` copies `data/campus_customs.db` over the working copy
  and logs a `db_reset` entry. Without it, the command warns if the working
  copy already holds earlier changes.
- **Order:** tickets run one after another, so two tickets never race for the
  same cash.

### 3.1 The agents

Every agent also has `ask_agent(agent, request)`, so any agent can delegate to
any other (full connectivity).

| Agent | Job | Prompt | MCP tools it can call | Returns |
|---|---|---|---|---|
| **Boss** | Reads each ticket, decides who works on it, makes the final call, sets the board status | `prompts/boss.md` | `list_tickets`, `get_ticket`, `list_approvals`, `list_drafts`, `check_cash`, `update_ticket_status` | `BossDecision` (an `AgentReport` if a teammate asks it) |
| **Inventory** | Stock by SKU and size, shortfalls, which vendor can restock and when | `prompts/inventory.md` | `get_ticket`, `check_stock_and_price`, `list_vendors`, `check_invoice` | `AgentReport` |
| **Accounting** | Cash, invoices and margins; prepares payments, purchase orders and price overrides for human approval | `prompts/accounting.md` | `get_ticket`, `check_cash`, `list_unpaid_invoices`, `check_invoice`, `check_lease`, `check_stock_and_price`, `list_vendors`, `list_approvals`, `request_payment`, `create_purchase_order`, `request_price_override` | `AgentReport` |
| **Facilities** | The shop space: leases, rent, the landlord | `prompts/facilities.md` | `get_ticket`, `check_lease`, `list_approvals` | `AgentReport` |
| **Customer Service** | Drafts messages to customers and other requesters (never sends) | `prompts/customer_service.md` | `get_ticket`, `list_drafts`, `check_stock_and_price`, `save_customer_draft` | `AgentReport` |

**Delegation (`ask_agent`)**
- **What a teammate gets:** the asked agent gets the ticket id, who is asking,
  and the request. It cannot see the asker's conversation, so the request must
  carry what it needs.
- **Refused asks:** the backend refuses delegating to yourself, going deeper
  than depth 2 (Boss → agent → agent), and more than 8 delegations per ticket.
  A refusal comes back as a message, and it is logged.
- **Failures:** if a teammate fails, the asker gets a short error instead of
  crashing.

**What the backend checks on every MCP call** (`_check_and_stamp`)
- **Ownership:** the tool must be this agent's.
- **Ticket scope:** write tools may only change the ticket being worked.
- **Status:** only the Boss at the top of the run may set ticket status.
- **Real name:** the real agent's name replaces any `actor` the model sent.
- **The Boss's decision:** it must name this ticket and carry the same status
  the Boss set on the board, or it is sent back.

### 3.2 Every MCP tool and the tables it uses

| Tool | Kind | Tables | Agents that can call it |
|---|---|---|---|
| `list_tickets` | read | `tickets`, `desk` | Boss |
| `get_ticket` | read | `tickets`, `ticket_updates`, `drafts`, `approvals`, `desk` | all five |
| `check_stock_and_price` | read | `inventory`, `pricing` | Inventory, Accounting, Customer Service |
| `check_invoice` | read | `invoices`, `vendors`, `desk` | Inventory, Accounting |
| `check_lease` | read | `leases`, `desk` | Accounting, Facilities |
| `list_vendors` | read | `vendors`, `invoices`, `desk` | Inventory, Accounting |
| `list_unpaid_invoices` | read | `invoices`, `vendors`, `desk` | Accounting |
| `check_cash` | read | `cash_accounts`, `approvals`, `payments`, `desk` | Boss, Accounting |
| `list_approvals` | read | `approvals` | Boss, Accounting, Facilities |
| `list_drafts` | read | `drafts` | Boss, Customer Service |
| `request_payment` | write (request) | writes `approvals`; reads `tickets`, `invoices` or `leases`, `vendors`, `cash_accounts`, `desk` | Accounting |
| `create_purchase_order` | write (request) | writes `purchase_orders`, `approvals`; reads `tickets`, `vendors`, `inventory`, `pricing`, `invoices`, `cash_accounts`, `desk` | Accounting |
| `request_price_override` | write (request) | writes `approvals`; reads `tickets`, `pricing`, `desk` | Accounting |
| `save_customer_draft` | write | writes `drafts`; reads `tickets` | Customer Service |
| `update_ticket_status` | write | writes `tickets.status`, `ticket_updates`; reads `approvals` | Boss |
| `approve_request` | **human only** | writes `approvals`, `payments`, `cash_accounts`, plus `invoices.status`, `leases.next_due` or `purchase_orders`; reads `pricing`, `vendors`, `desk` | none |
| `reject_request` | **human only** | writes `approvals`, `purchase_orders` | none |

The two human-only tools exist only in a server process started with
`CAMPUS_HUMAN_TOOLS=1`: the API's desk connection, used by the approve and
reject routes (§4). The agents'
server process and Claude Code's (`.mcp.json`) do not have them at all.
`mcp_server/README.md` gives each tool's arguments and refusals.

### 3.3 Tables the server adds, and the conventions it uses

The original data has no place for requests, orders, drafts or board history
(§1.3). The first time a **write** tool runs on a working copy, the server adds
four tables. Lookups read them as empty until then, so lookups never change the
file. Resetting the working copy removes the tables.

| Table | Holds |
|---|---|
| `approvals` | Every request for a human: `kind` (`invoice_payment`, `rent_payment`, `purchase_order`, `price_override`), `ref_id`, `amount` (cash that leaves if approved; 0 for a price override), a JSON snapshot of the details, `reason`, `requested_by`, `status`, and who decided and when |
| `purchase_orders` | Restock orders: vendor, SKU, size, qty, `unit_cost`, `total`, `status` (`pending_approval`, `ordered`, `rejected`), `expected_arrival` |
| `drafts` | Customer messages, always `status = 'draft'` |
| `ticket_updates` | The board history: each status change, its note and the agent that set it |

**Approval statuses**
- `pending`: waiting for a human.
- `approved`
- `rejected`
- `stale`: the invoice, lease or price changed after the request was filed.
  Approval was refused, nothing was paid, and a fresh request is allowed.

**Conventions (our rules, since the data sets none)**
- **Invoices:** an approved invoice payment sets `status = 'paid'`. Any other
  status counts as unpaid.
- **Rent:** an approved rent payment moves `next_due` one calendar month on. A
  due date on the last day of a month stays on the last day.
- **Purchase orders:** a PO costs `qty × pricing.unit_cost` and is paid when
  approved. Its expected arrival is `date_today + vendors.lead_days`.
- **Discounts:** a price override must be at least `unit_cost` and below
  `list_price`, and it moves no cash.
- **Amounts:** every payment must be positive (cash only goes out).
- **Resolved tickets:** a resolved ticket takes no new money requests.
- **Restock vendor:** still chosen by Inventory from `vendors.specialty`.

### 3.4 The audit trail (`output/audit_trail.json`)

`backend/audit.py` appends one JSON object per agent-loop step **as it
happens**. The file is a JSON array that only grows. Every entry has `seq`,
`ts` (UTC) and `event`. Run entries also have `run_id` and `ticket_id`.
`db_reset` has neither, and `human_decision` has a `ticket_id` but no
`run_id`. Agent steps add `agent`, `depth`, `chain` (who asked whom) and
`step`.

| Event | Records |
|---|---|
| `db_reset` | The working copy was reset from the original (with its hash) |
| `run_start` | Ticket, model, database file the server uses, every limit |
| `agent_start` | The agent and the exact request it was given |
| `model_step` | One model call: the tools it asked for, with arguments (or its final answer), any text, `finish_reason`, tokens (input, cached, output), team usage so far (this request included), time |
| `tool_call` | One tool call: tool, arguments as sent to the server (with the stamped `actor`), `ok`, `error` or `cancelled`, the result or error, time |
| `call_refused` | A call refused before any tool ran, with what the model was told. Covers a tool the agent does not have, bad arguments, and a final answer that failed a check (e.g. a decision that did not match the board) |
| `delegation` / `delegation_refused` / `delegation_failed` | Who asked whom for what, delegations left, or why it was refused or failed |
| `agent_end` | The agent's output, or why it stopped (`usage_limit`, `error`), and team usage |
| `model_error` | A failed model call |
| `run_end` | Stop reason (`completed`, `usage_limit`, `error`, `cancelled`), delegations used, the status set on the board, total usage, and the Boss's decision. It is written even when a run is cancelled. |
| `human_decision` | A human's approve or reject on the dashboard, written by `backend/main.py`. Records the approval id, decision, `decided_by`, outcome (`done` or `refused`), kind and amount. A payment also records its `payments` row, `cash_balance_after` and what changed. |

**How the file stays append-only**
- **Locking:** each append takes a lock, so two runs never collide. The lock
  across processes needs macOS or Linux.
- **Atomic writes:** it writes the whole array to a temporary file and swaps it
  in, so the file is never half-written.
- **Nothing is deleted:** old entries are never removed or rewritten. A file
  that is not valid JSON or UTF-8 is renamed aside, never overwritten.
- **No trail, no run:** if the trail cannot be written, the run does not start.
- **Clipping:** strings over 4,000 characters are clipped and marked as
  clipped.
- **Location:** `CAMPUS_AUDIT_PATH` points it elsewhere (the tests use that).

### 3.5 Safety

**The shop rules, and where each is enforced.** The rules live in the tools
and the backend, not only in the prompts, so a model that ignores its prompt
still cannot break them.

| Shop rule | Enforced by | How it held in the full run (§6) |
|---|---|---|
| `desk.date_today` is "today"; overdue is judged by it | Every dated tool returns `date_today` and computes `days_overdue` or `days_until_due` from it; prompts forbid the real clock | Invoice 501 was "3 days overdue" and the rent "2 days away", both from 2026-08-31 |
| Vendor lead times come from `vendors` | `list_vendors` and `create_purchase_order` give arrival as `date_today + lead_days` | PO 1's expected arrival is 2026-09-05 (5 lead days) |
| A vendor with an open unpaid invoice will not ship | `vendor_blocked` in the tools; `approve_request` refuses a PO while its vendor has an unpaid invoice | The tee PO could only be approved after invoice 501 was paid; the board kept its button locked |
| A human approves every payment, and the paid table is updated | Agents can only file requests. `approve_request` exists only in the desk's server process, and it writes `payments`, `cash_accounts` and the invoice, lease or PO in one transaction | 3 payments, each tied to an approval decided by a named human; invoice 501 is `paid`, lease 1's `next_due` moved on, PO 1 is `ordered` |
| Not enough cash: the pay tool refuses | `_pay` refuses any payment larger than the balance | The $264 hoodie PO could not fit with $152 left. The approver rejected it (note: "no money") rather than trying it, and the cash replay check (`tests/cash/replay_check.py`) shows the refusal |
| Cash only goes out | Payments must be positive, and no tool adds money | Checking only fell: $3,400.00 → $152.00 |
| Reset before a full run | `POST /api/reset` and `agents.py --reset` copy the original over the working copy (atomic swap) and log `db_reset` | Reset at audit seq 323, with the original's hash |
| Never email customers or call vendors; drafts stay on the board | There is no send tool; `save_customer_draft` only saves | 4 drafts, all `draft`, none sent |
| Only gpt-6-luna through Portkey | One model, built in `backend/agents.py` from `PORTKEY_API_KEY` | Every `run_start` records `gpt-6-luna` |
| Never invent data | Tools return database values; a missing row is an error; every `Fact` names its source tool | All 45 facts in the Boss's decisions name a source: a tool, or a teammate and its tool |
| Keep `data/campus_customs.db` untouched | The server refuses to open it; resets only read it | Its SHA-256 is unchanged (`23686a90…`) |

**Guardrails for real customers and real money**
- **A human approves every payment.** Agents can only request a payment, a
  purchase order or a discount. The two tools that settle a request
  (`approve_request`, `reject_request`) are not registered in the agents'
  server process or Claude Code's. The backend also refuses any tool not on an
  agent's list. The approver's name may not resemble an agent's ("Accounting
  agent", "B o s s" and words like "bot" or "GPT" are refused).
- **Money rules live in the tool, not the prompt.**
  - Cash never goes negative.
  - Payments must be positive.
  - A PO is refused while its vendor has an unpaid invoice.
  - A request is marked stale, and nothing is paid, when the data behind it
    changed: the invoice amount, the rent amount or due date, the PO's unit
    cost, or a price override that would now be below cost.
  - Each payment updates the ledger, cash, and the invoice, lease or order in
    one transaction.
  - Amounts come from the database, never from the model.
  - Duplicate pending payment requests are refused on any ticket. A duplicate
    PO for the same item is refused on the same ticket; open orders for the
    item on other tickets are shown.
- **Nothing reaches a customer.** There is no send tool, and messages are saved
  as drafts for a human. A discount can never go below unit cost and needs
  approval. Prompts forbid putting an unapproved price, date or timeframe in a
  draft.
- **Scope.**
  - Writes may only change the ticket being worked.
  - Only the top-level Boss sets status, and its decision must match the board.
  - A ticket cannot be marked resolved while a payment it depends on is
    pending, even one filed on another ticket.
- **No invented facts.** Tools return database values, and a missing row is an
  error that names it. Prompts require every number to come from a tool, and
  `Fact.source` records which one.
- **Ticket text is data.** Prompts tell agents to ignore instructions inside
  ticket notes or tool results (prompt injection).
- **Least privilege:**
  - Each agent sees only its tools.
  - The backend writes the real agent name into every write.
  - The MCP server gets no model API keys.
  - The original database cannot be opened.
- **Everything is on the record.** Every model call, tool call, refusal and
  delegation is in the append-only audit trail.
- **What a real deployment would add:**
  - Signed-in approvers, with a two-person rule above a dollar limit.
  - Daily payment caps.
  - Checks on vendor bank details.
  - Alerts on refused or unusual requests.
  - An approval secret on the human-only server.

**Limits that keep token use in check.** These apply to each ticket and are
shared by the whole team. Each can be changed with a `TEAM_*` environment
variable (see `.env.example`).
- **Where agents see them:** the prompts state the defaults. A "## This run"
  note in every agent's instructions gives the live values, and it overrides
  the prompts.
- **When they are checked:** limits are checked before each request. With
  delegations running in parallel, the team can overshoot by about one request
  per agent running at the same time.

| Limit | Default | Why |
|---|---|---|
| Model requests | 40 | Caps the loop across all five agents |
| Tool calls | 60 | Caps MCP calls and delegations |
| Total tokens | 300,000 | The spend ceiling per ticket |
| Output tokens per response | 8,000 | Stops a runaway answer (reasoning included). It was 3,000 until the full run (§6), where a reasoning-heavy final answer hit it |
| Reasoning effort | `low` | Keeps hidden reasoning tokens small |
| Delegations | 8 | Stops agents passing work around |
| Delegation depth | 2 | Boss → agent → agent, no deeper chains |
| Tool retries | 2 | A failing call or answer cannot loop |

**Other ways the team saves tokens**
- **Short tool lists:** each agent's tool list is short, and the `actor`
  argument is hidden from the model, so every request carries a smaller
  schema.
- **One ticket at a time:** tickets run one after another.
- **Clean stops:** when a limit is hit, the run stops and records why in the
  trail.

### 3.6 How it was tested

All tests ran on scratch copies of the original database, with a scratch audit
file (`CAMPUS_DB_PATH`, `CAMPUS_AUDIT_PATH`). The working copy and
`output/audit_trail.json` were not touched. The original database's SHA-256 was
unchanged.

**1. MCP tools (no model).** A scripted client ran 65 checks, and all passed.
They covered the whole approval flow and every guard:
- **Requests:** duplicate requests, unknown tickets, vendors and agent names,
  and prices below cost or not below list were refused.
- **Blocked vendor:** the PO was refused while invoice 501 was unpaid, and went
  through after it was paid.
- **No negative cash:** the $2,400 rent was refused with $2,296 left, and
  nothing changed.
- **Rent:** an approved payment moved `next_due` from 2026-09-02 to 2026-10-02.
  Month-end dates stayed month-end.
- **Stale requests:** a changed invoice amount, PO unit cost or override price
  marked the request stale, and a fresh request was then allowed.
- **Amounts:** a negative amount was refused.
- **Resolved tickets:** they took no new requests, and `resolved` was refused
  while a linked payment was pending on another ticket.
- **Lookups:** on a fresh copy they left the file byte-identical.
- **Human-only tools:** they were absent without `CAMPUS_HUMAN_TOOLS=1`.

**2. Team wiring (no model).** PydanticAI's `FunctionModel` played scripted
agents through `run_ticket`, and all 15 checks passed:
- **Tool lists:** all five agents saw exactly their own tools. None saw
  `approve_request` or the `actor` argument.
- **Real names:** spoofed `actor` values were recorded under the real agent,
  in both the database and the audit.
- **Refusals:** each of these was refused and logged as `call_refused`:
  - a write to another ticket
  - an attempt to call `approve_request`
  - a decision whose status did not match the board
- **Depth:** a delegation past depth 2 was refused.
- **Runs:** two runs in separate event loops both worked. A cancelled run still
  wrote `run_end`.
- **Audit file:** a non-UTF-8 audit file was set aside intact.

**3. Live run (gpt-6-luna).** After all fixes, tickets 101, 102 and 103 ran in
order on a fresh scratch copy:

| Ticket | What the team did | Board status | Usage |
|---|---|---|---|
| 101 | Inventory found 0 in size S. Accounting requested the $840 payment for overdue invoice 501 (it blocks the vendor) and an $8 PO for 1 tee. Customer Service drafted a message: no date or timeframe, and offered sizes M, L or XL with no substitution without agreement. | `waiting_approval` | 3 delegations, 18 requests, ~127k tokens |
| 102 | Facilities matched the notice to lease 1 ($2,400, due 2026-09-02, 2 days out). Accounting requested the rent payment. | `waiting_approval` | 2 delegations, 11 requests, ~75k tokens |
| 103 | Inventory found 8 of 20 in size M. Accounting requested a price override (above the $22 cost) and a $264 PO for 12. Its request to pay invoice 501 again was refused as a duplicate, so it relied on approval 1. Customer Service drafted a reply: the discount is "under review", with no price and no timeframe. | `waiting_approval` | 3 delegations, 20 requests, ~144k tokens |

No money moved. Cash stayed at $3,400, and every payment waits in `approvals`
for a human. Together the pending requests total $3,512, which is $112 more
than the shop has. The human approver has to choose, and the pay step will
refuse whatever does not fit. The audit trail recorded 136 steps (49 model
steps, 51 tool calls, 8 delegations), with one tool error: the refused
duplicate.

An earlier live run, before these fixes, behaved the same way except that the
hoodie draft quoted the proposed price labelled "pending approval". The
Customer Service prompt now forbids any unapproved price in a draft.

---

## 4. The backend API (Problem 7)

`backend/main.py` is a FastAPI app for the React dashboard. Start it from the
`backend/` folder with the project's virtual environment active:
`uvicorn main:app --reload --port 8000`. Interactive docs are at `/docs`.

| Route | What it does |
|---|---|
| `GET /api/health` | Says whether the API can reach the shop's MCP server (`desk: up/down`), with the database, audit file and model it uses, and any run in progress |
| `GET /api/tickets` | The three tickets, each with its board status and `state`: `resolved` only if the Boss set resolved, otherwise `open`. Also which ticket is running |
| `GET /api/tickets/{ticket_id}` | One ticket with its status history, drafts and approval requests |
| `POST /api/tickets/{ticket_id}/run` | Runs the agent team on that ticket. Returns a `run_id` at once (`202`), or waits with `?wait=true` (`200`). Returns `409` if a run is already going |
| `GET /api/runs` | Every run since the server started, newest first, and which one is running |
| `GET /api/runs/{run_id}` | One run: running, or finished with the Boss's decision, usage and stop reason |
| `GET /api/events` | Agent events from the audit trail, oldest first: what each agent said (`said`) and which tools it used (`tools`). For refreshes, pass the returned `last_seq` as `?since=` (`has_more` means call again). Can filter by `ticket_id` and `run_id` |
| `GET /api/approvals` | The requests the agents prepared (payments, purchase orders, discounts), filterable by `status` and `ticket_id` |
| `POST /api/approvals/{approval_id}/approve` | A human (`{"approved_by": "<name>"}`) approves a request. For a payment or PO, this is what actually changes cash. Refused with `409` if cash is short, the vendor is blocked, the request is stale or already decided, or the name is an agent's |
| `POST /api/approvals/{approval_id}/reject` | A human (`{"decided_by": "<name>"}`) rejects a request. Nothing is paid |
| `GET /api/cash` | The checking balance from `cash_accounts`, plus pending requests and what checking would hold if all were approved |
| `POST /api/reset` | Copies `data/campus_customs.db` over the working copy for a fresh run (atomic swap). Refused while a run is going. The audit trail keeps everything and records the reset |

**How it works**
- **Shop data goes through MCP.** Every shop read and change goes through the
  MCP server.
- **The desk connection is the human side.** It is one MCP server process
  started with `CAMPUS_HUMAN_TOOLS=1`, so it is the only place
  `approve_request` and `reject_request` exist. Agent runs start their own
  server without those tools. If the desk process dies, the next call restarts
  it. Reads are retried once; an approval or rejection is never retried
  blindly, and returns `503` so the human checks the board first.
- **One run at a time.** Starting a run and resetting the database share one
  lock. A second run, or a reset, during a run gets `409`, and two Run clicks
  at the same moment start only one run, so tickets never race for cash.
- **The audit trail.**
  - **Events:** agent events come from the trail. `said` is the asker's words
    on a delegation, and an agent's answer at its end: the summary or
    decision, plus recommendation, blockers or human actions. Tool calls carry
    their arguments and results in `detail`.
  - **Human decisions:** each one, done or refused, is added as a
    `human_decision` entry with its ticket.
- **Resolving a ticket.** After a human decides a ticket's requests, run the
  ticket again so the Boss can re-check it. The Boss marks it resolved once
  the shop's part is done: every request it needed is decided and a saved
  draft matches the decisions. A delivery or a customer's reply can still be
  to come (`backend/prompts/boss.md`, section 10; §6.1).
- **Quiet logs.** The board polls every second during a run (every 4 seconds
  when idle), so uvicorn's access log leaves out successful `GET` and
  `OPTIONS` requests. Every `POST` (runs, approvals,
  resets) and every error still prints.
- **Browser access (CORS).** Browsers may call the API from any
  `http://localhost` or `http://127.0.0.1` port (the Vite dev server).
  `CORS_ORIGINS` adds other origins.
- **Status codes:** `404` for an unknown id; `409` when the shop's state says
  no; `422` for bad input; `503` when the MCP server or database is
  unreachable.

**Tested.** There were two suites, both on a scratch database and audit file,
with scripted models standing in for gpt-6-luna. All 53 checks passed.
- **FastAPI TestClient (29 checks):**
  - every route except reject and the runs list
  - status codes `202`, `200`, `404`, `409` and `422`
  - approve moving cash from $3,400 to $1,000
  - agent names refused as approvers
  - double approval refused
  - a cancelled run recorded
  - reset restoring $3,400
- **A real uvicorn server in the test process (24 checks):**
  - two simultaneous Run clicks: one `202`, one `409`
  - resets during a run: `409`
  - four simultaneous resets: all `200`, the file byte-identical to the
    original, no temp files left
  - killing the desk's MCP process: the next call recovers
  - paging with `since` and `limit=5`: every event exactly once
  - the `run_id` filter
  - reject (no cash moved)
  - a blank approver name: `422`
  - CORS from `localhost:5174` allowed and from another site refused
  - no MCP processes left after shutdown

The server was also started with the command above (on a scratch copy) and run
on ticket 102 with gpt-6-luna:
- The run returned `202` at once, and a second run got `409`.
- The run finished `waiting_approval` in about 22 seconds, using about 80k
  tokens.
- `GET /api/events` showed Boss → Facilities (`check_lease`) and
  Boss → Accounting (`check_cash`, `request_payment`).
- Approving moved checking to $1,000 and `next_due` to 2026-10-02.
- Reset brought back $3,400.

---

## 5. The operations dashboard (Problem 8)

`frontend/` is a React + Vite + TypeScript app.
- **Start it:** run `npm install` once, then `npm run dev`. It opens
  `http://localhost:5173` in the browser.
- **Backend:** it calls the routes in §4 at `http://localhost:8000` (set
  `VITE_API_BASE` in `frontend/.env` to change that).
- **CORS:** the backend allows the Vite origin.

`output/design.md` explains the look and why.

| What the board does | How |
|---|---|
| Lists the three tickets | `GET /api/tickets`, with status chips and the number of requests waiting on you |
| Picks a ticket and starts the team | Run button (or `Alt`+`R`) → `POST /api/tickets/{id}/run` |
| Shows each agent and what it is saying or doing during a run | `GET /api/events?since=` every second while a run is going. The team table shows each agent raised (working), sunk (waiting) or hollow (not called). The feed shows handoffs, tool findings and reports |
| Marks a ticket resolved | From the board status. A resolved card sinks into the board with a lime check and the stage gets a RESOLVED stamp. After you decide every request, the chip reads "Ready to close" and the button becomes "Ask the Boss to close". The Boss then re-checks the ticket and sets resolved once the shop's part is done (every request decided, a matching draft saved; §4 and §6.1). In the Problem 9 run all three ended resolved |
| Summarises what each agent did | "Who did what" cards built from every run on the ticket since the last reset: who asked it, what it checked, what it filed, its last words |
| Lets a human approve a payment or purchase | The "Waiting on you" inbox → `POST /api/approvals/{id}/approve` (and reject). Moving cash asks for confirmation first |
| Shows the checking balance | `GET /api/cash`. The balance rolls down when a payment is approved, and a meter shows what pending requests would take |

**How it was checked.** It was tested in the browser against the real API on
a scratch copy of the Problem 5 live run (real agent events), with a scripted
team for live runs, so no tokens were spent:
- approving invoice 501 dropped checking from $3,400 to $2,560, and the $8
  order then cleared its "pay invoice 501 first" block ($2,552)
- "Ask the Boss to close #101" ended with #101 resolved (a scripted team;
  the real run's close run also resolved #101, §6)
- a #102 run showed Boss → Facilities → Accounting live, including a refused
  duplicate request
- reset brought back $3,400
- layouts at 1440, 1024 and 375 px wide

**Review fixes.** Three reviewers then checked the code, the requirements and
accessibility, and `design.md`. Their fixes were each re-checked in the
browser:
- The confirm dialog is a real modal that starts on Cancel and never steals
  focus on refresh.
- A double-clicked Pay records one decision.
- Runs from before a reset are no longer shown as the current story.
- "Who did what" spans every run on the ticket.
- A "Ready to close" chip appears once every request is decided.
- A blocked purchase order's button stays disabled until its invoice is paid.
- Errors behind the API show a banner.
- Shortcuts need `Alt`.
- All five agent seats and all ten lines between them are visible.

---

## 6. The full run (Problem 9)

Problem 9 ran the whole system end to end on fresh data. The database was
reset, the team ran tickets 101, 102 and 103 through the backend's run route
(the one behind the board's Run button), a human decided every request on the board, and each ticket got close runs until it
was resolved.

**Two full runs.** The run described here is the second, on 2026-10-14 (audit
seq 323–558). The first, on 2026-10-13 (seq 92–322), is still in the audit
trail. It left #101 and #103 `in_progress`, because the Boss then resolved a
ticket only once the tee had arrived or the customer had answered, and the
shop's date never moves. Its five decisions were also clicked by Claude Code
on the approver's instruction. Before the second run, the Boss's closing rules
changed (`backend/prompts/boss.md`: section 10's status table and a re-run
step in each playbook), and every decision was clicked by hand.

| File | What it holds |
|---|---|
| `output/desk_tickets.html` | For each ticket, the Problem 6 Expected plan (unchanged) beside the Actual run: who worked, what they delegated, which tools they used, the outcome, and the matches and differences. The Cash tab itemizes the money. The Reflection tab (Problem 10) grades the run, compares it with the plans, and looks at what Campus Customs could do next |
| `output/resolved_tickets.json` | For each ticket: id, final status, a short outcome, what each agent contributed, the human approvals, the drafts and the runs |
| `output/resolved_board.html` | Screenshots of the React board for 101, 102 and 103 at the end. The images are embedded, so it opens with a double-click |
| `output/audit_trail.json` | The run itself, appended as seq 323–558 (236 entries) after the 322 entries already there |
| `output/cash_checks.json`, `tests/cash/` | The three cash checks (§6.4): each check and its result, and the scripts that re-run them |

### 6.1 How it was run

1. **Reset.** The working copy was reset through `POST /api/reset` (the board's
   "Reset shop data" route). The reset is logged as `db_reset` at seq 323, with
   the original's SHA-256 (`23686a90…`). Checking was back to **$3,400.00** and
   `payments` was empty.
2. **First runs.** #101, #102 and #103 were run in that order against the
   backend on port 8000 (gpt-6-luna through Portkey, reasoning `low`, output
   cap 8,000). Each ended `waiting_approval`, with five requests in all.
3. **Human decisions.** Matthew Agurcia clicked each one on the board:
   - approve 3 (rent)
   - approve 1 (invoice 501)
   - approve 2 (the tee order)
   - approve 4 (the hoodie price, $49 × 20)
   - reject 5 (the hoodie restock), with the note "no money"
4. **Close runs.** Each ticket was run again so the Boss could re-check it.
   Under the closing rule, a ticket is resolved when every request it needed
   is decided and a saved draft matches the decisions, even if a delivery or a
   customer's reply is still to come. #101 and #102 were resolved by the Boss
   alone. #103's first close run filed a new request: Accounting judged that
   approval 4 covered 20 hoodies, not the 8 in stock, and asked for approval 6
   ($49 × 8, no cash). The ticket went back to `waiting_approval`.
5. **One more decision.** Matthew Agurcia approved request 6 on the board, and
   #103's second close run saved draft 4 (the 8-hoodie offer) and set it
   `resolved`.

### 6.2 Results

| Ticket | Final status | Outcome | Who worked (delegations) | Cash |
|---|---|---|---|---|
| 101 Bulldog tee | `resolved` | Size S was out of stock (0 of 1). Invoice 501 was paid to unblock Bulldog Print Co, and a 1-tee restock (PO 1) was ordered, arriving 2026-09-05 at the earliest. Draft 1 to Tauhid Zaman was saved, not sent | Boss → Inventory, Accounting, Customer Service; close run: the Boss alone (3) | −$848.00 |
| 102 Rent due | `resolved` | Lease 1 matched the notice. The September rent was paid, and `next_due` moved to 2026-10-02 | Boss → Facilities, Accounting; close run: the Boss alone (2) | −$2,400.00 |
| 103 Bulk hoodie discount | `resolved` | 8 of 20 in stock. $49 × 20 ($980) was approved, and the $264 restock was rejected for cash. A separate $49 × 8 price ($392) was filed and approved, and draft 4 offers the club those 8 | Boss → Inventory, Accounting, Customer Service; close run 1: the same three; close run 2: Boss → Customer Service (7) | $0.00 |

All 12 delegations came from the Boss, and no specialist asked another. No
ticket used every specialist: Facilities never worked on 101 or 103, and
Inventory and Customer Service never worked on 102.

### 6.3 Runs and usage

| Ticket | Run | Agents | MCP calls | Model calls | Tokens | Ended |
|---|---|---|---|---|---|---|
| 101 | first | Boss, Inventory, Accounting, Customer Service | 15 | 18 | 128,465 | completed, `waiting_approval` |
| 102 | first | Boss, Facilities, Accounting | 10 | 13 | 88,868 | completed, `waiting_approval` |
| 103 | first | Boss, Inventory, Accounting, Customer Service | 18 | 20 | 145,615 | completed, `waiting_approval` |
| 101 | close | Boss | 3 | 4 | 30,476 | completed, `resolved` |
| 102 | close | Boss | 3 | 4 | 27,833 | completed, `resolved` |
| 103 | close 1 | Boss, Inventory, Accounting, Customer Service | 12 | 18 | 141,644 | completed, `waiting_approval` |
| 103 | close 2 | Boss, Customer Service | 6 | 9 | 72,724 | completed, `resolved` |
| **All** | 7 runs | 12 delegations | **67** | **86** | **635,625** | |

- **Tokens:** 618,164 input and 17,461 output.
- **Limits:** every run stayed inside every limit. The largest used 20 of 40
  model requests, 20 of 60 tool calls and 145,615 of 300,000 tokens. The
  longest single response was 1,247 output tokens, under the 8,000 cap.
- **Model name:** the model responses report `gpt-6-luna-global`, the
  provider's name for the requested gpt-6-luna. Every `run_start` records
  `gpt-6-luna`.
- **Refused call:** one tool call was refused. On #103, Accounting asked again
  for invoice 501's payment, and the server refused it as a duplicate of
  approval 1.

### 6.4 Cash

| | Checking |
|---|---|
| Start, after the reset | **$3,400.00** |
| Approve 3: rent, lease 1 → payment 1, −$2,400.00 (#102) | $1,000.00 |
| Approve 1: invoice 501, Bulldog Print Co → payment 2, −$840.00 (#101) | $160.00 |
| Approve 2: PO 1, 1 × CC-TEE-WHITE S → payment 3, −$8.00 (#101) | $152.00 |
| Approve 4: price $49 × 20 (no cash moves, #103) | $152.00 |
| Reject 5: PO 2, 12 hoodies, $264.00 (nothing paid, #103) | $152.00 |
| Approve 6: price $49 × 8 (no cash moves, #103) | $152.00 |
| **End = `cash_accounts` checking in the working database** | **$152.00** |

By ticket, #101 −$848.00, #102 −$2,400.00 and #103 $0.00 sum to $3,248.00 paid
out. Before any decision, the requests asked for $3,512.00, which is $112.00
more than checking held, so one had to wait. The hoodie restock was the one
rejected.

**Three independent cash tests, all passed.** All three compare whole cents.
Their results are saved in `output/cash_checks.json`, and the scripts in
`tests/cash/` re-run them.
1. **The ledger reconciles inside the database: 20 of 20**
   (`tests/cash/ledger_check.py`):
   - every payment matches exactly one approved request
   - no rejected request or price override has a payment
   - start − payments = `cash_accounts`
   - the balance never goes negative
   - the invoice, lease and orders were updated to match
2. **Every source agrees: 32 of 32** (`tests/cash/sources_check.py`, which
   needs the backend on port 8000). It compared the working database with:
   - the live API (`/api/cash`, `/api/approvals`)
   - the audit trail: the reset, each decision's balance, and every agent's
     cash read (three at $3,400.00 before the decisions, one at $152.00 after)
   - every cash figure in the three deliverables
3. **A replay through the real MCP server: 30 of 30**
   (`.venv/bin/python tests/cash/replay_check.py`). On a fresh copy of the
   original, the same six requests and decisions were run through the
   server's own tools. They ended on exactly the working database's cash,
   payments, approvals, invoices, leases, orders and stock. The refusals held
   too:
   - the $264 order with $152 left
   - the tee order while invoice 501 was unpaid
   - paying rent twice
   - an agent's name as approver
   - a duplicate request

   Neither real database file changed.

### 6.5 Expected vs actual, in short

`output/desk_tickets.html` has the full comparison, ticket by ticket.
- **First calls:** the Boss called the planned agent first on all three
  tickets (Inventory, Facilities, Inventory), and the delegations came in the
  planned order.
- **Extra reads:** Accounting re-read data before filing (`check_invoice` on
  #101 and #103, `list_approvals` on #102, `check_stock_and_price` and
  `list_vendors` on #103). The plans listed most of these as possible.
- **Skipped check:** on #103 the Boss asked Accounting to request payment for
  every unpaid invoice of vendor 1, and Accounting skipped the planned
  `list_approvals`, so it tried to request invoice 501 again; the server
  refused the duplicate.
- **The rush reprint:** the #101 plan expected Inventory and Accounting to
  flag that invoice 501's "Rush reprint CC-TEE-WHITE S" might already cover the
  tee, and the human to check before approving PO 1. No agent raised it, and
  PO 1 was approved.
- **Price:** #103's price was $49 a hoodie, not the planned $50. That is 15.5%
  off list with a $27 margin, inside the planned range.
- **Payment order:** the #103 plan had the Boss recommend paying rent and
  invoice 501 before the hoodie restock. It flagged the $112.00 gap but left
  the order to the human.
- **What the plans did not foresee:** the close runs. #103 needed a second
  price request (approval 6) and two more drafts before it could close.

### 6.6 The audit trail

The run was appended to `output/audit_trail.json`, not written over it. The
322 entries from earlier board use and the first full run are still there, and
`seq` runs unbroken from 1 to 558. The run added 236 entries:
- 1 `db_reset`
- 7 `run_start` and 7 `run_end`
- 19 `agent_start` and 19 `agent_end`
- 86 `model_step`
- 79 `tool_call` (67 MCP calls and 12 `ask_agent` delegations)
- 12 `delegation`
- 6 `human_decision` (5 approvals, 1 rejection). The 3 that paid give the
  balance after each payment: $1,000.00, $160.00 and $152.00. The price
  overrides (approvals 4 and 6) and the rejected PO 2 (approval 5) moved no
  cash and have no balance field.
