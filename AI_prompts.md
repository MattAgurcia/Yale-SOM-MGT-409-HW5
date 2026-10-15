# AI Prompts Log — HW 5

This file logs the prompts typed while completing this assignment, organized by problem.

## Problem 1: Vibe coder prompts

**Prompts:**

1. Starting a project for my AI class. Can you start a AI_prompts.md tracker like this one for a previous assignment, '/Users/matthewagurcia/Documents/MBA/Fa26/MGT-409_AI/hw 4/hw4/AI_prompts.md'

**Notes:**

---

## Problem 2: Study the database and start the harness

**Prompts:**

1. We will be working on a project with 11 total questions, please don't go forward too much other than what I ask you to do in each query. We will get there.

   CONTEXT: We will be pretending we are a college merch store operator "Campus Customs", and the assignment is to build an agentic team that runs the shop as part of their "Multi-Agent Operations" team. This involves: opening tickets that land on a board (customer orders, rent, unpaid bills, discount requests - whatever the shop has to handle). You will built three pieces that talk to each other; an MCP server, a FastAPI backend with a multi-agent team, and a React dashboard so a human can watch the agents at work and approve results.

   The agent team has full connectivity - any agent may delegate tasks to any other agent for help. In this assignment, you will build these agents:

   * Boss (reads each ticket, decides who should work on it, and makes final calls)
   * Inventory (checks stock by SKU and size, spots shortfalls, and figures out which vendor can restock)
   * Accounting (watches cash and invoices, checks margins, and prepares payments or purchase orders for human approval)
   * Facilities (handles the shop space side (leases, rent, etc.))
   * Customer service (drafts messages for customers; do not send!)

   RULES:

   * The field desk.date_today is "today" for the shop. Use this date to determine what is overdue
   * Vendor lead times com from the "vendors" table
   * A vendor will not ship new product while they still have an open unpaid invoice
   * Human approval is required for any payments. If payment is made, make sure to update the relevant table.
   * If there is not enough cash, the pay tool must refuse (no negative balances)
   * Cash only goes out in this homework. We did not model revenue, so no money comes in
   * Before a full run to resolve the tickets, make sure to reset the database to the original values
   * Do NOT email customers or call real vendors. Drafts stay on the board
   * Use the PORTKEY_API_KEY for AI calls. For this assignment, use only gpt-6-luna through Portkey for every agent. Multi-agent chats burn tokens fast.

   Problem 2:
   Data has been provided in the folder in a folder called /data, mainly campus_customs.db. Your tools will update the database as tickets get resolved. Open @data/campus_customs.db and look through every table and its fields. Make a copy of the database file @data/campus_customs.db and call it campus_customs_new.db and point your MCP server and backend at that working copy. Keep @data/campus_customs.db untouched so you can reset when you want to restart solving tickets.

   Study the three open tickets so you can see how they link to other tables.

   Start output/harness.md. For each table, list the fields and one short line on why that table matters for the agents. You will keep growing this harness file in later problems.

**Notes:**

---

## Problem 3: Build the MCP server

**Prompts:**

1. Sweet, yes, Problem 3 build the MCP server. Write an MCP server in mcp_server/ using FastMCP. It will talk to data/campus_customs_new.db. You do not need to connect or run it in this problem, but feel free to test it. Every agent in this homework uses the tools in this MCP server. You will add more tools to it later; for now write three tools you know you will need for the tickets in the database. Keep the names clear. Never invent any data, only use information in the database.

   In output/harness.md, list each of your three MCP tools. For every tool include: which table it reads, which ticket it helps unlock (101, 102, or 103), and one sentence on why that tool is the right one for that tickets. Vague lines like "reads inventory" are not useful; tie the tool to the ticket.

   Also, add a short mcp_server/README.md file that explains what the MCP server is for, which database file it uses, and the three tools it has.

**Notes:**

---

## Problem 4: Connect the MCP server and smoke-test the tools

**Prompts:**

1. sweet, thank you. moving onto problem 4.

   Add the MCP server to this project so that the vibe coder can calls the tools. Save the connection JSON text in .mcp.json at the project root.

   Now test each of the three MCP tools. Save the evidence in output/mcp_smoke.json. For every tool, include:

   * the prompt you asked
   * the tool name
   * the tool output (must match values in @data/campus_customs_new.db )

**Notes:**

