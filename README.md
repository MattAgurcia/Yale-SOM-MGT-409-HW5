# Campus Customs Multi-Agent Operations (Yale SOM MGT 409, HW 5)

Campus Customs is a Yale merch shop. Its tickets (a customer order, a rent
notice, a bulk discount request) are worked by five PydanticAI agents (Boss,
Inventory, Accounting, Facilities, Customer Service) on gpt-6-luna through
Portkey. Every shop fact comes from an MCP server over a SQLite database, a
FastAPI backend runs the team, and a React board lets a human watch the agents
and approve or reject every payment.

| Part | Where |
|---|---|
| Shop data | `data/campus_customs.db` (the original, never changed) and `data/campus_customs_new.db` (the working copy every tool uses) |
| MCP server | `mcp_server/server.py` (tools listed in `mcp_server/README.md`) |
| Agent team | `backend/agents.py`, `backend/models.py`, `backend/audit.py`, prompts in `backend/prompts/` |
| API | `backend/main.py` |
| Board | `frontend/` (React + Vite + TypeScript) |
| Deliverables | `output/` (harness, smoke test, desk tickets, design, resolved tickets, board screenshots, audit trail) |
| Cash checks | `tests/cash/` |

The working copy in this repo is the database as it ended after the Problem 9
run: all three tickets resolved and $152.00 in checking. Reset it (step 1 or
step 5) before running the tickets again.

## Setup

You need Python 3.11 or newer (built on 3.14), Node 20.19 or newer, and a
Portkey API key. Run these from the repo root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env    # then put your key in PORTKEY_API_KEY
```

The real `.env` is never committed. Only gpt-6-luna is used, for every agent.

## 1. Copy the original database to the working copy (a clean run)

The tools only ever change `data/campus_customs_new.db`. To start over from
the original data, stop the backend first, then copy the original over the
working copy and remove any SQLite side files:

```bash
cp data/campus_customs.db data/campus_customs_new.db
rm -f data/campus_customs_new.db-journal data/campus_customs_new.db-wal data/campus_customs_new.db-shm
```

Checking is back to $3,400.00, every ticket is open, and there are no
payments. While the backend is running, use step 5 instead.

## 2. Start the MCP server

You don't need a separate terminal for the agents. The backend starts the
server itself (`mcp_server/server.py` over stdio): one process for the board's
approvals and one for each ticket run.

- **By hand**, to see that it starts: `.venv/bin/python mcp_server/server.py`.
  It speaks MCP over stdio, so it waits for a client on standard input. Stop
  it with Ctrl+C.
- **From Claude Code**: `.mcp.json` registers it as `campus-customs`. Open
  Claude Code in this folder, approve the project server when asked, and run
  `/mcp` to see its tools. Claude Code gets the lookup and request tools, never
  the human-only `approve_request` and `reject_request`.

By default the server uses `data/campus_customs_new.db`. `CAMPUS_DB_PATH`
points it at another file. It refuses to open the original.

## 3. Start the FastAPI backend

```bash
cd backend
../.venv/bin/uvicorn main:app --reload --port 8000
```

(Or activate the environment with `source ../.venv/bin/activate` and run
`uvicorn main:app --reload --port 8000`.) Check it at
http://localhost:8000/api/health; the route docs are at http://localhost:8000/docs.
The routes are listed in `output/harness.md`, §4.

## 4. Start the React board

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The board talks to the backend at
http://localhost:8000; `frontend/.env.example` shows how to change that.

## 5. Reset the database before a full three-ticket run

With the backend running, reset in one of these ways:

- the board's **Reset shop data** button (top right), or
- `curl -X POST http://localhost:8000/api/reset`

Either one copies the original over the working copy and logs a `db_reset`
entry in `output/audit_trail.json`. Checking should read $3,400.00.

Then run the three tickets:

1. On the board, run #101, #102 and #103 in that order (each run takes one to
   two minutes). Each ends `waiting_approval`.
2. Type your name under **Waiting on you** and approve or reject each request.
   The requests ask for more cash than checking holds, so something has to
   wait. Agents never pay; only these clicks move money.
3. Run each ticket again so the Boss can close it. If a close run files a new
   request, decide it and run that ticket once more.

From the command line, without the board, this resets and runs all three
first runs: `.venv/bin/python backend/agents.py --reset 101 102 103`.

## Checking the cash

```bash
python3 tests/cash/ledger_check.py            # the ledger reconciles inside the database
python3 tests/cash/sources_check.py           # DB, API, audit trail and pages agree (backend running)
.venv/bin/python tests/cash/replay_check.py   # replays the decisions through the MCP server on a temp copy
```

These checks describe the recorded run. After a new run with different
decisions, the checks that expect those exact decisions will fail on purpose.

## Where the results are

| File | What it holds |
|---|---|
| `output/harness.md` | Tables, MCP tools, the five agents, API routes, the board and the safety rules |
| `output/mcp_smoke.json` | The three MCP tools tested from Claude Code |
| `output/desk_tickets.html` | Expected vs actual for each ticket, the Cash tab and the Reflection |
| `output/design.md` | The board's design and why |
| `output/resolved_tickets.json` | Each ticket's outcome, who did what, and every human decision |
| `output/resolved_board.html` | Screenshots of the board for each resolved ticket |
| `output/audit_trail.json` | Every agent step, tool call and human decision (append-only) |
| `output/cash_checks.json` | The three cash checks and their results |
| `output/github_url.txt` | This repo's URL |
| `AI_prompts.md` | The prompts used for each problem |
