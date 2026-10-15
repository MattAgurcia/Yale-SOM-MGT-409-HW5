"""The Campus Customs operations team: five PydanticAI agents that work tickets.

    Boss              reads each ticket, decides who works on it, makes the final call
    Inventory         stock by SKU and size, shortfalls, which vendor can restock
    Accounting        cash, invoices, margins; prepares payments and purchase orders for approval
    Facilities        the shop space: leases and rent
    Customer Service  drafts customer messages (never sends them)

Full connectivity: every agent has an ask_agent tool and may delegate to any
other agent. Every shop fact comes from the MCP server (mcp_server/server.py)
over the working database; this file adds no shop tools of its own. Each run
starts its own MCP server process, and each agent sees only the MCP tools its
job needs. The human-only approve_request / reject_request tools are not even
registered in that process.

Every agent-loop step is appended to output/audit_trail.json (see audit.py).
Every agent uses gpt-6-luna through Portkey.

Run tickets one after another from the project root. --reset first copies the
original database over the working copy (do this before a full run):
    .venv/bin/python backend/agents.py --reset 101 102 103
"""

import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from dotenv import find_dotenv, load_dotenv
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import ModelRetry, UsageLimitExceeded
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelRequest, RetryPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import RunUsage, UsageLimits

from audit import AuditTrail, clip
from models import AGENT_NAMES, AgentName, AgentReport, BossDecision, RunState, TeamDeps, TicketRun, UsageTotals

load_dotenv(find_dotenv())  # PORTKEY_API_KEY from the nearest .env up the tree
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

BACKEND = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND.parent
PROMPTS = BACKEND / "prompts"
MCP_SERVER = PROJECT_ROOT / "mcp_server" / "server.py"
ORIGINAL_DB = PROJECT_ROOT / "data" / "campus_customs.db"
WORKING_DB = PROJECT_ROOT / "data" / "campus_customs_new.db"

# --- Model: only gpt-6-luna, through Portkey, for every agent -------------------

MODEL_NAME = "gpt-6-luna"


def _build_model() -> OpenAIResponsesModel:
    """A gpt-6-luna client built from the current environment. The Responses API
    is used because Portkey's gpt-6-luna refuses tools plus reasoning on chat
    completions."""
    client = AsyncOpenAI(
        api_key=os.getenv("PORTKEY_API_KEY") or "missing",
        base_url=os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1"),
        default_headers={"x-portkey-provider": os.getenv("PORTKEY_PROVIDER", "openai")},
        timeout=90.0,
        max_retries=2,
    )
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


# --- Limits that keep token use in check (all per ticket, shared by the team) ----


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


MAX_REQUESTS = _env_int("TEAM_MAX_REQUESTS", 40)  # model calls across all five agents
MAX_TOOL_CALLS = _env_int("TEAM_MAX_TOOL_CALLS", 60)  # MCP + delegation calls across the team
MAX_TOKENS = _env_int("TEAM_MAX_TOKENS", 300_000)  # input + output tokens across the team
MAX_OUTPUT_TOKENS = _env_int("TEAM_MAX_OUTPUT_TOKENS", 8_000)  # per model response, reasoning included (3,000 was too tight: the full run hit it)
REASONING_EFFORT = os.getenv("TEAM_REASONING_EFFORT", "low")  # low keeps reasoning tokens small
MAX_DELEGATIONS = _env_int("TEAM_MAX_DELEGATIONS", 8)  # ask_agent calls per ticket
MAX_DEPTH = _env_int("TEAM_MAX_DEPTH", 2)  # Boss -> Inventory -> Accounting is depth 2
TOOL_RETRIES = _env_int("TEAM_TOOL_RETRIES", 2)  # a failing tool call or answer is retried at most this often

LIMITS = UsageLimits(request_limit=MAX_REQUESTS, tool_calls_limit=MAX_TOOL_CALLS, total_tokens_limit=MAX_TOKENS)
SETTINGS = OpenAIResponsesModelSettings(max_tokens=MAX_OUTPUT_TOKENS, openai_reasoning_effort=REASONING_EFFORT)