The smoke test needed Claude Code itself to call the tools, but my Claude Code CLI login had expired, so I signed in again in the terminal (`~/.local/bin/claude auth login`) before the three test prompts in output/mcp_smoke.json were run.

---

## Problem 5: Build the agent team

**Prompts:**

1. thanks, moving onto problem 5. now let's build the agentic team using PydanticAI: Boss, Inventory, Accounting, Facilities, and Customer Service. Include prompts, models, and agent loops so they can delegate work to each other with full connectivity.

   Put the agent prompts in backend/prompts/ - one file per agent. Put data types in backend/models.py, and the agent files under backend/. Use the PORTKEY_API_KEY and *only* gpt-6-luna for every agent.

   Please write each prompt with the shop rules that agent needs. Please write very detailed prompts that cover *ALL* aspects of an agent's work and scope; be exhaustive.

   Add any tools that the agents need to your MCP server so they can work on the open tickets. Shop facts come from the MCP server over @data/campus_customs_new.db - DO NOT INVENT A SECOND SHOP/TOOLS LAYER THAT BYPASSES MCP. Wire the agents so they append to output/audit_trail.json as they run; for each agent-loop step, record enough to audit later. Append to this file; do not wipe it on each run.

   In output/harness.md, list each agent and each MCP tool (including ones you add in this problem) along with which table the tool uses. Also add a short safety section: the guardrails a real business would want when agents touch real customers and real money, plus limits that keep token use in check.

   Update mcp_server/README.md so the tool list matches what you have now.

2. can you expand on this?

   Responses API: Portkey’s gpt-6-luna rejects tool calls plus reasoning on the chat endpoint, so the team uses OpenAI’s Responses API with reasoning effort “low”.

**Notes:**

---

## Problem 6: Expected plan for each ticket (desk_tickets.html)

**Prompts:**

1. thanks, got it. moving to q6 - please write down what we expect the team to do on each open ticket. Build output/desk_tickets.html with one tab per ticket (e.g. 101, 102, & 103). Also add empty Cash and Reflection tabs for later problems (leave them blank or with a short "coming soon" note for now.)

   On each ticket tab, fill an Expected section only (leave room for an Actual section you will fill after we run the agents).

   For each ticket's Expected section, write:

   * Who the Boss should call first (and why?)
   * All the agent delegations you expect (not just "Boss calls everyone")
   * Which MCP tools you expect that run to use

   We do not want plans that assign every specialist to every ticket. We will then compare this plan to what actually happens when the agents resolve the three tickets.

**Notes:**

---

## Problem 7: Backend routes (FastAPI)

**Prompts:**

1. thank you - moving onto q7. Now we will build the backend routes

   We'll be building a React frontend dashboard in q8, but for that we'll need a backend it can call on. In backend/main.py, use FastAPI and add routes that do the following:

   * Return the three tickets and whether each is open or resolved
   * Take a ticket id and run your agent team on that ticket
   * Return recent agent events - what each agent said and which tools they used - so the board can refresh
   * Approve a payment or purchase after a human clicks approve (agents only prepare the pay; this route is what actually changes cash)
   * Return the current checking balance from cash_accounts
   * Reset the database to the original values when you want to try a fresh run

   The server should be able to start with the following command run on the backend/ folder:=
   uvicorn main:app --reload --port 8000

   In output/harness.md, list each route in one line (what URL / what it does)

**Notes:**

---

## Problem 8: The agent dashboard (React + Vite + TypeScript)

**Prompts:**

