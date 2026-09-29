"""Scentline core types: Steps and Trails.

A Trail is a pheromone deposit left on the web graph by one agent session
so that later sessions can follow (route) or avoid (hazard) the same path.

Only the standard library is used anywhere in Scentline.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

KIND_ROUTE = "route"      # positive pheromone: this path worked
KIND_HAZARD = "hazard"    # negative pheromone: this path failed — avoid


@dataclass
class Step:
    """One action taken on a page.

    ``action``  – click | fill | select | press | scroll | goto | extract | wait
    ``target``  – stable selector or ref token (CSS / accessibility ref).
    ``value``   – payload for fill/select/press (NOT part of route identity).
    ``dom_sha`` – structural fingerprint of the page state *before* the action
                  (see scentline.fingerprint). Anchors the step to page
                  structure, so drift is detectable per-step.
    """

    action: str
    target: str
    value: Optional[str] = None
    dom_sha: Optional[str] = None

    def token(self) -> str:
        """Route-identity token: the *shape* of the action, not its payload."""
        target = " ".join(self.target.lower().split())
        return f"{self.action.lower()}:{target}"

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "target": self.target,
            "value": self.value,
            "dom_sha": self.dom_sha,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Step":
        return cls(
            action=d["action"],
            target=d["target"],
            value=d.get("value"),
            dom_sha=d.get("dom_sha"),
        )


@dataclass
class Trail:
    """A pheromone trail on the web graph.

    ``kind="route"``  – positive pheromone: a path that worked. Later agents
                        follow it.
    ``kind="hazard"`` – negative pheromone: a path that led to failure. Later
                        agents avoid it. Same evaporation physics as routes —
                        a hazard nobody re-confirms fades like any scent.
    """

    url: str                       # entry URL (canonicalized on deposit)
    dom_sha: str                   # fingerprint of the entry page state
    steps: list[Step] = field(default_factory=list)
    reward: float = 1.0            # Σ of walk contributions (undecayed)
    deposits: int = 1              # how many times this route was deposited
    born_at: float = 0.0           # first deposit (unix seconds)
    last_deposit_at: float = 0.0   # last reinforcement (unix seconds)
    walks: list = field(default_factory=list)  # [(tᵢ, rᵢ), ...] per-walk pheromone ledger
    ttl_seconds: Optional[float] = None  # hard expiry, else config default
    author: str = "anonymous"      # agent/session id that left it
    note: Optional[str] = None     # free-text "why this route" (first non-empty wins)
    kind: str = KIND_ROUTE         # route | hazard
    id: str = field(default_factory=lambda: "t" + uuid.uuid4().hex[:12])

    @property
    def tokens(self) -> list[str]:
        return [s.token() for s in self.steps]

    def identity(self) -> tuple:
        """Merging key: same page + same route shape + same kind = same trail.
        The URL is canonicalized here so identity is stable even before deposit."""
        from .fingerprint import canonical_url

        return (canonical_url(self.url), self.dom_sha, tuple(self.tokens), self.kind)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "dom_sha": self.dom_sha,
            "steps": [s.to_dict() for s in self.steps],
            "reward": self.reward,
            "deposits": self.deposits,
            "born_at": self.born_at,
            "last_deposit_at": self.last_deposit_at,
            "walks": [[float(t), float(r)] for t, r in self.walks],
            "ttl_seconds": self.ttl_seconds,
            "author": self.author,
            "note": self.note,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Trail":
        return cls(
            id=d["id"],
            url=d["url"],
            dom_sha=d["dom_sha"],
            steps=[Step.from_dict(s) for s in d.get("steps", [])],
            reward=float(d.get("reward", 1.0)),
            deposits=int(d.get("deposits", 1)),
            born_at=float(d.get("born_at", 0.0)),
            last_deposit_at=float(d.get("last_deposit_at", 0.0)),
            walks=[(float(t), float(r)) for t, r in d.get("walks", [])],
            ttl_seconds=d.get("ttl_seconds"),
            author=d.get("author", "anonymous"),
            note=d.get("note"),
            kind=d.get("kind", KIND_ROUTE),
        )


@dataclass
class TrailHit:
    """A live (non-evaporated) trail returned by sniff(), ranked for context."""

    trail: Trail
    intensity: float   # decayed reward at query time
    rank: int          # 3 = same URL + same DOM, 2 = same URL, 1 = same host
    similarity: float  # path overlap with the querying agent's steps so far

    @property
    def confidence(self) -> float:
        return max(self.intensity, 0.0) * self.similarity if self.rank == 1 else self.intensity


@dataclass
class SniffResult:
    url: str
    hits: list[TrailHit] = field(default_factory=list)        # live routes at this URL
    drift: Optional[dict] = None  # {"expected": [dom_sha...], "observed": dom_sha}
    hazards: list[TrailHit] = field(default_factory=list)     # live hazards at this URL
    host_hints: list[TrailHit] = field(default_factory=list)  # thin scent, same host

    def render(self, budget_tokens: int = 600) -> str:
        """Project trails into a compact text block for an agent's context window."""
        from .context import render_sniff  # local import to avoid cycle

        return render_sniff(self, budget_tokens)
