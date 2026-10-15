# Campus Customs MCP server

**What it is for.** This server holds the shop tools for the Campus Customs
operations team. Every agent (Boss, Inventory, Accounting, Facilities,
Customer Service) works tickets by calling these tools, not by reading the
database directly. The tools only report what is in the database, plus simple
arithmetic on it. A missing SKU, size, invoice, lease, ticket or vendor
returns an error that names it (except `check_invoice`, which returns
`vendor: null` if the invoice's vendor row is missing); no value is ever filled
in.

**Database.** The server uses the working copy, `data/campus_customs_new.db`.
To use a different file, set `CAMPUS_DB_PATH`; a relative path is read from the
project root. The server refuses to open the original,
`data/campus_customs.db`, because that file is the reset copy. Lookup tools
open the database read-only and never change it; write tools change it in one
all-or-nothing transaction. The first time a write tool runs on a working copy,
the server adds four tables the original data has no room for: `approvals`,
`purchase_orders`, `drafts` and `ticket_updates`. Until then, lookups read
those tables as empty.

**Money needs a human.** Agents can only *request* payments, purchase orders
and discounts. Only `approve_request` and `reject_request` settle a request,
and they are registered **only when the server starts with
`CAMPUS_HUMAN_TOOLS=1`** (the API's desk connection in `backend/main.py`, used by its approve and reject routes). The agents' server and
Claude Code's (`.mcp.json`) never have them. A payment is refused if it would
take cash below zero or is not positive, and a purchase order is refused while
the vendor still has an unpaid invoice. Nothing is ever emailed or sent:
customer messages are saved as drafts.

## Tools

Write tools take an `actor` argument (the agent's name). The backend fills it
in, so an agent cannot act under another agent's name.

### Lookups (read-only)

| Tool | Arguments | Reads | Returns |
|---|---|---|---|
| `list_tickets` | optional `status` | `tickets`, `desk` | Every ticket on the board (or one status), with `date_today`. |
| `get_ticket` | `ticket_id` | `tickets`, `ticket_updates`, `drafts`, `approvals`, `desk` | One ticket with its status history, saved drafts and approval requests. |
| `check_stock_and_price` | `sku`, optional `size`, optional `qty_needed` (needs a size) | `inventory`, `pricing` | Stock for every size, and for the size asked: on hand, shortfall, whether stock covers it. Unit cost, list price, margin at list. |
| `check_invoice` | `invoice_id` | `invoices`, `vendors`, `desk` | The invoice, whether it is overdue on `date_today` and by how many days, the vendor, all of that vendor's unpaid invoices, and `vendor_blocked`. Any status other than `paid` counts as unpaid. |
| `check_lease` | `lease_id` | `leases`, `desk` | Space, landlord, monthly rent, next due date, days until due (negative if past due). |
| `list_vendors` | none | `vendors`, `invoices`, `desk` | Every vendor's specialty and lead days, earliest arrival if ordered today, unpaid invoices, and `vendor_blocked`. |
| `list_unpaid_invoices` | none | `invoices`, `vendors`, `desk` | Every unpaid invoice with vendor name, overdue days, and the total owed. |
| `check_cash` | none | `cash_accounts`, `approvals`, `payments`, `desk` | Balances, pending cash requests and the balance left if all were approved, and the payment ledger. |
| `list_approvals` | optional `status`, optional `ticket_id` | `approvals` | Approval requests and where each stands: pending, approved, rejected, or stale (the data changed after filing, so a new request is needed). |
| `list_drafts` | optional `ticket_id` | `drafts` | Customer message drafts (never sent). |

### Agent requests and board updates (write, never move money)

| Tool | Arguments | Writes | Does |
|---|---|---|---|
| `request_payment` | `ticket_id`, `kind` (`invoice` or `rent`), `ref_id`, `reason` | `approvals` (reads `tickets`, `invoices` or `leases`, `vendors`, `cash_accounts`, `desk`) | Asks a human to approve paying an invoice or rent. The amount comes from the database. Refuses a duplicate pending request (on any ticket), an invoice already paid, an amount that is not positive, or a resolved ticket. Shows the cash impact. |
| `create_purchase_order` | `ticket_id`, `vendor_id`, `sku`, `size`, `qty`, `reason` | `purchase_orders`, `approvals` (reads `tickets`, `vendors`, `inventory`, `pricing`, `invoices`, `cash_accounts`, `desk`) | Drafts a restock order costed at `qty` x `unit_cost` and asks for approval. Shows expected arrival (`date_today` + `lead_days`), any invoices blocking the vendor, open orders for the same item on other tickets, and the cash impact. Refuses a second pending order for the same item on the same ticket, or a resolved ticket. |
| `request_price_override` | `ticket_id`, `sku`, `qty`, `unit_price`, `reason` | `approvals` (reads `tickets`, `pricing`, `desk`) | Asks a human to approve a discounted price. Refuses a price below `unit_cost` (never sell at a loss) or not below `list_price`. Shows the discount and margin. No cash moves. |
| `save_customer_draft` | `ticket_id`, `recipient`, `subject`, `body` | `drafts` (reads `tickets`) | Saves a customer message as a draft on the board. There is no send tool. |
| `update_ticket_status` | `ticket_id`, `status` (`open`, `in_progress`, `waiting_approval`, `resolved`, `escalated`), `note` | `tickets.status`, `ticket_updates` (reads `approvals`) | Sets the board status and logs a note. Refuses `resolved` while an approval the ticket depends on is pending: its own, or a payment of the invoice or lease it links, even if filed on another ticket. |

### Human only (registered only with `CAMPUS_HUMAN_TOOLS=1`)

| Tool | Arguments | Writes | Does |
|---|---|---|---|
| `approve_request` | `approval_id`, `approved_by`, optional `note`, optional `account` | `approvals`, `payments`, `cash_accounts`, and `invoices.status`, `leases.next_due` or `purchase_orders` (reads `pricing`, `vendors`, `desk`) | Approves and carries out a request in one transaction. An invoice is marked `paid`; rent moves the lease's `next_due` one month on (a month-end date stays month-end); a purchase order is paid and marked `ordered`. Refuses, leaving the request pending, if cash is short or a purchase order's vendor still has an unpaid invoice. If the invoice amount, rent amount or due date, PO unit cost or override pricing changed since filing, marks the request `stale` and pays nothing. Refuses an `approved_by` that looks like an agent. |
| `reject_request` | `approval_id`, `decided_by`, optional `note` | `approvals`, `purchase_orders` | Rejects a pending request. Nothing is paid. |

## Run it

From the project root:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python mcp_server/server.py
```

It speaks MCP over stdio, so an MCP client starts it as a subprocess. Claude
Code finds it through `.mcp.json` at the project root (server name
`campus-customs`), and the agent team (`backend/agents.py`) starts its own copy.
The two paths in `.mcp.json` are absolute paths on this machine, so update them
if the project folder moves.
