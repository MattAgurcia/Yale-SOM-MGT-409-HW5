"""Campus Customs backend API: the routes the operations dashboard calls.

Start it from the backend/ folder, with the project's virtual environment active:
    uvicorn main:app --reload --port 8000

Every shop fact and every change goes through the MCP server (mcp_server/server.py):
- The "desk" connection below is the human side. It reads the board, and it is
  the only process started with CAMPUS_HUMAN_TOOLS=1, so it is the only place
  approve_request / reject_request exist. A human clicking Approve is the only
  thing that moves cash.
- Agent runs (agents.run_ticket) start their own MCP server without those tools.

Agent events come from the append-only audit trail (output/audit_trail.json).
Browsers may call it from any http://localhost or http://127.0.0.1 port (the Vite
dev server); CORS_ORIGINS adds other origins. Interactive docs: /docs
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from pydantic import BaseModel, Field, StringConstraints

import agents
from audit import AuditTrail

# --- The desk's MCP connection (human side) ------------------------------------------


class ToolRefused(Exception):
    """An MCP tool said no (unknown id, not enough cash, stale request, ...)."""


class DeskDown(Exception):
    """The desk's MCP server could not be reached."""


def _desk_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PORTKEY_", "OPENAI_", "ANTHROPIC_"))}
    return {**env, "CAMPUS_HUMAN_TOOLS": "1", "FASTMCP_LOG_LEVEL": env.get("FASTMCP_LOG_LEVEL", "WARNING")}


MONEY_TOOLS = {"approve_request", "reject_request"}  # never retried blindly: the first try may have landed


class Desk:
    """One MCP server process for the dashboard's reads and the human's decisions.
    If the process dies, the next call restarts it."""

    def __init__(self) -> None:
        self.client: Client | None = None
        self.lock = asyncio.Lock()

    async def start(self) -> None:
        transport = StdioTransport(command=sys.executable, args=[str(agents.MCP_SERVER)], env=_desk_env(),
                                   cwd=str(agents.PROJECT_ROOT), keep_alive=False)
        self.client = Client(transport)
        await self.client.__aenter__()

    async def stop(self) -> None:
        client, self.client = self.client, None
        if client is not None:
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass  # already dead

    async def _restart(self) -> None:
        await self.stop()
        await self.start()

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> Any:
        async with self.lock:  # one call at a time on this connection
            for attempt in (1, 2):
                try:
                    if self.client is None:
                        await self.start()
                    result = await self.client.call_tool(tool, args or {}, raise_on_error=False)
                    break
                except Exception as error:  # the server process died or the pipe broke
                    try:
                        await self._restart()
                    except Exception as restart_error:
                        raise DeskDown(f"The shop's MCP server is not responding ({restart_error}).") from error
                    if attempt == 2 or tool in MONEY_TOOLS:
                        raise DeskDown(f"The shop's MCP server dropped the call to {tool} ({type(error).__name__}); "
                                       "it has been restarted. Check the board before trying again.") from error
        if result.is_error:
            raise ToolRefused(result.content[0].text if result.content else f"{tool} failed")
        data = result.structured_content or {}
        return data["result"] if set(data) == {"result"} else data  # list results come wrapped

    async def ping(self) -> bool:
        try:
            await self.call("list_tickets")
            return True
        except Exception:
            return False


desk = Desk()
audit = AuditTrail()