# --- MCP: one server process per run, a filtered view per agent ---------------------

READ_TOOLS = {
    "list_tickets", "get_ticket", "check_stock_and_price", "check_invoice", "check_lease",
    "list_vendors", "list_unpaid_invoices", "check_cash", "list_approvals", "list_drafts",
}
WRITE_TOOLS = {"request_payment", "create_purchase_order", "request_price_override", "save_customer_draft", "update_ticket_status"}
HUMAN_ONLY_TOOLS = {"approve_request", "reject_request"}  # never given to any agent

TOOLS_BY_AGENT: dict[AgentName, set[str]] = {
    "Boss": {"list_tickets", "get_ticket", "list_approvals", "list_drafts", "check_cash", "update_ticket_status"},
    "Inventory": {"get_ticket", "check_stock_and_price", "list_vendors", "check_invoice"},
    "Accounting": {
        "get_ticket", "check_cash", "list_unpaid_invoices", "check_invoice", "check_lease", "check_stock_and_price",
        "list_vendors", "list_approvals", "request_payment", "create_purchase_order", "request_price_override",
    },
    "Facilities": {"get_ticket", "check_lease", "list_approvals"},
    "Customer Service": {"get_ticket", "list_drafts", "check_stock_and_price", "save_customer_draft"},
}
assert all(tools <= READ_TOOLS | WRITE_TOOLS for tools in TOOLS_BY_AGENT.values())


def _server_env() -> dict[str, str]:
    """The MCP server's environment, read when the run starts: no model credentials
    (it never calls a model), and never the human-only tools."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PORTKEY_", "OPENAI_", "ANTHROPIC_"))}
    env.pop("CAMPUS_HUMAN_TOOLS", None)
    return {**env, "FASTMCP_LOG_LEVEL": env.get("FASTMCP_LOG_LEVEL", "WARNING")}


def _db_label(env: dict[str, str]) -> str:
    return env.get("CAMPUS_DB_PATH") or "data/campus_customs_new.db"


async def _check_and_stamp(ctx: RunContext[TeamDeps], call_tool: Any, name: str, args: dict[str, Any]) -> Any:
    """Last check before an MCP call leaves the backend. The tool must be this
    agent's; writes may only touch the ticket being worked; only the top-level
    Boss sets status; and write tools get the real agent's name, whatever the model sent."""
    deps = ctx.deps
    if name in HUMAN_ONLY_TOOLS or name not in TOOLS_BY_AGENT[deps.agent]:
        raise ModelRetry(f"{deps.agent} is not allowed to call {name}. Use your own tools or ask the teammate who has it.")
    if name in WRITE_TOOLS and args.get("ticket_id") != deps.ticket_id:
        raise ModelRetry(f"You are working ticket {deps.ticket_id}; write tools may only change that ticket.")
    if name == "update_ticket_status" and deps.depth > 0:
        raise ModelRetry("Only the Boss at the top of the run sets ticket status; put the status you recommend in your report instead.")
    if name in WRITE_TOOLS:
        args = {**args, "actor": deps.agent}
    result = await call_tool(name, args)
    if name == "update_ticket_status":
        deps.state.status_set = args["status"]  # the call succeeded; the decision must match it
    return result


def _hide_actor(ctx: RunContext[TeamDeps], tool_defs: list[ToolDefinition]) -> list[ToolDefinition]:
    """The backend fills in `actor`, so the model never sees (or spends tokens on) that argument."""
    out = []
    for td in tool_defs:
        schema = td.parameters_json_schema
        if "actor" in schema.get("properties", {}):
            schema = {
                **schema,
                "properties": {k: v for k, v in schema["properties"].items() if k != "actor"},
                "required": [r for r in schema.get("required", []) if r != "actor"],
            }
            td = replace(td, parameters_json_schema=schema)
        out.append(td)
    return out


