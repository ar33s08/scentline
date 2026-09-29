# Launch kit — Scentline v0.2.0
# Reusable assets for posting about the project. Edit freely before posting.

## One-liners (pick per platform)

- "Your browser agent re-derives the same checkout path every single run.
  Scentline makes the web itself remember: evaporating, DOM-anchored trails
  any agent can sniff. Zero dependencies. github.com/ar33s08/scentline"
- "Ants never message each other — they leave trails. Scentline gives
  browser agents the same trick: successful routes become pheromone trails
  ON the live web, failures become AVOID warnings, and both evaporate."
- "Agent memory that maintains itself: per-walk evaporation kills stale
  routes, DOM fingerprints flag redesigns before they cost you a run, and
  the 100th agent to hit a site gets 100 walks of social proof."

## What makes it different (the 4 bullet reply when someone says
## "isn't this just X?")

1. Substrate: the live web graph (URL + DOM fingerprint = the scent key) —
   not a sidecar DB, not summaries in a vector store.
2. Physics: per-walk decay stack Σ rᵢ·2^(−Δt/3d) — memory bounded by
   usefulness, not a cleanup cron. Daily routes stay hot; dead ones fade.
3. Drift: followers fingerprint their OWN live page — redesigns surface as
   warnings, cosmetic redeploys hash identically and change nothing.
4. Neutrality: one JSONL file + raw-stdlib MCP server — a Claude agent and a
   Playwright bot share one colony with zero shared code.

## Demo transcript (real output, examples/checkout_demo.py)

no scent here — be the first to lay a trail
agent-a deposited route t7ca17815cd4f + 1 hazard
scent @ https://shop.example.com/sale — 1 route(s), 1 hazard(s)
! AVOID [3] fill:input[type=search] -> click:button -> click:a[href='/sponsored-landing']
   1 hit | last 0s ago | intensity 1.00
   # sponsored landing is a dead end — go straight to /checkout
-> [3] click:a[href='/checkout']
   1 walk | last 0s ago | intensity 1.00
   # use product search, then /checkout link

## Proof block (paste as the "receipts" reply)

- 39 tests green (Python 3.10–3.13, CI on push)
- zero-dependency gate: core imports with every non-stdlib import blocked
- 24 concurrent processes, zero lost deposits (fcntl-locked JSONL)
- MCP server: raw JSON-RPC, 6 tools, survives malformed input

## The OpenClaw playbook (why this can travel)

1. A primitive everyone needs but nobody named. (MCP = tool calling;
   Scentline = route memory for web agents.)
2. Zero-dependency core — installs in seconds, embeds anywhere.
3. A demo that explains itself in one screenshot. (the AVOID + route
   projection IS the pitch)
4. Protocol posture, not app posture — others can build on it.
5. Ship the receipts: tests, CI badge, honest limits section.

## Suggested X thread

1/ Browser agents are stateless amnesiacs. Every session re-explores the
   same sites from zero — same dead ends, same cookie walls, same
   12-click checkout funnels. I built the fix: github.com/ar33s08/scentline

2/ Scentline = stigmergic trail memory for the web. An agent that finds a
   working route deposits a pheromone trail anchored to the page's DOM
   structure. Every later agent — any framework — sniffs it and skips the
   exploration entirely.

3/ The physics is the point: every walk evaporates on its own clock
   (3-day half-life). Routes in daily use stay hot. Abandoned ones fade
   walk-by-walk. Memory stays small because it's *useful*, not because a
   cron job cleaned it.

4/ Failures are memory too. Deposit a hazard and every later agent sees
   "! AVOID" before touching that path — hazards evaporate the same way,
   so a fixed bug stops scaring agents once nobody re-hits it.

5/ It survives the web changing under it. Trails hash the page's
   STRUCTURE + labels, not styling — a site can redeploy nightly CSS and
   its trails still match. A real redesign surfaces as a DRIFT WARNING,
   never a silent wrong click.

6/ Zero dependencies. One JSONL file (commit it = trails-as-code). Ships
   with an MCP server written in raw stdlib JSON-RPC so Claude/Cursor/any
   MCP client shares the same colony as your Playwright bots. 39 tests,
   24-process concurrency stress, CI on 3.10→3.13.

7/ Cold start is the honest hard part — trails pay off with density
   (fleets, teams, repeated jobs). That's why the substrate is a protocol
   and not an app. Lay the first trail: github.com/ar33s08/scentline
