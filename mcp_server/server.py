"""Campus Customs MCP server: the shop tools every agent on the team uses.

Every tool works on the working copy, data/campus_customs_new.db. The original,
data/campus_customs.db, is the reset source; this server refuses to open it.

Tools report what is in the database, plus simple arithmetic on those values (a
shortfall, days overdue) and the shop rules: a vendor with an unpaid invoice
will not ship, money moves only after a human approves, and a payment never
takes cash below zero. If a row is missing they say so instead of guessing.

Agents can read, and can *request* payments, purchase orders and discounts;
those requests wait in the approvals table. Only the human-only tools
(approve_request, reject_request) settle them, and they exist only in a
server process started with CAMPUS_HUMAN_TOOLS=1 (the human approver's);
the agents' server and Claude Code's never have them.

The server adds four tables to the working copy the first time a write tool
runs (approvals, purchase_orders, drafts, ticket_updates); lookups read them as
empty until then. The original database is
never changed, so resetting the working copy removes them until the next run.

Run over stdio:  .venv/bin/python mcp_server/server.py
"""

import calendar
import json
import os
import re
import sqlite3
import unicodedata
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

# --- Database location -------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ORIGINAL_DB = (PROJECT_ROOT / "data" / "campus_customs.db").resolve()
DEFAULT_DB = "data/campus_customs_new.db"
SHOP_TABLES = {"desk", "inventory", "pricing", "vendors", "invoices", "leases", "cash_accounts", "payments", "tickets"}