1. thanks, moving onto 18 - building the agent dashboard.

   Please build the frontend dashboard in frontend/ with React + Vite + TypeScript. The page should call the routs you built in Problem 7.

   At minimum, the board should:

   * List all three tickets
   * Let you pick one ticket and start the agent team on it
   * Show each agent and what they are saying / doing while the ticket runs
   * Mark a ticket resolved when the run finished
   * Show a short summary of what each agent did on that ticket
   * Let a human approve a pay or purchase when asked
   * Show the checking balance (it should drop after an approved pay)

   Make the dashboard in a neumorphism design using the color schemes used in the project '/Users/matthewagurcia/Documents/MBA/Fa26/MGT-409_AI/hw 4' and use this color palette:

   | Name | HEX | RGB | CMYK |
   |---|---|---|---|
   | Yale Blue | #00356B | 0 / 53 / 107 | 100 / 75 / 8 / 40 |
   | Medium Blue (YaleMedicine Blue) | #286DC0 | 40 / 109 / 192 | 90 / 49 / 0 / 0 |
   | Azure (YNHHS Blue) | #00A9E0 | 0 / 169 / 224 | 100 / 25 / 0 / 12 |
   | Marigold | #F9C73F | 249 / 199 / 63 | 0 / 20 / 75 / 2 |
   | Lime | #C1D655 | 193 / 214 / 85 | 10 / 0 / 60 / 16 |
   | Tomato | #ED5E6C | 237 / 94 / 108 | 0 / 60 / 54 / 7 |
   | Yale Black | #001A1C | 0 / 26 / 28 | 0 / 0 / 0 / 100 |
   | Yale White | #FAFFFF | 250 / 255 / 255 | 0 / 0 / 0 / 0 |
   | Grey 700 | #4D4E51 | 77 / 78 / 81 | 5 / 4 / 0 / 68 |
   | Grey 500 | #696B71 | 105 / 107 / 113 | 7 / 5 / 0 / 56 |
   | Grey 300 | #ADAEB3 | 173 / 174 / 179 | 3 / 3 / 0 / 30 |
   | Grey 100 | #E6E6E7 | 230 / 230 / 231 | 0 / 0 / 0 / 9 |

   Tell the frontend to talk to the backend at localhost:8000. On the backend, allow the Vite page original (usually localhost:5173) so the browser is allowed to call those routes.

   The board should be able to start with npm run dev. This opens the React desk in your browser so that you can pick tickets and watch agents.

   Write output/design.md with what you chose for the dashboard look (layout, how agents read differently, how resolved tickets and cash show up) and why - including the creative choices that make it feel special and something humans would actually enjoy using.

   For reference, I used Yale blue color palette and other colors recommended by the yale school of medicine. I chose the neumorphism design because I like it but I wanted something slightly different than the glassmorphism.

**Notes:**

The palette was pasted as a table from the Yale identity guide; it is reproduced here as a table.

After the dashboard was built I started the backend myself (`cd backend && source ../.venv/bin/activate && uvicorn main:app --reload --port 8000`) and ran ticket 101 from the board: I approved the $840 invoice and the $8 tee order, then asked the Boss to close it. The Boss kept #101 "In progress" because the tee had not arrived yet. I chose to keep that behaviour (option 1); that reply is logged as the first prompt under Problem 9.

---

## Problem 9: Full run over the three tickets

**Prompts:**

1. go with option 1 and quiet the polling logs. then for problem 9 -

   Now we're going to test the agents on a full run over the three tickets. Please reset the working database @data/campus_customs_new.db again so you start clean. Note the starting checking balance. Then run all three tickets on the board (101-103) until each is resolved.

   Open @output/desk_tickets.html from p6 - on each ticket tab, fill the actual section from this run: which agents worked, what they delegated, and which tools they used. Keep your expected section so you can compare the two.

   On the cash tab of the same @output/desk_tickets.html, itemize the money:

   * Starting checking balance (after the reset)
   * For each ticket: how cash changed when that ticket resolved, and why (which pay / purchase, dollar amount)
   * Ending checking balance - it must match cash_accounts in the working database

   Please triple test this cash functionality; wrong cash math is considered a complete, and total failure of this entire project.

   Also save:

   * output/resolved_tickets.json - for each ticket: id, final status, short outcome, what each agent contributed, and any human approvals
   * output/resolved_board.html - a page you can double-click with a screenshot of your React board for each resolved ticket (101-103)

   Append real runs to output/audit_trail.json. Finish output/harness.md so it covers tables, MCP tools, the five agents, API routes, the dashboard, and the safety rules.

2. what went wrong?

3. go ahead, retry the preview server

**Notes:**

When asked, I chose to have Claude Code click the five approval decisions on the board under my name, with rent and bills paid first. It approved the rent, invoice 501, the tee order and the hoodie price, and rejected the $264 hoodie restock. I also kept option 1, so tickets 101 and 103 end "In progress" rather than resolved. During the run, ticket 102's first close run hit the 3,000-token output cap, so the cap was raised to 8,000 and the close was run again. Prompts 2 and 3 came after the browser preview step was interrupted while checking `desk_tickets.html`. I later reset and reran this whole problem so I could click every decision myself and so all three tickets would end resolved; see the Pre-submission check section.

