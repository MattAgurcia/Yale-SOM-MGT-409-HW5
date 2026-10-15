# Design: the Campus Customs operations desk

The dashboard (`frontend/`, React + Vite + TypeScript) is a desk where a person
picks a ticket, watches the five agents work it, and approves what they prepare.
This note explains the look and the reasons for it.

## The idea: a desk you can feel

HW 4's storefront used **glassmorphism**: frosted panels floating over blue
light. For the operations desk I used **neumorphism**: everything looks pressed
out of one soft sheet of Yale Grey 100, lit from the top left. A Yale White
highlight sits on one side of each shape and a soft grey shadow on the other.

Neumorphism has one useful property: a shape is either **raised** or
**pressed in**. The desk uses that as its language for state:

- **Raised means active or open.** An open ticket, its "Open" chip, and an
  agent that is working all stand up. A working agent rises with a ripple in
  its colour.
- **Pressed means settled or waiting.** A resolved ticket and its "Resolved"
  chip sink into the board. An agent waiting on a teammate sinks into the
  table with a dashed ring.

So you can read the room before reading a word. This is also why it feels
different from glass: glass is about seeing through, and this is about touch.

## Palette and type

- **Surface:** everything is cut from Yale Grey 100 (`#E6E6E7`). Highlights
  are Yale White (`#FAFFFF`), and shadows are Grey 500 at low opacity.
- **Brand and actions:** Yale Blue (`#00356B`) carries the brand, the primary
  buttons, the cash figure and the Boss. Medium Blue and HW 4's lighter blue
  tints make the gradients and washes.
- **State colours:** Marigold, Lime and Tomato from the Yale School of
  Medicine palette mark state:
  - Marigold for "needs your approval"
  - Lime for "done", "resolved" and "ready to close"
  - Tomato for "trouble"

  Azure marks a run in progress.
- **Agents** each wear one palette colour as a ring:
  - Boss: Yale Blue
  - Inventory: Azure
  - Accounting: Marigold (gold, for money)
  - Facilities: Medium Blue
  - Customer Service: Tomato (a warm voice)
- **Shared colours, never colour alone.** The palette has only three blues
  that are not state colours, so three agents share a hue with a state. That
  is why colour is never the only signal:
  - **State** always comes as a chip with an icon and a word ("✓ Resolved",
    "✋ Needs your approval", "⚠ refused").
  - **Agents** always show their name and their own glyph.
  - **Text** never uses an agent or state colour. Values stay in dark ink, and a
    shortfall is dark text on a light Tomato wash.
- **Colour check.** I ran the five agent colours through a colour-blindness
  checker:
  - **Separation passed:** every pair stays distinguishable for colour-blind
    viewers (worst difference 15.9).
  - **Lightness flagged:** it flagged Yale Blue as very dark and Marigold as
    very light for a set of categories.
  - **Contrast flagged:** Azure, Marigold and Tomato fall below 3:1 against
    the grey.

  The always-visible names and glyphs are the answer to both flags.
- **Type** is carried over from HW 4: the Yale serif (EB Garamond stand-in) for
  headings, ticket numbers and the customer letters, and Mallory (Source Sans 3
  stand-in) for everything else. The cash balance is set in the sans, the way a
  figure on a dashboard should be.

## Layout: pick, watch, decide

Three columns, read left to right in the order of the work:

| Left: what's on the desk | Centre: the ticket's story | Right: what needs you |
|---|---|---|
| The three tickets, and the checking balance | The ticket, the Run button and the Boss's last call. Then the team table, then the conversation | Requests waiting on you, who did what, and the letters Dan drafted |

**Narrower screens**
- **Below 1280px:** the right column moves under the cash vault, so "Waiting
  on you" stays beside the ticket's story.
- **Below 860px** (phones and portrait tablets): everything stacks in one
  column, and a "skip to requests waiting on you" link appears for keyboard
  users.
- **Below 560px:** the team table shrinks so all five seats still fit.

## How the agents read differently

- **At the table.** The five seats sit in a pentagon, with the Boss at the
  head. Each has its own glyph:
  - Boss: a compass
  - Inventory: a stock box
  - Accounting: a stack of coins
  - Facilities: the storefront
  - Customer Service: **Dan**, the bulldog from the HW 4 storefront, now
    drafting the replies

  Faint dotted lines join every pair of seats, which shows full connectivity:
  anyone can ask anyone. In a pentagon no line runs under another seat, so all
  ten are visible. A handoff lights its line in the asker's colour, and the
  line flows while the asker waits. An agent the Boss never calls stays a
  quiet hollow, which makes the point of the expected-vs-actual comparison
  (not everyone on every ticket) visible at a glance.
