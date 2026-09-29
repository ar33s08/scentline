# Scentline

**Stigmergic trail memory for web agents.** The live web becomes a shared
pheromone substrate: agents lay evaporating, DOM-anchored trails over the
routes they walk, and every later session — any framework, any process —
sniffs those trails instead of re-deriving the route from a cold page.

Ants never message each other. They leave traces in the environment, and the
colony converges. Scentline applies that to browser agents:

- **Trails** are routes (click/fill chains) anchored to the *structural
  fingerprint* of the page they were walked on.
- **Evaporation** is per-walk: every walk deposits its own scent
  contribution, each decaying from its own timestamp
  (`intensity(t) = Σ rᵢ · 2^(−(t−tᵢ)/3days)`). Routes in daily use stay hot;
  abandoned routes fade in days and hard-die at 30 days.
- **Merging is by route identity** — same entry URL + same DOM fingerprint +
  same route shape — so a hundred agents that each found the checkout funnel
  pile pheromone onto *one* collective trail.
- **Drift is surfaced, never hidden**: follower agents fingerprint their own
  live page. If the site redesigned since the trail was laid, they get a
  `DRIFT WARNING` instead of silently replaying stale selectors. Cosmetic
  redesigns (new ids/classes/themes, same labels) hash identically, so trails
  survive them.

Everything is deterministic — no LLM inside the memory mechanics. The only
stdlib dependency is Python itself. `pip install scentline` (zero deps).

## Quickstart

```python
import scentline

# --- Agent A: first session, cold page. It struggles, succeeds, deposits. ---
with scentline.mark(url, html=page.content(), author="agent-a") as rec:
    rec.step("fill",  "input[type=search]", "wireless headphones", persist_value=True)
    rec.step("click", "button[type=submit]")
    rec.step("click", "a", )  # ...
    trail = rec.leave_trail(note="catalog search works; homepage search is broken")

# --- Agent B / next session / different framework: sniff before acting. ---
scent = scentline.sniff(url, dom_sha=scentline.fingerprint_dom(page.content()))
print(scent.render())          # drop this straight into the agent's context
# scent @ shop.example.com — 1 live trail(s)
# -> [3] fill:input[type=search] -> click:button[type=submit] -> click:a
#    1 walk | last walked 2h ago | intensity 0.97
#    # catalog search works; homepage search is broken
```

Failed sessions leave **no scent** — deposit happens only on an explicit
`leave_trail()` inside a clean `with` block.

### CLI

```bash
scentline sniff "https://shop.example.com/sale" --dom-sha <fingerprint>
scentline deposit trail.json        # agent frameworks emit trail JSON
scentline gc                        # evaporate dead trails
scentline stat                      # trails / walks / scent mass
SCENTLINE_FILE=./shop.trails.jsonl scentline stat   # per-project colony
```

### Framework glue

- **Any Playwright page**: `mark(url, html=page.content())`,
  `recorder.step(...)`, `recorder.leave_trail(note=...)`,
  `scentline.sniff(url, dom_sha=scentline.fingerprint_dom(page.content()))`.
- **Followers**: resolve recorded targets against the live DOM with
  `scentline.hooks._resolve_step(page, step)` — CSS → label → role chain.
  Targets are *suggestions*, never a blind replay.
- **browser-use / others**: map the framework's history entries to
  `recorder.step()` calls (5 lines of glue; see `examples/`).

## Trails-as-code

The substrate is one JSONL file (`~/.scentline/trails.jsonl` by default, or
`SCENTLINE_FILE`, or `--file ./trails.jsonl`). It is append-event-logged
(`<file>.events.log`) and compacted under a cross-process lock — safe for
dozens of concurrent agent processes. Commit a project-scoped file and the
team's routes travel with the repo through git.

## Why this isn't agent-workflow-memory

AWM/WebCoach-style systems summarize trajectories with an LLM and retrieve
them by embedding similarity. Scentline's mechanics are pure code:

| | AWM / WebCoach | Scentline |
|---|---|---|
| Route reuse | LLM summaries + embedding match | exact route identity (URL+DOM+shape) |
| Evaporation | none — memory only grows | per-walk decay stack, TTL hard kill |
| Stale-UI safety | none | DOM fingerprint drift warnings |
| Identity stability | breaks on class/id churn | hash on structure+labels, not styling |
| Concurrency | research scripts | fcntl-locked file, N processes |
| Dependencies | heavy | **zero** |

The two stacks compose: use an LLM to *choose* among sniffed trails if you
like — the substrate stays deterministic, auditable, and cheap.

## Honest limits (v0.1)

- Fingerprints read raw HTML; content rendered exclusively inside shadow DOM
  is invisible to the outline (the follower still verifies its own live state,
  so the failure mode is a drift warning, not a wrong click).
- Sites that serve different *structure* per user (hard A/B splits) surface as
  drift — honest, but noisy on such sites.
- Locking is POSIX (`fcntl`); Windows falls back to best-effort no-lock.
- Fingerprint matching is exact; near-identical pages (same shape, different
  label wording) count as drift until fuzzy anchoring lands.

## Roadmap

Negative pheromones (failed routes deposit aversive scent) · SQLite substrate
· an MCP server so any MCP client shares one colony · embedding-based fuzzy
DOM anchoring · cross-machine sync layers.

## License

MIT