def _mcp_for_run(env: dict[str, str]) -> MCPToolset:
    """A fresh MCP server process for one run; it exits when the run ends."""
    transport = StdioTransport(command=sys.executable, args=[str(MCP_SERVER)], env=env, cwd=str(PROJECT_ROOT), keep_alive=False)
    return MCPToolset(
        Client(transport),
        id="campus-customs",
        tool_error_behavior="retry",  # a ToolError goes back to the model so it can correct the call
        max_retries=TOOL_RETRIES,
        process_tool_call=_check_and_stamp,
    )


def _views(mcp: MCPToolset) -> dict[str, Any]:
    def view(agent: AgentName):
        allowed = TOOLS_BY_AGENT[agent]
        return mcp.filtered(lambda ctx, td: td.name in allowed).prepared(_hide_actor)

    return {name: view(name) for name in AGENT_NAMES}


# --- Audit: one entry per agent-loop step ------------------------------------------


def _where(ctx: RunContext[TeamDeps]) -> dict[str, Any]:
    d = ctx.deps
    return {"run_id": d.run_id, "ticket_id": d.ticket_id, "agent": d.agent, "depth": d.depth, "chain": list(d.chain)}


def _usage(u: RunUsage, pending_requests: int = 0) -> dict[str, int]:
    return {"requests": u.requests + pending_requests, "tool_calls": u.tool_calls, "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens, "total_tokens": u.input_tokens + u.output_tokens}


def _logged_args(ctx: RunContext[TeamDeps], tool: str, args: Any) -> Any:
    """The arguments that actually reached the MCP server (actor as stamped)."""
    args = dict(args) if isinstance(args, dict) else args
    if tool in WRITE_TOOLS and isinstance(args, dict):
        args["actor"] = ctx.deps.agent
    return args


@dataclass
class AuditSteps(AbstractCapability[TeamDeps]):
    """Appends each step of an agent's loop to the audit trail as it happens."""

    agent: str

    async def before_run(self, ctx: RunContext[TeamDeps]) -> None:
        ctx.deps.audit.append("agent_start", **_where(ctx), prompt=ctx.prompt if isinstance(ctx.prompt, str) else str(ctx.prompt))

    async def wrap_model_request(self, ctx: RunContext[TeamDeps], *, request_context: Any, handler: Any) -> Any:
        self._record_refusals(ctx, request_context)
        started = time.perf_counter()
        try:
            response = await handler(request_context)
        except BaseException as error:  # the request may still have been billed
            ctx.deps.audit.append("model_error", **_where(ctx), step=ctx.run_step, model=MODEL_NAME,
                                  error=f"{type(error).__name__}: {error}", ms=round((time.perf_counter() - started) * 1000))
            raise
        output_tools = {t.name for t in request_context.model_request_parameters.output_tools}
        calls = [{"tool": "final_answer" if p.tool_name in output_tools else p.tool_name, "args": p.args_as_dict()}
                 for p in response.parts if isinstance(p, ToolCallPart)]
        text = "".join(p.content for p in response.parts if isinstance(p, TextPart))
        u = response.usage
        ctx.deps.audit.append(
            "model_step", **_where(ctx), step=ctx.run_step, model=response.model_name or MODEL_NAME,
            finish_reason=response.finish_reason, tool_calls=calls, text=text or None,
            tokens={"input": u.input_tokens, "cached": u.cache_read_tokens, "output": u.output_tokens},
            team_usage_so_far=_usage(ctx.usage, pending_requests=1), ms=round((time.perf_counter() - started) * 1000),
        )
        return response

    def _record_refusals(self, ctx: RunContext[TeamDeps], request_context: Any) -> None:
        """Calls the framework refused before any tool ran (unknown or disallowed tool,
        bad arguments, an answer that failed validation): what the model was told."""
        last = request_context.messages[-1] if request_context.messages else None
        if not isinstance(last, ModelRequest):
            return
        output_tools = {t.name for t in request_context.model_request_parameters.output_tools}
        for part in last.parts:
            if isinstance(part, RetryPromptPart) and part.tool_call_id not in ctx.deps.state.errored_calls:
                tool = "final_answer" if part.tool_name is None or part.tool_name in output_tools else part.tool_name
                reason = part.content if isinstance(part.content, str) else json.dumps(part.content, default=str)
                ctx.deps.audit.append("call_refused", **_where(ctx), step=ctx.run_step, tool=tool, reason=reason)

    async def wrap_tool_execute(self, ctx: RunContext[TeamDeps], *, call: ToolCallPart, tool_def: ToolDefinition, args: Any, handler: Any) -> Any:
        started = time.perf_counter()
        base = {**_where(ctx), "step": ctx.run_step, "tool": call.tool_name, "args": _logged_args(ctx, call.tool_name, args)}
        try:
            result = await handler(args)
        except Exception as error:
            # ModelRetry from a ToolError or a backend check: the model sees the message and may try again.
            ctx.deps.state.errored_calls.add(call.tool_call_id)
            ctx.deps.audit.append("tool_call", **base, status="error", error=f"{type(error).__name__}: {error}",
                                  ms=round((time.perf_counter() - started) * 1000))
            raise
        except BaseException as error:  # cancelled mid-call: a write may already have committed
            ctx.deps.audit.append("tool_call", **base, status="cancelled", error=type(error).__name__,
                                  ms=round((time.perf_counter() - started) * 1000))
            raise
        ctx.deps.audit.append("tool_call", **base, status="ok", result=result, ms=round((time.perf_counter() - started) * 1000))
        return result

    async def after_run(self, ctx: RunContext[TeamDeps], *, result: Any) -> Any:
        ctx.deps.audit.append("agent_end", **_where(ctx), stop_reason="final_answer", output=result.output,
                              team_usage_so_far=_usage(ctx.usage))
        return result

    async def on_run_error(self, ctx: RunContext[TeamDeps], *, error: BaseException) -> Any:
        reason = "usage_limit" if isinstance(error, UsageLimitExceeded) else "error"
        ctx.deps.audit.append("agent_end", **_where(ctx), stop_reason=reason, error=f"{type(error).__name__}: {error}",
                              team_usage_so_far=_usage(ctx.usage))
        raise error


# --- Delegation: any agent may ask any other agent ----------------------------------


async def ask_agent(ctx: RunContext[TeamDeps], agent: AgentName, request: str) -> AgentReport | str:
    """Ask a teammate to do part of this ticket's work and wait for their report.

    Args:
        agent: The teammate to ask (any agent except yourself).
        request: Exactly what you need back, with every id, SKU, size, quantity
            and amount they need to do it. They cannot see your conversation.
    """
    deps = ctx.deps
    state = deps.state
    refusal = None
    if agent == deps.agent:
        refusal = "You cannot delegate to yourself. Use your own tools."
    elif deps.depth + 1 > state.max_depth:
        refusal = (f"Delegation depth limit reached ({state.max_depth}). Finish with what you have and "
                   "name what is missing in your answer.")
    elif state.left == 0:
        refusal = (f"This ticket's delegation budget ({state.max_delegations}) is used up. Finish with what you "
                   "have and name what is missing in your answer.")
    if refusal:
        deps.audit.append("delegation_refused", **_where(ctx), to=agent, request=request, reason=refusal)
        return refusal

    state.used += 1
    child = deps.delegate_to(agent)
    deps.audit.append("delegation", **_where(ctx), to=agent, request=request,
                      delegations_used=state.used, delegations_left=state.left)
    prompt = (
        f"Ticket {deps.ticket_id}. {deps.agent} asks you ({agent}) for help.\n\n"
        f"Request: {request}\n\n"
        "Rely on the tool-sourced facts in the request; use your tools for anything missing or that a write "
        "depends on, and answer with your report."
    )
    try:
        result = await TEAM[agent].run(
            prompt, deps=child, model=deps.model, usage=ctx.usage, usage_limits=LIMITS,
            output_type=AgentReport, toolsets=[deps.toolsets[agent]],
        )
    except UsageLimitExceeded:
        raise  # the whole ticket run stops; run_ticket records why
    except Exception as error:  # a teammate failing should not sink the asking agent
        deps.audit.append("delegation_failed", **_where(ctx), to=agent, error=f"{type(error).__name__}: {error}")
        return f"{agent} could not finish ({type(error).__name__}: {error}). Continue without them and say so."
    return result.output


# --- The agents --------------------------------------------------------------------

PROMPT_FILES: dict[AgentName, str] = {
    "Boss": "boss.md", "Inventory": "inventory.md", "Accounting": "accounting.md",
    "Facilities": "facilities.md", "Customer Service": "customer_service.md",
}


def _situation(ctx: RunContext[TeamDeps]) -> str:
    """Per-run note: who this agent is in the chain, and the live limits."""
    d = ctx.deps
    return (
        f"## This run\nYou are {d.agent}. Ticket: {d.ticket_id}. Chain so far: {' -> '.join(d.chain)} "
        f"(depth {d.depth} of at most {d.state.max_depth}). Delegations left for this ticket: "
        f"{d.state.left} of {d.state.max_delegations}. Team limits for this ticket (these override any numbers "
        f"elsewhere in your instructions): {MAX_REQUESTS} model requests, {MAX_TOOL_CALLS} tool calls, "
        f"{MAX_TOKENS:,} tokens, {MAX_OUTPUT_TOKENS:,} output tokens per response."
    )


async def _check_decision(ctx: RunContext[TeamDeps], output: Any) -> Any:
    """The top-level Boss's decision must be about this ticket and match the board."""
    if isinstance(output, BossDecision) and ctx.deps.depth == 0:
        if output.ticket_id != ctx.deps.ticket_id:
            raise ModelRetry(f"Your decision is for ticket {output.ticket_id}, but you are working ticket {ctx.deps.ticket_id}.")
        board = ctx.deps.state.status_set
        if board is None:
            raise ModelRetry("Set the ticket's status with update_ticket_status before giving your final decision.")
        if output.status != board:
            raise ModelRetry(f"Your decision says status '{output.status}', but you set '{board}' on the board. Make them match.")
    return output


def _build(name: AgentName) -> Agent[TeamDeps, Any]:
    agent = Agent(
        _build_model(),  # replaced per run by run_ticket's model (built from the environment at that moment)
        name=name,
        deps_type=TeamDeps,
        output_type=BossDecision if name == "Boss" else AgentReport,
        instructions=(PROMPTS / PROMPT_FILES[name]).read_text(encoding="utf-8"),
        tools=[ask_agent],  # the MCP tools are added per run (run_ticket / ask_agent)
        model_settings=SETTINGS,
        retries=TOOL_RETRIES,
        capabilities=[AuditSteps(name)],
    )
    agent.instructions(_situation)
    if name == "Boss":
        agent.output_validator(_check_decision)
    return agent


TEAM: dict[AgentName, Agent[TeamDeps, Any]] = {name: _build(name) for name in AGENT_NAMES}


# --- Running a ticket ------------------------------------------------------------------


async def run_ticket(ticket_id: int, audit: AuditTrail | None = None, run_id: str | None = None) -> TicketRun:
    """The Boss works one ticket, delegating as needed, inside the team-wide limits.
    A caller (the API) may pass its own run_id so it can report it before the run ends."""
    audit = audit or AuditTrail()
    run_id = run_id or uuid.uuid4().hex[:12]
    state = RunState(MAX_DELEGATIONS, MAX_DEPTH)
    usage = RunUsage()
    env = _server_env()
    zero = UsageTotals(**_usage(usage))
    try:
        audit.append("run_start", run_id=run_id, ticket_id=ticket_id, model=MODEL_NAME, database=_db_label(env),
                     limits={"requests": MAX_REQUESTS, "tool_calls": MAX_TOOL_CALLS, "total_tokens": MAX_TOKENS,
                             "output_tokens_per_response": MAX_OUTPUT_TOKENS, "reasoning_effort": REASONING_EFFORT,
                             "delegations": MAX_DELEGATIONS, "depth": MAX_DEPTH, "tool_retries": TOOL_RETRIES})
    except Exception as exc:  # no audit trail, no run
        return TicketRun(run_id=run_id, ticket_id=ticket_id, stop_reason="error", decision=None, delegations_used=0,
                         error=f"Audit trail unavailable, so the run did not start: {type(exc).__name__}: {exc}",
                         usage=zero, audit_file=str(audit.path))

    decision, error, stop, cancelled = None, None, "completed", None
    try:
        if not os.getenv("PORTKEY_API_KEY"):
            raise RuntimeError("PORTKEY_API_KEY is not set (looked in the environment and the nearest .env).")
        model = _build_model()
        mcp = _mcp_for_run(env)
        views = _views(mcp)
        deps = TeamDeps(run_id=run_id, ticket_id=ticket_id, agent="Boss", chain=("Boss",), state=state,
                        audit=audit, toolsets=views, model=model)
        async with mcp:
            result = await TEAM["Boss"].run(
                f"Work ticket {ticket_id}. Start by reading it with get_ticket, then follow your workflow.",
                deps=deps, model=model, usage=usage, usage_limits=LIMITS, toolsets=[views["Boss"]],
            )
        decision = result.output
    except UsageLimitExceeded as exc:
        stop, error = "usage_limit", str(exc)
    except Exception as exc:
        stop, error = "error", f"{type(exc).__name__}: {exc}"
    except BaseException as exc:  # cancelled (timeout, disconnect, Ctrl-C): record it, then let it propagate
        stop, error, cancelled = "cancelled", type(exc).__name__, exc
    finally:
        totals = UsageTotals(**_usage(usage))
        try:
            audit.append("run_end", run_id=run_id, ticket_id=ticket_id, stop_reason=stop, error=error,
                         delegations_used=state.used, board_status=state.status_set, usage=totals, decision=decision)
        except Exception:
            pass  # the run already happened; the caller still gets the result
    if cancelled is not None:
        raise cancelled
    return TicketRun(run_id=run_id, ticket_id=ticket_id, stop_reason=stop, decision=decision, error=error,
                     delegations_used=state.used, usage=totals, audit_file=str(audit.path))


# --- Command line ------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def working_db_path() -> Path:
    """The database the MCP server uses: CAMPUS_DB_PATH (relative to the project root) or the working copy."""
    path = Path(os.environ.get("CAMPUS_DB_PATH") or "data/campus_customs_new.db")
    return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()


def reset_working_db(audit: AuditTrail | None = None) -> dict[str, str]:
    """Copy the original database over the working copy (the reset before a full run).
    The copy is swapped in atomically, and the original is never the target."""
    target = working_db_path()
    if target == ORIGINAL_DB.resolve() or (target.exists() and os.path.samefile(target, ORIGINAL_DB)):
        raise ValueError("Refusing to reset: the target is the original database.")
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".", suffix=".resetting")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out, open(ORIGINAL_DB, "rb") as src:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
        digest = _sha256(tmp)  # the bytes that will be swapped in
        os.replace(tmp, target)  # atomic: readers see the old file or the new one, never a partial copy
    finally:
        tmp.unlink(missing_ok=True)
    for side in ("-journal", "-wal", "-shm"):  # stale SQLite side files would not match the fresh copy
        target.with_name(target.name + side).unlink(missing_ok=True)
    info = {"database": _db_label(os.environ), "copied_from": "data/campus_customs.db", "sha256": digest}
    (audit or AuditTrail()).append("db_reset", **info)
    return info


async def _main(argv: list[str]) -> None:
    reset = "--reset" in argv
    ids = [a for a in argv if a != "--reset"]
    if not ids or not all(a.isdigit() for a in ids):
        raise SystemExit(__doc__)
    if reset:
        reset_working_db()
    elif _sha256(working_db_path()) != _sha256(ORIGINAL_DB):
        print("Note: the working copy already holds earlier changes. Use --reset before a full run.", file=sys.stderr)
    for ticket_id in map(int, ids):  # one after another, so tickets never race for the same cash
        run = await run_ticket(ticket_id)
        print(json.dumps(clip(run), indent=2))


if __name__ == "__main__":
    asyncio.run(_main(sys.argv[1:]))