# Tables this server adds to the working copy; the original data has no place
# for approvals, purchase orders, drafts or board updates (harness §1.3).
EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    kind TEXT NOT NULL,              -- invoice_payment | rent_payment | purchase_order | price_override
    ref_id INTEGER,                  -- invoices.id | leases.id | purchase_orders.id | NULL
    amount REAL NOT NULL,            -- cash that leaves if approved (0 for price_override)
    details TEXT NOT NULL,           -- JSON snapshot of what was requested
    reason TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    requested_at TEXT NOT NULL,      -- real UTC timestamp
    shop_date TEXT NOT NULL,         -- desk.date_today when requested
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
    decided_by TEXT,
    decided_at TEXT,
    decision_note TEXT,
    payment_id INTEGER
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    vendor_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    size TEXT NOT NULL,
    qty INTEGER NOT NULL,
    unit_cost REAL NOT NULL,
    total REAL NOT NULL,
    status TEXT NOT NULL,            -- pending_approval | ordered | rejected
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    ordered_at TEXT,
    expected_arrival TEXT
);
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',     -- always 'draft': nothing is ever sent
    written_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_updates (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""
EXTRA_TABLES = {"approvals", "purchase_orders", "drafts", "ticket_updates"}


def _db_path() -> Path:
    """The working copy, or CAMPUS_DB_PATH if set (relative to the project root)."""
    path = Path(os.environ.get("CAMPUS_DB_PATH") or DEFAULT_DB)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _is_original(path: Path) -> bool:
    # samefile also catches case-changed spellings (macOS) and hard links.
    return path == ORIGINAL_DB or (ORIGINAL_DB.exists() and os.path.samefile(path, ORIGINAL_DB))


def _checked_path() -> Path:
    path = _db_path()
    if not path.is_file():
        hint = (
            "CAMPUS_DB_PATH points to a file that does not exist."
            if os.environ.get("CAMPUS_DB_PATH")
            else "Copy data/campus_customs.db to data/campus_customs_new.db first."
        )
        raise ToolError(f"Working database not found at {path}. {hint}")
    if _is_original(path):
        raise ToolError(
            "Refusing to open data/campus_customs.db: it is the reset copy. "
            "Point CAMPUS_DB_PATH at data/campus_customs_new.db."
        )
    return path


def _open(path: Path, mode: str) -> tuple[sqlite3.Connection, set[str]]:
    """Open with mode 'ro' or 'rw'; neither mode ever creates a file."""
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    except sqlite3.DatabaseError as exc:
        raise ToolError(f"Could not read {path} as a database: {exc}.") from exc
    missing = SHOP_TABLES - tables
    if missing:
        conn.close()
        raise ToolError(f"{path} is not the shop database; missing tables: {', '.join(sorted(missing))}.")
    return conn, tables


def _connect_write() -> sqlite3.Connection:
    conn, tables = _open(_checked_path(), "rw")
    if EXTRA_TABLES - tables:
        conn.executescript(EXTRA_SCHEMA)
    return conn


def _connect_readonly() -> sqlite3.Connection:
    """Open the working copy read-only, so lookup tools can never change it. On a
    freshly reset copy the extra tables do not exist yet; lookups read them as empty."""
    conn, _ = _open(_checked_path(), "ro")
    return conn


def _extra_rows(conn: sqlite3.Connection, table: str, sql: str, args: tuple | list = ()) -> list[sqlite3.Row]:
    """Rows from one of the server's own tables, or [] if a reset copy does not have it yet."""
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
    return conn.execute(sql, args).fetchall() if exists else []


@contextmanager
def _write_tx():
    """One all-or-nothing write: BEGIN IMMEDIATE ... COMMIT, rolled back on any error."""
    conn = _connect_write()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _parse_date(value: str, where: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ToolError(f"{where} holds {value!r}, which is not a YYYY-MM-DD date.") from exc


def _shop_today(conn: sqlite3.Connection) -> date:
    """desk.date_today is "today" for the shop; never the computer's clock."""
    rows = conn.execute("SELECT date_today FROM desk").fetchall()
    if len(rows) != 1:
        raise ToolError(f"Expected exactly one row in desk, found {len(rows)}.")
    return _parse_date(rows[0]["date_today"], "desk.date_today")


def _now() -> str:
    """Real UTC time, for when a request or decision was recorded (not the shop date)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _add_month(d: date) -> date:
    """Same day next month, clamped to that month's length (Jan 30 -> Feb 28). A due
    date on the last day of its month stays on the last day (Feb 28 -> Mar 31), so a
    month-end lease does not drift earlier."""
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    last = calendar.monthrange(year, month)[1]
    if d.day == calendar.monthrange(d.year, d.month)[1]:
        return d.replace(year=year, month=month, day=last)
    return d.replace(year=year, month=month, day=min(d.day, last))


def _money(x: float) -> float:
    return round(x + 0.0, 2)


# invoices.status is free text and the data only has 'open'. Anything that is
# not 'paid' (the value approve_request writes) counts as unpaid, so a typo or
# new status can never unblock a vendor by mistake.
PAID_STATUS = "paid"
UNPAID_SQL = "lower(trim(status)) <> 'paid'"

AGENT_NAMES = ("Boss", "Inventory", "Accounting", "Facilities", "Customer Service")
Actor = Annotated[
    Literal["Boss", "Inventory", "Accounting", "Facilities", "Customer Service"],
    Field(description="The agent making this change. The backend fills this in."),
]
TicketStatus = Literal["open", "in_progress", "waiting_approval", "resolved", "escalated"]

SQLITE_MAX_INT = 2**63 - 1
RowId = Annotated[int, Field(ge=1, le=SQLITE_MAX_INT)]
READ_ONLY = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
WRITES = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
MOVES_MONEY = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": False}

mcp = FastMCP(
    name="Campus Customs Shop",
    instructions=(
        "Tools for the Campus Customs operations team. Every value comes from "
        "the shop database or simple arithmetic on it; vendor_blocked applies "
        "the shop rule that a vendor with an unpaid invoice will not ship. If "
        "a tool says a row does not exist, do not guess it. Judge overdue and "
        "due dates by the shop's date_today, which each dated tool returns. "
        "Payments, purchase orders and discounts are only requests until a "
        "human approves them; nothing is ever emailed or sent."
    ),
)


# --- Result types ------------------------------------------------------------


class SizeStock(BaseModel):
    size: str
    qty: int
    location: str


class SizeCheck(BaseModel):
    size: str
    qty_on_hand: int
    in_stock: bool = Field(description="True if at least one unit is on hand.")
    qty_needed: int | None = None
    shortfall: int | None = Field(
        default=None, description="Units still missing after using all stock (0 if none)."
    )
    can_fill_from_stock: bool | None = None


class Pricing(BaseModel):
    unit_cost: float
    list_price: float
    margin_per_unit_at_list: float
    margin_pct_at_list: float | None = Field(
        default=None, description="Margin as a percent of list price."
    )


class StockAndPrice(BaseModel):
    sku: str
    name: str
    sizes: list[SizeStock] = Field(description="Stock for every size of this SKU.")
    total_qty: int
    requested: SizeCheck | None = Field(
        default=None, description="The size asked about, if one was given."
    )
    pricing: Pricing | None = Field(
        default=None, description="None if the SKU has no row in pricing."
    )


class Vendor(BaseModel):
    id: int
    name: str
    specialty: str
    lead_days: int


class UnpaidInvoice(BaseModel):
    invoice_id: int
    amount: float
    due_date: str
    status: str


class InvoiceCheck(BaseModel):
    invoice_id: int
    vendor_id: int
    amount: float
    due_date: str
    status: str
    description: str | None
    date_today: str
    is_overdue: bool = Field(description="Unpaid and past its due date.")
    days_overdue: int = Field(description="Days past due if overdue, else 0.")
    vendor: Vendor | None = Field(
        description="None if vendor_id matches no row in vendors."
    )
    vendor_unpaid_invoices: list[UnpaidInvoice] = Field(
        description="Every unpaid invoice this vendor has, including this one if unpaid."
    )
    vendor_unpaid_total: float
    vendor_blocked: bool = Field(
        description="True while the vendor has any unpaid invoice: by shop rule it will not ship new product."
    )


class LeaseCheck(BaseModel):
    lease_id: int
    space_name: str
    landlord: str
    monthly_rent: float
    next_due: str
    notes: str | None
    date_today: str
    days_until_due: int = Field(description="Negative if the rent is past due.")
    is_overdue: bool


class Ticket(BaseModel):
    ticket_id: int
    type: str
    requester: str
    subject: str
    sku: str | None
    size: str | None
    qty: int | None
    lease_id: int | None
    invoice_id: int | None
    status: str
    notes: str | None
    created_at: str


class TicketList(BaseModel):
    date_today: str
    tickets: list[Ticket]


class TicketUpdate(BaseModel):
    update_id: int
    status: str
    note: str
    updated_by: str
    created_at: str


class Draft(BaseModel):
    draft_id: int
    ticket_id: int
    recipient: str
    subject: str
    body: str
    status: str = Field(description="Always 'draft': nothing is ever sent.")
    written_by: str
    created_at: str


class Approval(BaseModel):
    approval_id: int
    ticket_id: int
    kind: str = Field(description="invoice_payment, rent_payment, purchase_order or price_override.")
    ref_id: int | None
    amount: float = Field(description="Cash that leaves if approved (0 for a price override).")
    details: dict[str, Any]
    reason: str
    requested_by: str
    requested_at: str
    shop_date: str
    status: str = Field(description="pending, approved or rejected.")
    decided_by: str | None
    decided_at: str | None
    decision_note: str | None
    payment_id: int | None


class TicketDetail(BaseModel):
    date_today: str
    ticket: Ticket
    updates: list[TicketUpdate]
    drafts: list[Draft]
    approvals: list[Approval]


class VendorStatus(BaseModel):
    vendor: Vendor
    earliest_arrival_if_ordered_today: str = Field(description="date_today + lead_days.")
    unpaid_invoices: list[UnpaidInvoice]
    unpaid_total: float
    vendor_blocked: bool = Field(description="True while the vendor has any unpaid invoice.")


class VendorList(BaseModel):
    date_today: str
    vendors: list[VendorStatus]


class OpenBill(BaseModel):
    invoice_id: int
    vendor_id: int
    vendor_name: str | None
    amount: float
    due_date: str
    status: str
    description: str | None
    is_overdue: bool
    days_overdue: int


class UnpaidInvoiceList(BaseModel):
    date_today: str
    invoices: list[OpenBill]
    total: float


class CashAccount(BaseModel):
    name: str
    balance: float
    date: str


class PendingPayment(BaseModel):
    approval_id: int
    ticket_id: int
    kind: str
    amount: float


class Payment(BaseModel):
    payment_id: int
    kind: str
    ref_id: int | None
    amount: float
    account: str
    paid_at: str
    approved_by: str


class CashCheck(BaseModel):
    date_today: str
    accounts: list[CashAccount]
    total_balance: float
    pending_payments: list[PendingPayment] = Field(description="Approvals waiting on a human that would move cash.")
    pending_total: float
    balance_if_all_pending_paid: float
    can_cover_all_pending: bool
    payments: list[Payment] = Field(description="Every payment already made (the ledger).")


class CashImpact(BaseModel):
    balance: float = Field(description="Cash in the paying account now.")
    this_request: float
    pending_total_including_this: float = Field(description="All pending cash requests, this one included.")
    balance_if_all_pending_paid: float
    fits_alone: bool = Field(description="True if the balance covers this request on its own.")
    fits_with_all_pending: bool = Field(description="True if the balance covers every pending request together.")


class PaymentRequestResult(BaseModel):
    approval: Approval
    cash: CashImpact
    note: str


class PurchaseOrder(BaseModel):
    po_id: int
    ticket_id: int
    vendor_id: int
    sku: str
    size: str
    qty: int
    unit_cost: float
    total: float
    status: str
    created_by: str
    created_at: str
    ordered_at: str | None
    expected_arrival: str | None


class PurchaseOrderResult(BaseModel):
    purchase_order: PurchaseOrder
    approval: Approval
    vendor_blocked: bool
    blocking_invoices: list[UnpaidInvoice] = Field(
        description="Unpaid invoices that must be paid before this order can be approved."
    )
    expected_arrival_if_approved_today: str
    other_open_orders: list[PurchaseOrder] = Field(
        description="Pending or placed orders for the same SKU and size on other tickets."
    )
    cash: CashImpact
    note: str


class PriceOverrideResult(BaseModel):
    approval: Approval
    note: str


class DraftResult(BaseModel):
    draft: Draft
    note: str


class TicketStatusResult(BaseModel):
    ticket_id: int
    old_status: str
    new_status: str
    update: TicketUpdate


class DecisionResult(BaseModel):
    approval: Approval
    payment: Payment | None = None
    cash_balance_after: float | None = None
    changes: list[str] = Field(description="Every row this decision changed.")


# --- Row helpers ---------------------------------------------------------------


def _ticket(row: sqlite3.Row) -> Ticket:
    return Ticket(ticket_id=row["id"], **{k: row[k] for k in Ticket.model_fields if k != "ticket_id"})


def _ticket_row(conn: sqlite3.Connection, ticket_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise ToolError(f"No ticket with id {ticket_id}.")
    return row


def _ticket_taking_requests(conn: sqlite3.Connection, ticket_id: int) -> sqlite3.Row:
    row = _ticket_row(conn, ticket_id)
    if row["status"].strip().lower() == "resolved":
        raise ToolError(f"Ticket {ticket_id} is resolved; a resolved ticket takes no new requests.")
    return row


def _approval(row: sqlite3.Row) -> Approval:
    return Approval(
        approval_id=row["id"],
        details=json.loads(row["details"]),
        **{k: row[k] for k in Approval.model_fields if k not in ("approval_id", "details")},
    )


def _approval_row(conn: sqlite3.Connection, approval_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if row is None:
        raise ToolError(f"No approval request with id {approval_id}.")
    return row


def _draft(row: sqlite3.Row) -> Draft:
    return Draft(draft_id=row["id"], **{k: row[k] for k in Draft.model_fields if k != "draft_id"})


def _update(row: sqlite3.Row) -> TicketUpdate:
    return TicketUpdate(update_id=row["id"], **{k: row[k] for k in TicketUpdate.model_fields if k != "update_id"})


def _po(row: sqlite3.Row) -> PurchaseOrder:
    return PurchaseOrder(po_id=row["id"], **{k: row[k] for k in PurchaseOrder.model_fields if k != "po_id"})


def _payment(row: sqlite3.Row) -> Payment:
    return Payment(payment_id=row["id"], **{k: row[k] for k in Payment.model_fields if k != "payment_id"})


def _vendor_unpaid(conn: sqlite3.Connection, vendor_id: int) -> list[UnpaidInvoice]:
    rows = conn.execute(
        f"SELECT id, amount, due_date, status FROM invoices WHERE vendor_id = ? AND {UNPAID_SQL} ORDER BY due_date, id",
        (vendor_id,),
    ).fetchall()
    return [UnpaidInvoice(invoice_id=r["id"], amount=r["amount"], due_date=r["due_date"], status=r["status"]) for r in rows]


def _account(conn: sqlite3.Connection, name: str = "checking") -> sqlite3.Row:
    row = conn.execute("SELECT * FROM cash_accounts WHERE name = ?", (name,)).fetchone()
    if row is None:
        names = [r["name"] for r in conn.execute("SELECT name FROM cash_accounts")]
        raise ToolError(f"No cash account named '{name}'. Accounts: {', '.join(names)}.")
    return row


def _pending_cash_total(conn: sqlite3.Connection) -> float:
    row = conn.execute("SELECT COALESCE(SUM(amount), 0) AS t FROM approvals WHERE status = 'pending' AND amount > 0").fetchone()
    return _money(row["t"])


def _cash_impact(conn: sqlite3.Connection, amount: float) -> CashImpact:
    """Called after the request row is inserted, so pending totals include it."""
    balance = _money(_account(conn)["balance"])
    pending = _pending_cash_total(conn)
    return CashImpact(
        balance=balance,
        this_request=_money(amount),
        pending_total_including_this=pending,
        balance_if_all_pending_paid=_money(balance - pending),
        fits_alone=balance >= amount,
        fits_with_all_pending=balance >= pending,
    )


def _insert_approval(conn, *, ticket_id, kind, ref_id, amount, details, reason, actor, today) -> sqlite3.Row:
    cur = conn.execute(
        "INSERT INTO approvals (ticket_id, kind, ref_id, amount, details, reason, requested_by, requested_at, shop_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticket_id, kind, ref_id, _money(amount), json.dumps(details), reason, actor, _now(), today.isoformat()),
    )
    return _approval_row(conn, cur.lastrowid)


def _clean_text(value: str, field: str, max_len: int) -> str:
    value = (value or "").strip()
    if not value:
        raise ToolError(f"{field} cannot be empty.")
    if len(value) > max_len:
        raise ToolError(f"{field} is {len(value)} characters; keep it under {max_len}.")
    return value


# --- Read tools ------------------------------------------------------------------

SIZE_ORDER = "CASE upper(trim(size)) WHEN 'XS' THEN 0 WHEN 'S' THEN 1 WHEN 'M' THEN 2 WHEN 'L' THEN 3 WHEN 'XL' THEN 4 WHEN 'XXL' THEN 5 ELSE 9 END"


@mcp.tool(annotations=READ_ONLY)
def list_tickets(
    status: Annotated[
        str | None, Field(description="Only tickets with this status, e.g. open. Leave out for all tickets.")
    ] = None,
) -> TicketList:
    """Every ticket on the board (or only those with one status), with the shop's date_today."""
    with closing(_connect_readonly()) as conn:
        today = _shop_today(conn)
        if status and status.strip():
            rows = conn.execute(
                "SELECT * FROM tickets WHERE lower(trim(status)) = ? ORDER BY id", (status.strip().lower(),)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM tickets ORDER BY id").fetchall()
    return TicketList(date_today=today.isoformat(), tickets=[_ticket(r) for r in rows])


@mcp.tool(annotations=READ_ONLY)
def get_ticket(ticket_id: Annotated[int, Field(ge=1, le=SQLITE_MAX_INT, description="Ticket id, e.g. 101.")]) -> TicketDetail:
    """One ticket with everything on the board for it: status updates, saved
    customer drafts, and approval requests (pending or decided)."""
    with closing(_connect_readonly()) as conn:
        today = _shop_today(conn)
        ticket = _ticket(_ticket_row(conn, ticket_id))
        updates = _extra_rows(conn, "ticket_updates", "SELECT * FROM ticket_updates WHERE ticket_id = ? ORDER BY id", (ticket_id,))
        drafts = _extra_rows(conn, "drafts", "SELECT * FROM drafts WHERE ticket_id = ? ORDER BY id", (ticket_id,))
        approvals = _extra_rows(conn, "approvals", "SELECT * FROM approvals WHERE ticket_id = ? ORDER BY id", (ticket_id,))
    return TicketDetail(
        date_today=today.isoformat(),
        ticket=ticket,
        updates=[_update(r) for r in updates],
        drafts=[_draft(r) for r in drafts],
        approvals=[_approval(r) for r in approvals],
    )


@mcp.tool(annotations=READ_ONLY)
def check_stock_and_price(
    sku: Annotated[str, Field(description="Product SKU, e.g. CC-HOOD-NAVY.")],
    size: Annotated[
        str | None,
        Field(description="Size to check (S, M, L, XL, or OS). Leave out to see every size."),
    ] = None,
    qty_needed: Annotated[
        int | None,
        Field(ge=1, description="Units the ticket asks for. Needs a size."),
    ] = None,
) -> StockAndPrice:
    """Stock on hand for a SKU (every size, or one size against a quantity
    needed) plus its unit cost, list price and margin, from inventory and pricing."""
    sku = sku.strip().upper()
    size = (size or "").strip().upper() or None
    if not sku:
        raise ToolError("Give a SKU, e.g. CC-HOOD-NAVY.")
    if qty_needed is not None and size is None:
        raise ToolError("qty_needed needs a size, because stock is counted per size.")

    with closing(_connect_readonly()) as conn:
        rows = conn.execute(
            f"SELECT sku, name, size, qty, location FROM inventory WHERE upper(trim(sku)) = ? ORDER BY {SIZE_ORDER}, size",
            (sku,),
        ).fetchall()
        if not rows:
            known = [r["sku"] for r in conn.execute("SELECT DISTINCT sku FROM inventory ORDER BY sku")]
            raise ToolError(f"No product with SKU '{sku}' in inventory. Known SKUs: {', '.join(known)}.")
        price = conn.execute(
            "SELECT unit_cost, list_price FROM pricing WHERE upper(trim(sku)) = ?", (sku,)
        ).fetchone()

    sizes = [SizeStock(size=r["size"], qty=r["qty"], location=r["location"]) for r in rows]

    requested = None
    if size is not None:
        match = next((s for s in sizes if s.size.strip().upper() == size), None)
        if match is None:
            raise ToolError(
                f"SKU '{sku}' has no size '{size}' in inventory. "
                f"Sizes on file: {', '.join(s.size for s in sizes)}."
            )
        requested = SizeCheck(size=match.size, qty_on_hand=match.qty, in_stock=match.qty > 0)
        if qty_needed is not None:
            requested.qty_needed = qty_needed
            requested.shortfall = max(0, qty_needed - match.qty)
            requested.can_fill_from_stock = match.qty >= qty_needed

    pricing = None
    if price is not None:
        margin = price["list_price"] - price["unit_cost"]
        pricing = Pricing(
            unit_cost=price["unit_cost"],
            list_price=price["list_price"],
            margin_per_unit_at_list=round(margin, 2),
            margin_pct_at_list=round(margin / price["list_price"] * 100, 1)
            if price["list_price"] > 0
            else None,
        )

    return StockAndPrice(
        sku=rows[0]["sku"],
        name=rows[0]["name"],
        sizes=sizes,
        total_qty=sum(s.qty for s in sizes),
        requested=requested,
        pricing=pricing,
    )


@mcp.tool(annotations=READ_ONLY)
def check_invoice(
    invoice_id: Annotated[int, Field(ge=1, le=SQLITE_MAX_INT, description="Invoice id, e.g. 501.")],
) -> InvoiceCheck:
    """One invoice with its vendor (name, specialty, lead days), whether it is
    overdue on the shop's date_today, and every unpaid invoice that vendor has.
    A vendor will not ship new product while it has any unpaid invoice."""
    with closing(_connect_readonly()) as conn:
        today = _shop_today(conn)
        inv = conn.execute(
            "SELECT id, vendor_id, amount, due_date, status, description FROM invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()
        if inv is None:
            raise ToolError(f"No invoice with id {invoice_id}.")
        vendor_row = conn.execute(
            "SELECT id, name, specialty, lead_days FROM vendors WHERE id = ?",
            (inv["vendor_id"],),
        ).fetchone()
        unpaid = _vendor_unpaid(conn, inv["vendor_id"])

    due = _parse_date(inv["due_date"], f"invoices.due_date for invoice {invoice_id}")
    is_unpaid = inv["status"].strip().lower() != PAID_STATUS
    is_overdue = is_unpaid and today > due

    return InvoiceCheck(
        invoice_id=inv["id"],
        vendor_id=inv["vendor_id"],
        amount=inv["amount"],
        due_date=inv["due_date"],
        status=inv["status"],
        description=inv["description"],
        date_today=today.isoformat(),
        is_overdue=is_overdue,
        days_overdue=(today - due).days if is_overdue else 0,
        vendor=Vendor(**dict(vendor_row)) if vendor_row else None,
        vendor_unpaid_invoices=unpaid,
        vendor_unpaid_total=round(sum(i.amount for i in unpaid), 2),
        vendor_blocked=bool(unpaid),
    )


@mcp.tool(annotations=READ_ONLY)
def check_lease(
    lease_id: Annotated[int, Field(ge=1, le=SQLITE_MAX_INT, description="Lease id, e.g. 1.")],
) -> LeaseCheck:
    """One lease: the space, landlord, monthly rent and next due date, with
    days until due (negative if past due) on the shop's date_today."""
    with closing(_connect_readonly()) as conn:
        today = _shop_today(conn)
        lease = conn.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due, notes FROM leases WHERE id = ?",
            (lease_id,),
        ).fetchone()
        if lease is None:
            raise ToolError(f"No lease with id {lease_id}.")

    days_until_due = (_parse_date(lease["next_due"], f"leases.next_due for lease {lease_id}") - today).days
    return LeaseCheck(
        lease_id=lease["id"],
        space_name=lease["space_name"],
        landlord=lease["landlord"],
        monthly_rent=lease["monthly_rent"],
        next_due=lease["next_due"],
        notes=lease["notes"],
        date_today=today.isoformat(),
        days_until_due=days_until_due,
        is_overdue=days_until_due < 0,
    )


@mcp.tool(annotations=READ_ONLY)
def list_vendors() -> VendorList:
    """Every vendor with its specialty and lead days, the earliest arrival date
    if ordered today, its unpaid invoices, and whether it is blocked from
    shipping (a vendor with any unpaid invoice will not ship new product)."""
    with closing(_connect_readonly()) as conn:
        today = _shop_today(conn)
        vendors = conn.execute("SELECT id, name, specialty, lead_days FROM vendors ORDER BY id").fetchall()
        result = []
        for v in vendors:
            unpaid = _vendor_unpaid(conn, v["id"])
            result.append(VendorStatus(
                vendor=Vendor(**dict(v)),
                earliest_arrival_if_ordered_today=(today + timedelta(days=v["lead_days"])).isoformat(),
                unpaid_invoices=unpaid,
                unpaid_total=_money(sum(i.amount for i in unpaid)),
                vendor_blocked=bool(unpaid),
            ))
    return VendorList(date_today=today.isoformat(), vendors=result)


@mcp.tool(annotations=READ_ONLY)
def list_unpaid_invoices() -> UnpaidInvoiceList:
    """Every unpaid vendor invoice with the vendor's name, whether it is overdue
    on the shop's date_today and by how many days, and the total owed."""
    with closing(_connect_readonly()) as conn:
        today = _shop_today(conn)
        rows = conn.execute(
            f"SELECT i.*, v.name AS vendor_name FROM invoices i LEFT JOIN vendors v ON v.id = i.vendor_id "
            f"WHERE {UNPAID_SQL.replace('status', 'i.status')} ORDER BY i.due_date, i.id"
        ).fetchall()
    bills = []
    for r in rows:
        due = _parse_date(r["due_date"], f"invoices.due_date for invoice {r['id']}")
        overdue = today > due
        bills.append(OpenBill(
            invoice_id=r["id"], vendor_id=r["vendor_id"], vendor_name=r["vendor_name"], amount=r["amount"],
            due_date=r["due_date"], status=r["status"], description=r["description"],
            is_overdue=overdue, days_overdue=(today - due).days if overdue else 0,
        ))
    return UnpaidInvoiceList(date_today=today.isoformat(), invoices=bills, total=_money(sum(b.amount for b in bills)))


@mcp.tool(annotations=READ_ONLY)
def check_cash() -> CashCheck:
    """Cash in every account, the payments already made, and the pending
    approval requests that would move cash, with the balance left if every
    pending request were approved. No revenue comes in; cash only goes out."""
    with closing(_connect_readonly()) as conn:
        today = _shop_today(conn)
        accounts = [CashAccount(**dict(r)) for r in conn.execute("SELECT name, balance, date FROM cash_accounts ORDER BY name")]
        pending = _extra_rows(
            conn, "approvals", "SELECT id, ticket_id, kind, amount FROM approvals WHERE status = 'pending' AND amount > 0 ORDER BY id"
        )
        payments = conn.execute("SELECT * FROM payments ORDER BY id").fetchall()
    total = _money(sum(a.balance for a in accounts))
    pending_total = _money(sum(r["amount"] for r in pending))
    return CashCheck(
        date_today=today.isoformat(),
        accounts=accounts,
        total_balance=total,
        pending_payments=[PendingPayment(approval_id=r["id"], ticket_id=r["ticket_id"], kind=r["kind"], amount=r["amount"]) for r in pending],
        pending_total=pending_total,
        balance_if_all_pending_paid=_money(total - pending_total),
        can_cover_all_pending=total >= pending_total,
        payments=[_payment(r) for r in payments],
    )


@mcp.tool(annotations=READ_ONLY)
def list_approvals(
    status: Annotated[
        Literal["pending", "approved", "rejected", "stale"] | None, Field(description="Only requests with this status.")
    ] = None,
    ticket_id: Annotated[int | None, Field(ge=1, le=SQLITE_MAX_INT, description="Only requests for this ticket.")] = None,
) -> list[Approval]:
    """Approval requests (payments, purchase orders, price overrides) and where
    each stands: pending (waiting on a human), approved, rejected, or stale (the
    data changed after it was filed, so a new request is needed)."""
    sql, args = "SELECT * FROM approvals WHERE 1 = 1", []
    if status:
        sql, args = sql + " AND status = ?", args + [status]
    if ticket_id is not None:
        sql, args = sql + " AND ticket_id = ?", args + [ticket_id]
    with closing(_connect_readonly()) as conn:
        rows = _extra_rows(conn, "approvals", sql + " ORDER BY id", args)
    return [_approval(r) for r in rows]


@mcp.tool(annotations=READ_ONLY)
def list_drafts(
    ticket_id: Annotated[int | None, Field(ge=1, le=SQLITE_MAX_INT, description="Only drafts for this ticket.")] = None,
) -> list[Draft]:
    """Customer message drafts saved on the board. Drafts are never sent."""
    with closing(_connect_readonly()) as conn:
        if ticket_id is None:
            rows = _extra_rows(conn, "drafts", "SELECT * FROM drafts ORDER BY id")
        else:
            rows = _extra_rows(conn, "drafts", "SELECT * FROM drafts WHERE ticket_id = ? ORDER BY id", (ticket_id,))
    return [_draft(r) for r in rows]


# --- Agent write tools: requests and drafts, never money -----------------------


@mcp.tool(annotations=WRITES)
def request_payment(
    ticket_id: Annotated[int, Field(ge=1, le=SQLITE_MAX_INT, description="The ticket this payment resolves.")],
    kind: Annotated[Literal["invoice", "rent"], Field(description="invoice: pay a vendor invoice. rent: pay a lease's rent.")],
    ref_id: Annotated[int, Field(ge=1, le=SQLITE_MAX_INT, description="invoices.id for invoice, leases.id for rent.")],
    reason: Annotated[str, Field(description="Why this should be paid now, for the human approver.")],
    actor: Actor,
) -> PaymentRequestResult:
    """Ask a human to approve paying a vendor invoice or a lease's rent. The
    amount comes from the database, never from the caller. Nothing is paid
    until a human approves; the result shows the cash impact."""
    reason = _clean_text(reason, "reason", 1000)
    with _write_tx() as conn:
        today = _shop_today(conn)
        _ticket_taking_requests(conn, ticket_id)
        if kind == "invoice":
            inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (ref_id,)).fetchone()
            if inv is None:
                raise ToolError(f"No invoice with id {ref_id}.")
            if inv["status"].strip().lower() == PAID_STATUS:
                raise ToolError(f"Invoice {ref_id} is already paid.")
            vendor = conn.execute("SELECT name FROM vendors WHERE id = ?", (inv["vendor_id"],)).fetchone()
            approval_kind, amount = "invoice_payment", inv["amount"]
            details = {
                "invoice_id": ref_id, "vendor_id": inv["vendor_id"], "vendor_name": vendor["name"] if vendor else None,
                "due_date": inv["due_date"], "description": inv["description"],
                "days_overdue": max(0, (today - _parse_date(inv["due_date"], "invoices.due_date")).days),
            }
        else:
            lease = conn.execute("SELECT * FROM leases WHERE id = ?", (ref_id,)).fetchone()
            if lease is None:
                raise ToolError(f"No lease with id {ref_id}.")
            approval_kind, amount = "rent_payment", lease["monthly_rent"]
            details = {
                "lease_id": ref_id, "space_name": lease["space_name"], "landlord": lease["landlord"],
                "for_due_date": lease["next_due"],
                "days_until_due": (_parse_date(lease["next_due"], "leases.next_due") - today).days,
            }
        if amount is None or amount <= 0:
            raise ToolError(f"The {kind} amount on file is {amount!r}; a payment must be positive (cash only goes out).")
        dup = conn.execute(
            "SELECT id FROM approvals WHERE kind = ? AND ref_id = ? AND status = 'pending'", (approval_kind, ref_id)
        ).fetchone()
        if dup:
            raise ToolError(f"Approval request {dup['id']} for this {kind} is already pending; do not request it twice.")
        row = _insert_approval(conn, ticket_id=ticket_id, kind=approval_kind, ref_id=ref_id, amount=amount,
                               details=details, reason=reason, actor=actor, today=today)
        impact = _cash_impact(conn, amount)
    return PaymentRequestResult(
        approval=_approval(row), cash=impact,
        note="Pending human approval. Nothing has been paid; cash is unchanged.",
    )


@mcp.tool(annotations=WRITES)
def create_purchase_order(
    ticket_id: Annotated[int, Field(ge=1, le=SQLITE_MAX_INT, description="The ticket this restock is for.")],
    vendor_id: Annotated[int, Field(ge=1, le=SQLITE_MAX_INT, description="vendors.id of the supplier.")],
    sku: Annotated[str, Field(description="SKU to restock, e.g. CC-HOOD-NAVY.")],
    size: Annotated[str, Field(description="Size to restock, e.g. M.")],
    qty: Annotated[int, Field(ge=1, le=10000, description="Units to order.")],
    reason: Annotated[str, Field(description="Why this order is needed, for the human approver.")],
    actor: Actor,
) -> PurchaseOrderResult:
    """Draft a purchase order and ask a human to approve it. The cost is qty x
    the SKU's unit_cost from pricing. Approving it pays the vendor up front, so
    it needs enough cash, and it cannot be approved while the vendor has an
    unpaid invoice."""
    reason = _clean_text(reason, "reason", 1000)
    sku, size = sku.strip().upper(), size.strip().upper()
    with _write_tx() as conn:
        today = _shop_today(conn)
        _ticket_taking_requests(conn, ticket_id)
        vendor = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            raise ToolError(f"No vendor with id {vendor_id}.")
        item = conn.execute(
            "SELECT sku, size FROM inventory WHERE upper(trim(sku)) = ? AND upper(trim(size)) = ?", (sku, size)
        ).fetchone()
        if item is None:
            raise ToolError(f"No inventory row for SKU '{sku}' size '{size}'.")
        price = conn.execute("SELECT unit_cost FROM pricing WHERE upper(trim(sku)) = ?", (sku,)).fetchone()
        if price is None:
            raise ToolError(f"SKU '{sku}' has no unit_cost in pricing, so the order cannot be costed.")
        if price["unit_cost"] <= 0:
            raise ToolError(f"SKU '{sku}' has unit_cost {price['unit_cost']}; an order must cost a positive amount.")
        dup = conn.execute(
            "SELECT id FROM purchase_orders WHERE ticket_id = ? AND sku = ? AND size = ? AND status = 'pending_approval'",
            (ticket_id, item["sku"], item["size"]),
        ).fetchone()
        if dup:
            raise ToolError(f"Purchase order {dup['id']} for this ticket and item is already pending; do not order it twice.")
        others = conn.execute(
            "SELECT * FROM purchase_orders WHERE sku = ? AND size = ? AND ticket_id <> ? "
            "AND status IN ('pending_approval', 'ordered') ORDER BY id", (item["sku"], item["size"], ticket_id),
        ).fetchall()
        total = _money(qty * price["unit_cost"])
        arrival = (today + timedelta(days=vendor["lead_days"])).isoformat()
        cur = conn.execute(
            "INSERT INTO purchase_orders (ticket_id, vendor_id, sku, size, qty, unit_cost, total, status, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_approval', ?, ?)",
            (ticket_id, vendor_id, item["sku"], item["size"], qty, price["unit_cost"], total, actor, _now()),
        )
        po_id = cur.lastrowid
        blocking = _vendor_unpaid(conn, vendor_id)
        details = {
            "po_id": po_id, "vendor_id": vendor_id, "vendor_name": vendor["name"], "vendor_specialty": vendor["specialty"],
            "sku": item["sku"], "size": item["size"], "qty": qty, "unit_cost": price["unit_cost"],
            "lead_days": vendor["lead_days"], "expected_arrival_if_approved_today": arrival,
            "blocked_by_invoices": [b.invoice_id for b in blocking],
        }
        row = _insert_approval(conn, ticket_id=ticket_id, kind="purchase_order", ref_id=po_id, amount=total,
                               details=details, reason=reason, actor=actor, today=today)
        impact = _cash_impact(conn, total)
        po = _po(conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone())
    note = "Pending human approval. Nothing has been ordered or paid."
    if others:
        note += f" Other tickets already have open orders for this item: PO {', '.join(str(o['id']) for o in others)}."
    if blocking:
        note += f" {vendor['name']} has unpaid invoice(s) {', '.join(str(b.invoice_id) for b in blocking)}; this order cannot be approved until they are paid."
    return PurchaseOrderResult(
        purchase_order=po, approval=_approval(row), vendor_blocked=bool(blocking), blocking_invoices=blocking,
        other_open_orders=[_po(o) for o in others],
        expected_arrival_if_approved_today=arrival, cash=impact, note=note,
    )


@mcp.tool(annotations=WRITES)
def request_price_override(
    ticket_id: Annotated[int, Field(ge=1, le=SQLITE_MAX_INT, description="The ticket asking for the discount.")],
    sku: Annotated[str, Field(description="SKU being discounted, e.g. CC-HOOD-NAVY.")],
    qty: Annotated[int, Field(ge=1, le=10000, description="Units the discounted price covers.")],
    unit_price: Annotated[float, Field(gt=0, description="Proposed price per unit, in dollars.")],
    reason: Annotated[str, Field(description="Why this price, for the human approver.")],
    actor: Actor,
) -> PriceOverrideResult:
    """Ask a human to approve a discounted unit price for a customer. The price
    must be at or above unit_cost (never sell at a loss) and below list_price.
    No cash moves; the result shows the discount and the margin left."""
    reason = _clean_text(reason, "reason", 1000)
    sku = sku.strip().upper()
    with _write_tx() as conn:
        today = _shop_today(conn)
        _ticket_taking_requests(conn, ticket_id)
        price = conn.execute("SELECT sku, unit_cost, list_price FROM pricing WHERE upper(trim(sku)) = ?", (sku,)).fetchone()
        if price is None:
            raise ToolError(f"SKU '{sku}' has no row in pricing.")
        unit_price = _money(unit_price)
        if unit_price < price["unit_cost"]:
            raise ToolError(f"${unit_price:.2f} is below the ${price['unit_cost']:.2f} unit cost; the shop does not sell at a loss.")
        if unit_price >= price["list_price"]:
            raise ToolError(f"${unit_price:.2f} is not below the ${price['list_price']:.2f} list price, so it is not a discount.")
        dup = conn.execute(
            "SELECT id FROM approvals WHERE kind = 'price_override' AND ticket_id = ? AND status = 'pending' "
            "AND json_extract(details, '$.sku') = ?", (ticket_id, price["sku"]),
        ).fetchone()
        if dup:
            raise ToolError(f"Price override request {dup['id']} for this ticket and SKU is already pending.")
        margin = unit_price - price["unit_cost"]
        details = {
            "sku": price["sku"], "qty": qty, "unit_price": unit_price, "list_price": price["list_price"],
            "unit_cost": price["unit_cost"],
            "discount_pct_off_list": round((price["list_price"] - unit_price) / price["list_price"] * 100, 1),
            "margin_per_unit": _money(margin), "margin_pct": round(margin / unit_price * 100, 1),
            "quote_total": _money(qty * unit_price), "list_total": _money(qty * price["list_price"]),
        }
        row = _insert_approval(conn, ticket_id=ticket_id, kind="price_override", ref_id=None, amount=0,
                               details=details, reason=reason, actor=actor, today=today)
    return PriceOverrideResult(
        approval=_approval(row),
        note="Pending human approval. Do not promise this price to the customer until it is approved.",
    )


@mcp.tool(annotations=WRITES)
def save_customer_draft(
    ticket_id: Annotated[int, Field(ge=1, le=SQLITE_MAX_INT, description="The ticket this message answers.")],
    recipient: Annotated[str, Field(description="Who the message is for, e.g. the ticket's requester.")],
    subject: Annotated[str, Field(description="Subject line.")],
    body: Annotated[str, Field(description="The full message text.")],
    actor: Actor,
) -> DraftResult:
    """Save a customer message as a draft on the board. There is no send tool:
    drafts are never emailed or delivered; a human reviews and sends them."""
    recipient = _clean_text(recipient, "recipient", 200)
    subject = _clean_text(subject, "subject", 200)
    body = _clean_text(body, "body", 5000)
    with _write_tx() as conn:
        _ticket_row(conn, ticket_id)
        cur = conn.execute(
            "INSERT INTO drafts (ticket_id, recipient, subject, body, status, written_by, created_at) VALUES (?, ?, ?, ?, 'draft', ?, ?)",
            (ticket_id, recipient, subject, body, actor, _now()),
        )
        draft = _draft(conn.execute("SELECT * FROM drafts WHERE id = ?", (cur.lastrowid,)).fetchone())
    return DraftResult(draft=draft, note="Saved as a draft on the board. Nothing was sent.")


@mcp.tool(annotations=WRITES)
def update_ticket_status(
    ticket_id: Annotated[int, Field(ge=1, le=SQLITE_MAX_INT, description="Ticket to update.")],
    status: Annotated[TicketStatus, Field(description="New status for the board.")],
    note: Annotated[str, Field(description="What was decided or done, for the board.")],
    actor: Actor,
) -> TicketStatusResult:
    """Set a ticket's status on the board and log a note. A ticket cannot be
    marked resolved while an approval it depends on is pending (its own, or a
    payment of the invoice or lease it links); use waiting_approval."""
    note = _clean_text(note, "note", 2000)
    with _write_tx() as conn:
        trow = _ticket_row(conn, ticket_id)
        old = trow["status"]
        if status == "resolved":
            # This ticket's own requests, plus any pending payment of the invoice or lease it links.
            pending = conn.execute(
                "SELECT id FROM approvals WHERE status = 'pending' AND (ticket_id = ? "
                "OR (kind = 'invoice_payment' AND ref_id = ?) OR (kind = 'rent_payment' AND ref_id = ?)) ORDER BY id",
                (ticket_id, trow["invoice_id"], trow["lease_id"]),
            ).fetchall()
            if pending:
                raise ToolError(
                    f"Ticket {ticket_id} has pending approval request(s) {', '.join(str(r['id']) for r in pending)}; "
                    "set waiting_approval until a human decides."
                )
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (status, ticket_id))
        cur = conn.execute(
            "INSERT INTO ticket_updates (ticket_id, status, note, updated_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (ticket_id, status, note, actor, _now()),
        )
        update = _update(conn.execute("SELECT * FROM ticket_updates WHERE id = ?", (cur.lastrowid,)).fetchone())
    return TicketStatusResult(ticket_id=ticket_id, old_status=old, new_status=status, update=update)


# --- Human-only tools: registered only for the human approver's process ---------
#
# approve_request and reject_request are the only tools that settle a request.
# They are registered only when CAMPUS_HUMAN_TOOLS=1 is set (the dashboard's
# server process). The agents' server process and Claude Code's (.mcp.json)
# never set it, so those clients do not see the tools at all.

HUMAN_TOOLS_ENABLED = os.environ.get("CAMPUS_HUMAN_TOOLS") == "1"
_NOT_HUMAN = ("agent", "bot", "gpt", "model", "assistant", "claude", "llm", "ai", "system")


def _human_name(name: str, field: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ToolError(f"{field} must be the name of the human making the decision.")
    # Compare letters only, so "Accounting-Agent", "B0ss" look-alikes with spacing or punctuation are caught too.
    squashed = re.sub(r"[^a-z]", "", unicodedata.normalize("NFKC", name).casefold())
    words = set(re.findall(r"[a-z]+", unicodedata.normalize("NFKC", name).casefold()))
    agent_names = {re.sub(r"[^a-z]", "", a.casefold()) for a in AGENT_NAMES}
    if any(a in squashed for a in agent_names) or words & set(_NOT_HUMAN):
        raise ToolError(f"{field} must be a human; agents cannot approve or reject requests.")
    return name


class _Stale(Exception):
    """The data behind a request changed after it was filed."""


def _pay(conn, today: date, *, kind: str, ref_id: int, amount: float, account: str, approved_by: str) -> tuple[Payment, float]:
    """Record one payment and take it out of cash. Refuses rather than go negative."""
    if amount <= 0:
        raise ToolError(f"A payment must be positive (got ${amount:,.2f}); cash only goes out. Nothing was paid.")
    acct = _account(conn, account)
    balance = _money(acct["balance"])
    if amount > balance:
        raise ToolError(
            f"Not enough cash: {account} has ${balance:,.2f} and this payment is ${amount:,.2f}. Nothing was paid."
        )
    cur = conn.execute(
        "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?, ?, ?, ?, ?, ?)",
        (kind, ref_id, amount, account, today.isoformat(), approved_by),
    )
    new_balance = _money(balance - amount)
    conn.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?", (new_balance, today.isoformat(), account))
    payment = _payment(conn.execute("SELECT * FROM payments WHERE id = ?", (cur.lastrowid,)).fetchone())
    return payment, new_balance


def approve_request(
    approval_id: Annotated[int, Field(ge=1, le=SQLITE_MAX_INT, description="approvals.id to approve.")],
    approved_by: Annotated[str, Field(description="Name of the human approving. Agents cannot approve.")],
    note: Annotated[str, Field(description="Optional note for the record.")] = "",
    account: Annotated[str, Field(description="Cash account that pays.")] = "checking",
) -> DecisionResult:
    """HUMAN ONLY. Approve a pending request and carry it out in one step.
    invoice_payment: pay it, mark the invoice paid. rent_payment: pay it, move
    the lease's next_due one month on. purchase_order: pay the vendor and mark
    the order placed (refused while the vendor has an unpaid invoice).
    price_override: record the approved price. A payment is refused if the
    account does not have enough cash; balances never go negative. If the data
    behind the request changed since it was filed, the request is marked stale
    and nothing is paid."""
    approved_by = _human_name(approved_by, "approved_by")
    try:
        with _write_tx() as conn:
            today = _shop_today(conn)
            row = _approval_row(conn, approval_id)
            if row["status"] != "pending":
                raise ToolError(f"Approval request {approval_id} is already {row['status']}.")
            details, amount = json.loads(row["details"]), _money(row["amount"])
            payment, balance_after, changes = None, None, []

            if row["kind"] == "invoice_payment":
                inv = conn.execute("SELECT * FROM invoices WHERE id = ?", (row["ref_id"],)).fetchone()
                if inv is None or inv["status"].strip().lower() == PAID_STATUS:
                    raise _Stale(f"invoice {row['ref_id']} is missing or already paid.")
                if _money(inv["amount"]) != amount:
                    raise _Stale(f"invoice {row['ref_id']} is now ${inv['amount']:,.2f}, not the requested ${amount:,.2f}.")
                payment, balance_after = _pay(conn, today, kind="invoice", ref_id=inv["id"], amount=amount, account=account, approved_by=approved_by)
                conn.execute("UPDATE invoices SET status = ? WHERE id = ?", (PAID_STATUS, inv["id"]))
                changes += [f"payments: row {payment.payment_id} added", f"cash_accounts.{account}: balance now {balance_after:.2f}",
                            f"invoices.{inv['id']}: status paid"]

            elif row["kind"] == "rent_payment":
                lease = conn.execute("SELECT * FROM leases WHERE id = ?", (row["ref_id"],)).fetchone()
                if lease is None:
                    raise _Stale(f"lease {row['ref_id']} no longer exists.")
                if lease["next_due"] != details.get("for_due_date") or _money(lease["monthly_rent"]) != amount:
                    raise _Stale(
                        f"lease {lease['id']} is now ${lease['monthly_rent']:,.2f} due {lease['next_due']}, not "
                        f"${amount:,.2f} due {details.get('for_due_date')} (already paid or changed)."
                    )
                payment, balance_after = _pay(conn, today, kind="rent", ref_id=lease["id"], amount=amount, account=account, approved_by=approved_by)
                next_due = _add_month(_parse_date(lease["next_due"], "leases.next_due")).isoformat()
                conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (next_due, lease["id"]))
                changes += [f"payments: row {payment.payment_id} added", f"cash_accounts.{account}: balance now {balance_after:.2f}",
                            f"leases.{lease['id']}: next_due {lease['next_due']} -> {next_due}"]

            elif row["kind"] == "purchase_order":
                po = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (row["ref_id"],)).fetchone()
                if po is None or po["status"] != "pending_approval":
                    raise _Stale(f"purchase order {row['ref_id']} is missing or no longer pending.")
                price = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (po["sku"],)).fetchone()
                if price is None or _money(price["unit_cost"]) != _money(po["unit_cost"]):
                    raise _Stale(f"{po['sku']} unit cost is now {price['unit_cost'] if price else 'missing'}, not {po['unit_cost']}.")
                blocking = _vendor_unpaid(conn, po["vendor_id"])
                if blocking:  # temporary: the request stays pending
                    raise ToolError(
                        f"Vendor {po['vendor_id']} still has unpaid invoice(s) {', '.join(str(b.invoice_id) for b in blocking)} "
                        "and will not ship; approve those payments first. Nothing was paid."
                    )
                vendor = conn.execute("SELECT lead_days FROM vendors WHERE id = ?", (po["vendor_id"],)).fetchone()
                payment, balance_after = _pay(conn, today, kind="purchase_order", ref_id=po["id"], amount=amount, account=account, approved_by=approved_by)
                arrival = (today + timedelta(days=vendor["lead_days"])).isoformat()
                conn.execute(
                    "UPDATE purchase_orders SET status = 'ordered', ordered_at = ?, expected_arrival = ? WHERE id = ?",
                    (today.isoformat(), arrival, po["id"]),
                )
                changes += [f"payments: row {payment.payment_id} added", f"cash_accounts.{account}: balance now {balance_after:.2f}",
                            f"purchase_orders.{po['id']}: ordered, expected {arrival}"]

            elif row["kind"] == "price_override":
                price = conn.execute("SELECT unit_cost, list_price FROM pricing WHERE sku = ?", (details.get("sku"),)).fetchone()
                unit_price = details.get("unit_price")
                if price is None or not (price["unit_cost"] <= unit_price < price["list_price"]):
                    raise _Stale(f"{details.get('sku')} pricing changed: ${unit_price} is no longer at or above cost and below list.")
                changes.append(f"price override for {details.get('sku')} at ${unit_price} approved (no cash moves)")
            else:
                raise ToolError(f"Unknown approval kind {row['kind']!r}.")

            conn.execute(
                "UPDATE approvals SET status = 'approved', decided_by = ?, decided_at = ?, decision_note = ?, payment_id = ? WHERE id = ?",
                (approved_by, _now(), note.strip() or None, payment.payment_id if payment else None, approval_id),
            )
            changes.append(f"approvals.{approval_id}: approved by {approved_by}")
            approval = _approval(_approval_row(conn, approval_id))
    except _Stale as stale:
        # Nothing above was committed. Record the request as stale so a fresh one can be filed.
        with _write_tx() as conn:
            conn.execute(
                "UPDATE approvals SET status = 'stale', decided_by = 'system', decided_at = ?, decision_note = ? "
                "WHERE id = ? AND status = 'pending'", (_now(), f"stale: {stale}", approval_id),
            )
        raise ToolError(
            f"Approval request {approval_id} is stale: {stale} It is now marked stale, so a new request can be filed. Nothing was paid."
        )
    return DecisionResult(approval=approval, payment=payment, cash_balance_after=balance_after, changes=changes)