- **In the conversation.** Each kind of step has its own shape:
  - **Handoffs** read as "Boss → Inventory" notes.
  - **Tool calls** read in plain English, with the agent's disc: "Inventory
    checked stock and price", then a one-line finding such as "CC-HOOD-NAVY M:
    8 on hand, short 12 · cost $22.00, list $58.00". The raw tool name sits
    beside it in a small pill, for anyone who wants it.
  - **Reports** are speech bubbles with a coloured top edge. The Boss's final
    decision sits on a light blue wash.
  - **Your decisions** come from a black "you" disc.
  - **A refused call** (e.g. a duplicate request) gets a dashed tomato edge and
    a "refused" tag, so mistakes are visible, not hidden.
- **Who did what.** A card per agent covers every run on the ticket since the
  last reset. It lists who asked the agent, what it did in plain words ("checked
  cash ×2", with a "⚠ 1 refused" label where a call was refused), what it filed,
  and its last words. It ends with "Not called on this ticket: …". Because it
  spans runs, the Boss's short final "close" run never hides the specialists'
  work.

## Resolved tickets

- **Running:** a ticket the team is working on breathes in Azure, and the Run
  button becomes a timer.
- **Waiting on you:** when the run ends, a toast says so, and the stage shows
  the Boss's call with the actions it left you. A ticket waiting on approvals
  shows a Marigold "needs your approval" chip with a count.
- **Ready to close:** once you have decided every request, the chip becomes a
  Lime-outlined **"Ready to close"** with a flag. The button changes to **"Ask
  the Boss to close #101"**, and a toast says so. Only the Boss marks a ticket
  resolved, after it re-checks the board, so the desk never claims something
  is done when it isn't.
- **Resolved:** the card sinks into the board with a lime check, the rail
  counts "1 of 3 resolved", and a tilted RESOLVED stamp lands on the ticket.
- **After a reset:** an earlier run's decision is hidden and a note explains
  why, so an Open ticket never shows an old "Resolved" call.

## Cash

- **The balance:** the checking balance is the desk's one hero number. When
  you approve a payment, the number rolls down and the amount ("−$840.00")
  drops out of the vault. Screen readers hear one clean "Checking balance
  $2,560.00", not every rolling digit.
- **The meter:** under it, the fill shows what is left of the starting cash,
  on a lighter step of the same blue. A hatched Marigold band marks the part
  that pending requests would take, with a small key.
- **The stats:** "Paid out", "Waiting on you" and "If all approved" sit side by
  side. If the requests add up to more than checking holds (as in this
  homework: $112 short), a tomato-edged note says so.
- **The ledger:** it lists every payment and who approved it.
- **Approving money:** every approval that moves cash asks once more in a real
  modal dialog that starts on **Cancel**. It names the new balance and your
  name ("Checking goes from $3,400.00 to $2,560.00. This is recorded under your
  name, …"). The Pay button locks while the payment goes through, so a double
  click never pays twice.
  - Each request shows "Checking after: $X".
  - A purchase order still blocked by an unpaid invoice shows "Pay invoice 501
    first". Its button reads "Waiting on invoice 501" and stays disabled until
    the invoice is approved. Its "Checking after" figure counts the invoice
    too.

## Small things that make it pleasant to use

- **Plain English everywhere it matters:** "Pay invoice 501 · Bulldog Print
  Co", not `invoice_payment ref 501`. Agents "check the lease" rather than
  calling `check_lease`.
- **Letters, not text boxes:** Dan's drafts are Yale White letters in the serif,
  with a "Draft · not sent" stamp and a copy button, because nothing is ever
  sent by an agent.
- **It remembers you:** the "Approving as" name is saved in the browser. If it
  is empty, pressing Approve takes you to the field and says why.
- **Keyboard:** `Alt`+`1`–`3` pick a ticket and `Alt`+`R` runs the team. Using a
  modifier means a stray key never starts a paid run.
- **It stays honest when things break:**
  - If the backend is down, a banner explains how to start it.
  - If the API answers but something behind it fails (the MCP server or the
    database), the status pill turns to "needs attention" and a banner says
    what is wrong. The board reconnects and retries on its own.
  - A reset asks first, and says the audit trail keeps everything.
- **Accessible:**
  - Focus rings are Yale Blue, and stay visible in high-contrast mode.
  - Fields have a visible edge.
  - Dialogs trap focus and return it.
  - Agent activity is announced once through a single live region.
  - All motion stops for `prefers-reduced-motion`.

## Running it

1. Copy `.env.example` to `.env` in the project root and add `PORTKEY_API_KEY`
   (the agent runs need it).
2. From the project root, activate the virtual environment
   (`source .venv/bin/activate`, after `pip install -r requirements.txt` once).
3. Start the API from `backend/`: `uvicorn main:app --reload --port 8000`.
4. From `frontend/`, run `npm install` once, then `npm run dev`.

The desk opens at `http://localhost:5173` and talks to `http://localhost:8000`
(`VITE_API_BASE` in `frontend/.env` changes that). The backend's CORS allows
the Vite origin.