class QuietPolls(logging.Filter):
    """The dashboard polls every second or so. Keep its routine reads out of the
    terminal: drop successful GET/OPTIONS lines from uvicorn's access log, but
    keep every POST (runs, approvals, resets) and every error."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        if len(args) >= 5:
            method, status = args[1], args[4]
            if method in ("GET", "OPTIONS") and isinstance(status, int) and status < 400:
                return False
        return True


logging.getLogger("uvicorn.access").addFilter(QuietPolls())

_SERVER_PROBLEMS = ("working database not found", "not the shop database", "refusing to open", "could not read")


def _http_error(error: Exception) -> HTTPException:
    if isinstance(error, DeskDown):
        return HTTPException(503, str(error))
    message = str(error)
    lowered = message.lower()
    if any(p in lowered for p in _SERVER_PROBLEMS):
        return HTTPException(503, message)  # a server set-up problem, not the shop saying no
    if lowered.startswith("no ") and (" with id " in lowered or "no product" in lowered):
        return HTTPException(404, message)
    if "validation error" in lowered:
        return HTTPException(422, message)
    return HTTPException(409, message)  # the shop's state says no: not enough cash, already decided, stale...


async def _tool(tool: str, args: dict[str, Any] | None = None) -> Any:
    try:
        return await desk.call(tool, args)
    except (ToolRefused, DeskDown) as error:
        raise _http_error(error) from error


# --- Agent runs: one at a time, in the background -------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RunRecord:
    run_id: str
    ticket_id: int
    status: Literal["running", "completed", "usage_limit", "error", "cancelled"] = "running"
    started_at: str = field(default_factory=_now)
    finished_at: str | None = None
    result: dict[str, Any] | None = None  # the TicketRun: decision, usage, delegations, error
    error: str | None = None

    def view(self) -> dict[str, Any]:
        return asdict(self)


RUNS: dict[str, RunRecord] = {}
TASKS: dict[str, asyncio.Task] = {}
current_run: str | None = None  # tickets run one at a time, so they never race for the same cash
# Held while a run is being admitted and while a reset copies the database, so
# a run, a second run and a reset can never overlap.
desk_gate = asyncio.Lock()


async def _execute(record: RunRecord) -> None:
    global current_run
    try:
        run = await agents.run_ticket(record.ticket_id, audit=audit, run_id=record.run_id)
        record.status, record.result, record.error = run.stop_reason, run.model_dump(mode="json"), run.error
    except asyncio.CancelledError:
        record.status, record.error = "cancelled", "the server stopped during the run"
        raise
    except Exception as error:  # run_ticket reports its own errors; this is a last resort
        record.status, record.error = "error", f"{type(error).__name__}: {error}"
    finally:
        record.finished_at = _now()
        if current_run == record.run_id:
            current_run = None
        TASKS.pop(record.run_id, None)


# --- App --------------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    await desk.start()
    try:
        yield
    finally:
        for task in list(TASKS.values()):  # a stopping server cancels its run; run_end records it
            task.cancel()
        await asyncio.gather(*TASKS.values(), return_exceptions=True)
        await desk.stop()


app = FastAPI(
    title="Campus Customs operations desk",
    description="Tickets, agent runs, agent events, human approvals, cash, and reset.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,  # the React dashboard (Vite dev server) runs on another port
    # The Vite dev server's origin, plus any extras in CORS_ORIGINS. The regex also
    # lets in other local ports (Vite moves to 5174 when 5173 is busy).
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"]
    + [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """Is the API up and can it reach the shop's MCP server? Also the database,
    audit file and model it uses, and any run in progress."""
    desk_ok = await desk.ping()
    return {"ok": desk_ok, "desk": "up" if desk_ok else "down", "database": agents._db_label(os.environ),
            "audit_file": str(audit.path), "model": agents.MODEL_NAME,
            "running": RUNS[current_run].view() if current_run else None}


# --- Tickets ------------------------------------------------------------------------------


@app.get("/api/tickets")
async def list_tickets() -> dict[str, Any]:
    """Every ticket with its board status and state: 'resolved' only when the Boss
    set resolved; open, in_progress, waiting_approval and escalated count as 'open'.
    (After a human approves a ticket's requests, run the ticket again so the Boss
    can re-check and resolve it.)"""
    board = await _tool("list_tickets")
    running = RUNS[current_run].ticket_id if current_run else None
    for t in board["tickets"]:
        t["state"] = "resolved" if t["status"] == "resolved" else "open"
        t["running"] = t["ticket_id"] == running
    return {**board, "running_ticket_id": running}


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: int) -> dict[str, Any]:
    """One ticket with its status history, drafts and approval requests."""
    return await _tool("get_ticket", {"ticket_id": ticket_id})


@app.post("/api/tickets/{ticket_id}/run", status_code=202)
async def run_ticket(
    ticket_id: int,
    response: Response,
    wait: bool = Query(False, description="Wait for the run to finish instead of returning at once."),
) -> dict[str, Any]:
    """Start the agent team on one ticket. Returns at once with a run_id (watch
    /api/events and /api/runs/{run_id}); only one run at a time."""
    global current_run
    async with desk_gate:  # check and claim the run slot as one step
        if current_run:
            running = RUNS[current_run]
            raise HTTPException(409, f"Ticket {running.ticket_id} is already running (run {running.run_id}). "
                                     "Runs go one at a time so tickets never race for the same cash.")
        await _tool("get_ticket", {"ticket_id": ticket_id})  # 404 for an unknown ticket
        record = RunRecord(run_id=uuid.uuid4().hex[:12], ticket_id=ticket_id)
        RUNS[record.run_id], current_run = record, record.run_id
        TASKS[record.run_id] = task = asyncio.create_task(_execute(record))
    if wait:
        await asyncio.shield(task)  # a dropped connection does not cancel the run
        response.status_code = 200
    return record.view()


@app.get("/api/runs")
async def list_runs() -> dict[str, Any]:
    """Runs started since the server started, newest first."""
    return {"running": current_run, "runs": [r.view() for r in reversed(RUNS.values())]}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """One run: running, or finished with the Boss's decision, usage and stop reason."""
    if run_id not in RUNS:
        raise HTTPException(404, f"No run with id {run_id} since the server started.")
    return RUNS[run_id].view()