---

## Problem 10: Reflection

**Prompts:**

1. thanks! Moving onto p10 - open @output/desk_tickets.html and fill in the reflection tab. Answer using my own voice with writing samples that you can find in this folder: /Users/matthewagurcia/Documents/mba-application-context

   Please be detailed and thorough:

   * How would you evaluate the performance of the agents on each ticket and why?
   * For each ticket, how did Actual compare to the Expected plan you wrote earlier?
   * What would have been simpler as one agent with tools - and why?
   * Describe three new problems Campus Customs might face that this agent team could solve with the tools you built. Here's three guesses that I have, but feel free to override me:
     * Being able to centralize expense approvals. Typically raising tickets that need money to be resolved results in long bureaucratic waits; now this can be automatically approved.
     * Being able to provide more detailed customer service resolutions with information from the accounting and facilities depts. These are typically segmented
     * Centralizing both internal and external tickets; no longer has to potentially be two separate systems.
   * Describe three new problems Campus Customs might face that this agent team could not solve with the tools you built, and explain the tools and agents you would need to solve them. Here's three guesses that I have, but feel free to override me:
     * if something doesn't have an answer, like t-shirts being out of stock, this just adds layers that may frustrate the client
     * Any customer service query that cannot be solved by a chatbot; again, just adding layers
     * Tracking resolution KPIs. The app helps triage situations, but I wouldn't expect massive improvements in ticket resolution if a lot of them ultimately need human approval.
     * What if the wrong thing gets prioritized and we run out of cash because the AI didn't properly triage the ranking of importance.

   Tie every answer to this app and the three tickets you ran; use the ticket tabs and Cash tab on the same page as your evidence. Please make sure to be specific about Campus Customs details. Do not make generic or broad statements without tying it back to Campus Customs' business strategy.

2. a) 5700 words is egregious
   b) why did you use analogies from my prior experience? I specifically said to only reference them to copy my writing voice

**Notes:**

The Reflection tab is written in my voice, using my writing samples for voice only, and it follows my own writing rules (no colons, no em dashes, no "it's not this, it's that" lines). The first draft ran about 5,700 words and borrowed stories from my past work, so I had it cut down and every reference to my prior experience removed. I kept my guesses where the run supported them and corrected the first one. Agents can't approve expenses in this app, because a human approves every payment. Two of my "can't solve" guesses were merged because the run showed they are the same problem.

---

## Pre-submission check (between Problems 10 and 11)

**Prompts:**

1. Can you grade this assignment based on what is in @instructions please

2. Do you think it would help the grading if we changed the "In Progress" statuses of 101 and 103 to something that's more concrete that doesn't make it seem like they're actually in progress? Is that allowed per the instructions?

   They currently say in progress because of problems that the AI can't fix; i.e. shirts size S are out of stock

3. Let's do a full reset and rerun instead, so I click the approvals myself and 101 and 103 end up resolved.

4. I've decided all five requests on the board. Run the close runs and rebuild the pages.

5. I've decided request 6 on the board. Run 103's last close and rebuild the pages.

**Notes:**

The grade check showed two problems with my Problem 9 run: tickets 101 and 103 ended in progress, and Claude Code had clicked my approvals. Relabeling the statuses would not have fixed either, so I changed the Boss's closing rule (resolved once the shop's part is done) and reran Problem 9 from a reset, clicking every decision on the board myself. Prompt 5 was needed because ticket 103's first close run filed a new $49 price for the 8 hoodies in stock (request 6), which I had to approve before the last close.

---

## Problem 11: Submit to GitHub

**Prompts:**

1. (Pasted a screenshot of the expected file layout from the assignment.) thanks. now we need to submit the assignment. can you please make a copy of all the files into a folder called "hw5" that's inside this directory and make sure all the files that are mentioned in the file layout are in there? then push that folder into a public Github repo so the graders can clone it? Put the URL in output/github_url.txt as well.

   Do not push the real .env to the Github repo. Please include both database files under data/ (the original and the working copy) so graders can run the app easily.

   Please also make a README.txt that explains how to copy the original DB to the working copy when you need a clean run, how to start the MCP server, the FastAPI backend, the React board, and how to reset the DB before a full three-ticket run. thanks!

**Notes:**

---
