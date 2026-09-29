"""Agent-facing API: mark() recorder, sniff(), and framework glue.

mark(url, html)            – wrap a working session; record steps; leave a
                             trail ONLY on explicit success (leave_trail()).
sniff(url, dom_sha, ...)   – read the shared scent at a URL, ranked for this
                             agent (exact → drift → host hints).
_resolve_step(page, step)  – follower-side helper: resolve a recorded target
                             against the live DOM. Targets are suggestions,
                             never a blind replay.
"""

from __future__ import annotations

from .fingerprint import fingerprint_dom
from .store import TrailStore, sniff as _sniff
from .types import Step, Trail

SCRUB_ACTIONS = {"fill", "press", "select"}  # payloads may carry user-typed data


class RouteRecorder:
    """Records the route an agent walks. Deposit happens only on success."""

    def __init__(self, url: str, dom_sha: str | None, store: TrailStore | None = None,
                 author: str = "anonymous", scrub: bool = True) -> None:
        self.url = url
        self.dom_sha = dom_sha or "unanchored"
        self.store = store
        self.author = author
        self.scrub = scrub
        self.steps: list[Step] = []
        self._deposited = False

    def step(self, action: str, target: str, value: str | None = None,
             dom_sha: str | None = None, persist_value: bool = False) -> "RouteRecorder":
        """Record one action. fill/press/select values are scrubbed by
        default (use persist_value=True only for public data like search
        queries — typed secrets never belong in trails; put environment-
        specific payloads in the deposit note instead)."""
        if self.scrub and action.lower() in SCRUB_ACTIONS and not persist_value:
            value = None
        self.steps.append(Step(action=action.lower(), target=target,
                               value=value, dom_sha=dom_sha))
        return self

    def leave_trail(self, note: str | None = None, ttl_seconds: float | None = None,
                    reward: float = 1.0) -> Trail:
        """Deposit the recorded route as pheromone. Call ONLY on success —
        failed sessions leave no scent (no negative pheromone in v0.1)."""
        if self._deposited:
            raise RuntimeError("leave_trail() called twice on one recorder")
        self._deposited = True
        trail = Trail(url=self.url, dom_sha=self.dom_sha, steps=list(self.steps),
                      reward=reward, author=self.author, note=note,
                      ttl_seconds=ttl_seconds)
        store = self.store or TrailStore()
        return store.deposit(trail)

    # context-manager support: an exception inside the block means no deposit
    def __enter__(self) -> "RouteRecorder":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False  # never suppress; no trail on failure/abandon


def mark(url: str, html: str | None = None, author: str = "anonymous",
         scrub: bool = True, store: TrailStore | None = None) -> RouteRecorder:
    """Start recording a route at ``url``. Pass the live page's HTML so the
    trail is DOM-anchored (required for drift detection by later followers)."""
    dom_sha = fingerprint_dom(html) if html else None
    return RouteRecorder(url, dom_sha, store=store, author=author, scrub=scrub)


def sniff(url: str, dom_sha: str | None = None, my_tokens: list[str] | None = None,
          k: int = 3, now: float | None = None, store: TrailStore | None = None):
    """Sniff the scent at ``url``; returns a SniffResult — call .render()
    on it to project it into an agent's context window."""
    return _sniff(url, dom_sha=dom_sha, my_tokens=my_tokens, k=k, now=now,
                  store=store or TrailStore())


def _resolve_step(page, step: Step):
    """Resolve a recorded target against the live DOM (Playwright page).

    Resolution chain: CSS selector -> accessible label -> button/link role.
    Returns a Playwright Locator or None. The follower re-perceives the page;
    recorded targets are suggestions, never a blind replay.
    """
    target = (step.target or "").strip()
    if not target:
        return None
    try:
        loc = page.locator(target)
        if loc.count() > 0:
            return loc.first
    except Exception:
        pass
    try:
        by_label = page.get_by_label(target)
        if by_label.count() > 0:
            return by_label.first
    except Exception:
        pass
    for role in ("button", "link"):
        try:
            by_role = page.get_by_role(role, name=target)
            if by_role.count() > 0:
                return by_role.first
        except Exception:
            pass
    return None