# --- Agent events (from the audit trail) ---------------------------------------------------

_BASE = {"seq", "ts", "event", "run_id", "ticket_id", "agent", "depth"}


def _report_text(out: dict[str, Any]) -> str | None:
    """The words an agent ended with: its answer, then what it recommends and what blocks it."""
    if "decision" in out:  # the Boss's final call
        parts = [out.get("decision")]
        if out.get("human_actions"):
            parts.append("Human actions: " + "; ".join(out["human_actions"]))
    else:
        parts = [out.get("summary")]
        if out.get("recommendation"):
            parts.append("Recommends: " + out["recommendation"])
        if out.get("blockers"):
            parts.append("Blockers: " + "; ".join(out["blockers"]))
    return " ".join(p for p in parts if p) or None


def _said_and_tools(e: dict[str, Any]) -> tuple[str | None, list[str]]:
    """What the agent said, and which tools it used, in one step of the trail."""
    kind = e["event"]
    if kind == "model_step":  # what the model wrote (often nothing but tool calls) and the tools it chose
        return e.get("text"), [c["tool"] for c in e.get("tool_calls", [])]
    if kind == "tool_call":
        return None, [e["tool"]]
    if kind == "call_refused":
        return e.get("reason"), [e["tool"]]
    if kind == "delegation":  # the asker's words to the teammate
        return f"Asks {e['to']}: {e['request']}", ["ask_agent"]
    if kind == "delegation_refused":
        return f"Could not ask {e['to']}: {e['reason']}", ["ask_agent"]
    if kind == "delegation_failed":
        return f"{e['to']} could not finish: {e.get('error')}", ["ask_agent"]
    if kind == "agent_end":
        out = e.get("output")
        return (_report_text(out) if isinstance(out, dict) else e.get("error")), []
    if kind == "run_end":
        return f"Run {e.get('stop_reason')}" + (f": {e['error']}" if e.get("error") else ""), []
    if kind == "human_decision":
        verb = "approve" if e.get("decision") == "approved" else "reject"
        if e.get("outcome") == "refused":
            return f"{e.get('decided_by')} tried to {verb} approval {e.get('approval_id')}; refused: {e.get('error')}", [e.get("tool", "")]
        return f"{e.get('decided_by')} {e.get('decision')} approval {e.get('approval_id')}", [e.get("tool", "")]
    return None, []  # agent_start (the request is in detail.prompt), run_start, db_reset, ...


def _read_trail() -> list[dict[str, Any]]:
    if not audit.path.exists() or audit.path.stat().st_size == 0:
        return []
    try:
        data = json.loads(audit.path.read_text(encoding="utf-8"))  # swapped in atomically, so never half-written
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise HTTPException(500, f"The audit trail could not be read: {error}") from error
    return data if isinstance(data, list) else []


@app.get("/api/events")
async def events(
    since: int = Query(0, ge=0, description="Only events after this seq: pass the last_seq from your previous call."),
    limit: int = Query(200, ge=1, le=2000, description="At most this many events per call."),
    ticket_id: int | None = Query(None, description="Only this ticket's events."),
    run_id: str | None = Query(None, description="Only this run's events."),
) -> dict[str, Any]:
    """Agent events, oldest first: what each agent said (`said`) and which tools it
    used (`tools`). With since=0 you get the newest `limit` events. With since=N you
    get the next `limit` events after N; if has_more is true, call again with the
    returned last_seq. Nothing is ever skipped."""
    trail = _read_trail()
    trail_last = trail[-1]["seq"] if trail else 0
    restarted = since > trail_last  # the trail was set aside and started again
    if restarted:
        since = 0
    matching = [e for e in trail if e.get("seq", 0) > since
                and (ticket_id is None or e.get("ticket_id") == ticket_id)
                and (run_id is None or e.get("run_id") == run_id)]
    if since == 0:
        picked, has_more = matching[-limit:], False  # first load: the newest events
        older_skipped = len(matching) - len(picked)
    else:
        picked, has_more, older_skipped = matching[:limit], len(matching) > limit, 0
    out = []
    for e in picked:
        said, tools = _said_and_tools(e)
        out.append({**{k: e.get(k) for k in _BASE}, "said": said, "tools": tools,
                    "detail": {k: v for k, v in e.items() if k not in _BASE}})
    return {
        "events": out,
        "last_seq": picked[-1]["seq"] if has_more else trail_last,  # pass this as `since` next time
        "has_more": has_more,
        "older_events_not_shown": older_skipped,
        "trail_restarted": restarted,
        "running": RUNS[current_run].view() if current_run else None,
    }