def reject_request(
    approval_id: Annotated[int, Field(ge=1, le=SQLITE_MAX_INT, description="approvals.id to reject.")],
    decided_by: Annotated[str, Field(description="Name of the human rejecting. Agents cannot reject.")],
    note: Annotated[str, Field(description="Why it was rejected.")] = "",
) -> DecisionResult:
    """HUMAN ONLY. Reject a pending request. Nothing is paid; a rejected
    purchase order is marked rejected."""
    decided_by = _human_name(decided_by, "decided_by")
    with _write_tx() as conn:
        row = _approval_row(conn, approval_id)
        if row["status"] != "pending":
            raise ToolError(f"Approval request {approval_id} is already {row['status']}.")
        changes = []
        if row["kind"] == "purchase_order":
            conn.execute("UPDATE purchase_orders SET status = 'rejected' WHERE id = ? AND status = 'pending_approval'", (row["ref_id"],))
            changes.append(f"purchase_orders.{row['ref_id']}: rejected")
        conn.execute(
            "UPDATE approvals SET status = 'rejected', decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
            (decided_by, _now(), note.strip() or None, approval_id),
        )
        changes.append(f"approvals.{approval_id}: rejected by {decided_by}")
        approval = _approval(_approval_row(conn, approval_id))
    return DecisionResult(approval=approval, changes=changes)


if HUMAN_TOOLS_ENABLED:
    mcp.tool(tags={"human"}, annotations=MOVES_MONEY)(approve_request)
    mcp.tool(tags={"human"}, annotations=WRITES)(reject_request)


if __name__ == "__main__":
    mcp.run(show_banner=False)
