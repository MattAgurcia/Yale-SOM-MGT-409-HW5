"""Data types for the Campus Customs agent team.

- AgentReport: what a teammate hands back when another agent asks it for help.
- BossDecision: the Boss's final call on one ticket.
- TeamDeps / RunState: the run context every agent shares (PydanticAI deps).
- TicketRun: what one team run on one ticket produced, for the caller.

Shop facts are not modelled here: they come from the MCP server's tools.
"""

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from audit import AuditTrail

AgentName = Literal["Boss", "Inventory", "Accounting", "Facilities", "Customer Service"]
AGENT_NAMES: tuple[AgentName, ...] = ("Boss", "Inventory", "Accounting", "Facilities", "Customer Service")
TicketStatus = Literal["open", "in_progress", "waiting_approval", "resolved", "escalated"]
StopReason = Literal["completed", "usage_limit", "error", "cancelled"]


class Fact(BaseModel):
    """One fact an agent relied on, and where it came from."""

    fact: str = Field(description="The fact in plain words with the exact number or date, e.g. 'Size <size> on hand: <n>'.")
    source: str = Field(
        description="Your own tool's name (e.g. check_stock_and_price), or 'Teammate (tool)' for a fact from a teammate's report, e.g. 'Inventory (list_vendors)'."
    )


class AgentReport(BaseModel):
    """A teammate's answer to a delegated request."""

    summary: str = Field(description="Two or three sentences that answer the request.")
    facts: list[Fact] = Field(description="Every fact the answer rests on, each with its source. No invented values.")
    actions_taken: list[str] = Field(
        description="Each change made through a tool by you or a teammate you asked, with who made it, its id and status (e.g. 'Accounting: approval <a>, PO <p> for <qty> <SKU> <size>, $<total>, pending'). Empty if none."
    )
    approval_ids: list[int] = Field(description="Approval requests created or relied on. Empty if none.")
    draft_ids: list[int] = Field(description="Drafts for a human to review: saved by you or a teammate you asked, or an existing one reused. Empty if none.")
    recommendation: str = Field(description="What the asking agent should do next.")
    blockers: list[str] = Field(description="What stops the work right now (e.g. vendor <id> blocked by unpaid invoice <id>). Empty if none.")
    needs_human: bool = Field(description="True if a human must approve or decide something before the work can finish.")


class BossDecision(BaseModel):
    """The Boss's final call on one ticket."""

    ticket_id: int
    status: TicketStatus = Field(description="The status the Boss set on the board with update_ticket_status.")
    decision: str = Field(description="The final call in plain words.")
    rationale: str = Field(description="Why, citing the facts and the shop rules that drove it.")
    agents_consulted: list[AgentName] = Field(description="Teammates who worked on this ticket.")
    facts: list[Fact] = Field(description="The facts the decision rests on, each with its source.")
    approval_ids: list[int] = Field(description="Pending approval requests this ticket waits on (another ticket's only if this one depends on it).")
    draft_ids: list[int] = Field(description="Drafts for a human to review: saved now, or an existing one reused. Empty if none.")
    human_actions: list[str] = Field(
        description="What a human must do next, e.g. 'Approve or reject approval <n> ($<amount>, invoice <id>)', 'Review and send draft <k>'."
    )
    next_steps: list[str] = Field(description="What happens after the human acts, e.g. reorder once the invoice is paid.")


@dataclass
class RunState:
    """Shared by every agent working on one ticket: the delegation allowance, and
    the status the top-level Boss last set on the board (checked against its decision)."""

    max_delegations: int
    max_depth: int
    used: int = 0
    status_set: str | None = None
    errored_calls: set[str] = field(default_factory=set)  # tool calls already audited as errors

    @property
    def left(self) -> int:
        return max(0, self.max_delegations - self.used)


@dataclass(frozen=True)
class TeamDeps:
    """Run context passed to every agent. Each delegation gets a copy with a longer chain."""

    run_id: str
    ticket_id: int | None
    agent: AgentName
    chain: tuple[AgentName, ...]  # who asked whom, Boss first; the last entry is this agent
    state: RunState  # shared (not copied) across the whole ticket run
    audit: "AuditTrail"
    toolsets: dict[str, Any] = field(default_factory=dict, compare=False)  # this run's MCP view per agent
    model: Any = field(default=None, compare=False)  # this run's gpt-6-luna client (None: the agent's default)

    @property
    def depth(self) -> int:
        """0 for the Boss at the top, 1 for an agent the Boss asked, and so on."""
        return len(self.chain) - 1

    def delegate_to(self, agent: AgentName) -> "TeamDeps":
        return replace(self, agent=agent, chain=self.chain + (agent,))


class UsageTotals(BaseModel):
    requests: int
    tool_calls: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


class TicketRun(BaseModel):
    """What one team run on one ticket produced."""

    run_id: str
    ticket_id: int
    stop_reason: StopReason
    decision: BossDecision | None = Field(description="None if the run stopped before the Boss finished.")
    error: str | None = None
    delegations_used: int
    usage: UsageTotals
    audit_file: str
    extra: dict[str, Any] = Field(default_factory=dict)