# --- Human approvals: the only routes that move cash ---------------------------------------

HumanName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class Approve(BaseModel):
    approved_by: HumanName = Field(description="Name of the human approving.")
    note: str = Field("", max_length=1000)


class Reject(BaseModel):
    decided_by: HumanName = Field(description="Name of the human rejecting.")
    note: str = Field("", max_length=1000)


@app.get("/api/approvals")
async def list_approvals(
    status: Literal["pending", "approved", "rejected", "stale"] | None = None,
    ticket_id: int | None = None,
) -> list[dict[str, Any]]:
    """Approval requests the agents prepared (payments, purchase orders, discounts)."""
    args = {k: v for k, v in {"status": status, "ticket_id": ticket_id}.items() if v is not None}
    return await _tool("list_approvals", args)


async def _approval_ticket(approval_id: int) -> int | None:
    try:
        return next((a["ticket_id"] for a in await desk.call("list_approvals") if a["approval_id"] == approval_id), None)
    except Exception:
        return None


async def _decide(tool: str, approval_id: int, decision: str, args: dict[str, Any], by: str) -> dict[str, Any]:
    entry = {"approval_id": approval_id, "decision": decision, "decided_by": by, "tool": tool}
    try:
        result = await desk.call(tool, {"approval_id": approval_id, **args})
    except (ToolRefused, DeskDown) as error:
        not_human = "must be a human" in str(error)
        audit.append("human_decision", **entry, agent=f"Unverified ({by})" if not_human else f"Human ({by})",
                     ticket_id=await _approval_ticket(approval_id), outcome="refused", error=str(error))
        raise _http_error(error) from error
    audit.append("human_decision", **entry, agent=f"Human ({by})", outcome="done",
                 ticket_id=result["approval"]["ticket_id"], kind=result["approval"]["kind"],
                 amount=result["approval"]["amount"], payment=result.get("payment"),
                 cash_balance_after=result.get("cash_balance_after"), changes=result.get("changes"))
    return result


@app.post("/api/approvals/{approval_id}/approve")
async def approve(approval_id: int, body: Approve) -> dict[str, Any]:
    """A human approves a request. For a payment or purchase order this is what
    actually moves cash (refused if cash is short or the vendor is still blocked)."""
    result = await _decide("approve_request", approval_id, "approved",
                           {"approved_by": body.approved_by, "note": body.note}, body.approved_by)
    return {**result, "cash": await cash()}


@app.post("/api/approvals/{approval_id}/reject")
async def reject(approval_id: int, body: Reject) -> dict[str, Any]:
    """A human rejects a request. Nothing is paid."""
    return await _decide("reject_request", approval_id, "rejected",
                         {"decided_by": body.decided_by, "note": body.note}, body.decided_by)


# --- Cash and reset -------------------------------------------------------------------------


@app.get("/api/cash")
async def cash() -> dict[str, Any]:
    """The checking balance from cash_accounts, the pending requests that would
    move cash, and what checking would hold if every one were approved."""
    c = await _tool("check_cash")
    checking = next((a for a in c["accounts"] if a["name"] == "checking"), None)
    if checking is None:
        raise HTTPException(404, "No 'checking' account in cash_accounts.")
    balance, pending = checking["balance"], c["pending_total"]
    return {"account": "checking", "balance": balance, "as_of": checking["date"], "date_today": c["date_today"],
            "pending_total": pending, "pending_payments": c["pending_payments"],
            "balance_if_all_pending_paid": round(balance - pending, 2), "can_cover_all_pending": balance >= pending,
            "payments": c["payments"]}


@app.post("/api/reset")
async def reset() -> dict[str, Any]:
    """Copy the original database over the working copy for a fresh run. Refused
    while a run is in progress. The audit trail is kept (it is append-only)."""
    async with desk_gate:  # no run can start, and no second reset can run, while the file is swapped
        if current_run:
            raise HTTPException(409, f"Ticket {RUNS[current_run].ticket_id} is running; reset after it finishes.")
        try:
            info = await asyncio.to_thread(agents.reset_working_db, audit)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
    return {**info, "tickets": (await list_tickets())["tickets"], "cash": await cash()}
