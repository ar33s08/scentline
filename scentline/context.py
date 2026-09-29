"""Projection: render live trails as a compact text block for agent context.

The substrate is machine data; the projection is what an LLM actually reads.
Rendering is deterministic, token-budget-aware, and never includes step
payload values (payloads may carry user data; routes are shape, not content).

Order in the projection: hazards first (safety information), then routes,
then host hints — each packed greedily under the token budget.
"""

from __future__ import annotations

import time

from .types import KIND_HAZARD, SniffResult

_CHARS_PER_TOKEN = 4


def _fmt_ago(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _chain(trail, max_steps: int = 8) -> str:
    chain = " -> ".join(s.token() for s in trail.steps[:max_steps])
    if len(trail.steps) > max_steps:
        chain += " -> ..."
    return chain


def render_sniff(result: SniffResult, budget_tokens: int = 600,
                 now: float | None = None) -> str:
    now = time.time() if now is None else float(now)
    char_budget = max(0, budget_tokens) * _CHARS_PER_TOKEN

    if not (result.hits or result.hazards or result.host_hints):
        return "no scent here — be the first to lay a trail"

    counts = f"{len(result.hits)} route(s)"
    if result.hazards:
        counts += f", {len(result.hazards)} hazard(s)"
    if result.host_hints:
        counts += f", {len(result.host_hints)} host hint(s)"
    lines: list[str] = [f"scent @ {result.url} — {counts}"]
    if result.drift:
        lines.append("  DRIFT WARNING: page structure changed since these trails "
                     "were laid — verify each target against the live page before replay")

    def block_for(hit) -> list[str]:
        t = hit.trail
        ago = _fmt_ago(now - t.last_deposit_at)
        if t.kind == KIND_HAZARD:
            label = "1 hit" if t.deposits == 1 else f"{t.deposits} hits"
            head = f"! AVOID [{hit.rank}] {_chain(t)}"
        else:
            label = "1 walk" if t.deposits == 1 else f"{t.deposits} walks"
            head = f"-> [{hit.rank}] {_chain(t)}"
        body = [head, f"   {label} | last {ago} | intensity {hit.intensity:.2f}"]
        if t.note:
            body.append(f"   # {t.note.splitlines()[0].strip()}")
        return body

    def hint_line(hit) -> str:
        t = hit.trail
        path = t.url.split("/", 3)
        where = "/" + path[3] if len(path) > 3 else "/"
        preview = " -> ".join(t.tokens[:3]) or "(empty route)"
        return (f"-> [hint] {preview} @ {where}"
                f" — confidence {hit.confidence:.2f} (same host)")

    budget_left = char_budget - len(lines[0]) - 1
    if result.drift:
        budget_left -= len(lines[1]) + 1

    for group in (result.hazards, result.hits):
        for hit in group:
            block = block_for(hit)
            cost = sum(len(l) + 1 for l in block)
            if cost > budget_left:
                continue  # skip, but keep trying smaller later blocks
            lines.extend(block)
            budget_left -= cost

    for hit in result.host_hints:
        line = hint_line(hit)
        if len(line) + 1 <= budget_left:
            lines.append(line)
            budget_left -= len(line) + 1

    return "\n".join(lines)
