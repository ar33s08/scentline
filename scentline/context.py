"""Projection: render live trails as a compact text block for agent context.

The substrate is machine data; the projection is what an LLM actually reads.
Rendering is deterministic, token-budget-aware, and never includes step
payload values (payloads may carry user data; routes are shape, not content).
"""

from __future__ import annotations

import time

from .types import SniffResult

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


def render_sniff(result: SniffResult, budget_tokens: int = 600,
                 now: float | None = None) -> str:
    now = time.time() if now is None else float(now)
    char_budget = max(0, budget_tokens) * _CHARS_PER_TOKEN

    if not result.hits:
        return "no scent here — be the first to lay a trail"

    lines: list[str] = [f"scent @ {result.url} — {len(result.hits)} live trail(s)"]
    if result.drift:
        lines.append("  DRIFT WARNING: page structure changed since these trails "
                     "were laid — verify each target against the live page before replay")

    def block_for(hit) -> list[str]:
        t = hit.trail
        chain = " -> ".join(s.token() for s in t.steps[:8])
        if len(t.steps) > 8:
            chain += " -> ..."
        walks = "1 walk" if t.deposits == 1 else f"{t.deposits} walks"
        ago = _fmt_ago(now - t.last_deposit_at)
        body = [f"-> [{hit.rank}] {chain}",
                f"   {walks} | last walked {ago} | intensity {hit.intensity:.2f}"]
        if t.note:
            body.append(f"   # {t.note.splitlines()[0].strip()}")
        return body

    budget_left = char_budget - len(lines[0]) - 1
    if result.drift:
        budget_left -= len(lines[1]) + 1
    for hit in result.hits:
        block = block_for(hit)
        cost = sum(len(l) + 1 for l in block)
        if cost > budget_left:
            break
        lines.extend(block)
        budget_left -= cost
    return "\n".join(lines)
