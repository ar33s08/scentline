"""Trail store: the substrate. A single JSONL file. Zero dependencies.

Concurrency protocol: every mutating operation runs under a stable sidecar
lock file (``<path>.lock`` — created once, never replaced, so every process
serializes on the same inode): re-read the full state, apply the mutation,
rewrite the compacted state in place (seek(0) + write + truncate — no inode
swap, no replace race), then append the event to ``<path>.events.log`` for
audit/replay. One trails file is therefore safely shareable by dozens of
agent processes on a machine — and because it is plain JSONL, teams can
commit it into a repo ("trails-as-code") and share routes through git.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from .decay import INTENSITY_FLOOR, effective_reward, is_live
from .fingerprint import canonical_url
from .types import SniffResult, Trail, TrailHit

DEFAULT_HOME = Path("~/.scentline").expanduser() / "trails.jsonl"
ENV_FILE = "SCENTLINE_FILE"
WALKS_CAP = 64  # per-trail walk-record cap; truncation under-counts intensity (conservative)


def default_path() -> Path:
    env = os.environ.get(ENV_FILE)
    if env:
        return Path(env).expanduser()
    return DEFAULT_HOME


class TrailStore:
    def __init__(self, path=None) -> None:
        self.path = Path(path).expanduser() if path is not None else default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()
        self._warned = False

    # ------------------------------------------------------------------ lock
    @contextmanager
    def _locked(self):
        lock_path = self.path.with_name(self.path.name + ".lock")
        with open(lock_path, "a+") as lock_fh:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)

    # ------------------------------------------------------------ file plumbing
    def _read(self) -> dict:
        trails: dict = {}
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return trails
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                t = Trail.from_dict(json.loads(line))
                trails[t.id] = t
            except Exception:
                if not self._warned:
                    print(f"[scentline] skipping corrupt trail record in {self.path}",
                          flush=True)
                    self._warned = True
        return trails

    def _write(self, trails: dict) -> None:
        with open(self.path, "r+", encoding="utf-8") as fh:
            fh.seek(0)
            fh.write("".join(json.dumps(t.to_dict(), separators=(",", ":")) + "\n"
                             for t in trails.values()))
            fh.truncate()
            fh.flush()

    def _log_event(self, kind: str, payload: dict) -> None:
        events = self.path.with_name(self.path.name + ".events.log")
        event = {"at": round(time.time(), 3), "kind": kind, **payload}
        with open(events, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, separators=(",", ":")) + "\n")

    # ------------------------------------------------------------------ ops
    def deposit(self, trail: Trail, now: float | None = None) -> Trail:
        """Deposit (or reinforce) a trail. Merging is by route identity:
        same entry URL + same DOM fingerprint + same route shape → the
        existing trail's pheromone stack gains this walk's contribution."""
        now = time.time() if now is None else float(now)
        trail.url = canonical_url(trail.url)
        if not trail.walks:
            trail.walks = [(trail.born_at or now, float(trail.reward))]

        with self._locked():
            trails = self._read()
            existing = None
            for t in trails.values():
                if t.identity() == trail.identity():
                    existing = t
                    break
            if existing is not None:
                existing.walks = (existing.walks + list(trail.walks))[-WALKS_CAP:]
                existing.reward = sum(float(r) for _, r in existing.walks)
                existing.deposits += 1
                existing.last_deposit_at = max(existing.last_deposit_at,
                                               trail.walks[-1][0] if trail.walks else now)
                if trail.ttl_seconds is not None:
                    existing.ttl_seconds = trail.ttl_seconds
                if existing.note is None and trail.note:
                    existing.note = trail.note
                stored = existing
            else:
                trail.born_at = trail.walks[0][0] if trail.walks else now
                trail.last_deposit_at = trail.walks[-1][0] if trail.walks else now
                trails[trail.id] = trail
                stored = trail
            self._write(trails)
        self._log_event("deposit", {"id": stored.id, "url": stored.url,
                                    "steps": len(stored.steps)})
        return stored

    def reinforce(self, trail_id: str, delta: float, now: float | None = None) -> Trail | None:
        """Add (or subtract) pheromone from a trail. Positive delta = another
        walk of the same route; negative = explicit evaporation force."""
        now = time.time() if now is None else float(now)
        with self._locked():
            trails = self._read()
            t = trails.get(trail_id)
            if t is None:
                return None
            t.walks = (t.walks + [(now, float(delta))])[-WALKS_CAP:]
            t.reward = sum(float(r) for _, r in t.walks)
            if delta > 0:
                t.last_deposit_at = now
            self._write(trails)
        self._log_event("reinforce", {"id": trail_id, "delta": delta})
        return t

    def live_for_url(self, url: str, now: float | None = None,
                     floor: float = INTENSITY_FLOOR) -> list[Trail]:
        now = time.time() if now is None else float(now)
        key = canonical_url(url)
        with self._locked():
            trails = self._read()
        return [t for t in trails.values()
                if t.url == key and is_live(t, now, floor)]

    def evict_dead(self, now: float | None = None,
                   floor: float = INTENSITY_FLOOR) -> int:
        """GC: drop trails below the intensity floor / past TTL. Returns count."""
        now = time.time() if now is None else float(now)
        with self._locked():
            trails = self._read()
            dead = [t.id for t in trails.values() if not is_live(t, now, floor)]
            for tid in dead:
                del trails[tid]
            if dead:
                self._write(trails)
        if dead:
            self._log_event("evict", {"count": len(dead)})
        return len(dead)

    def stat(self, now: float | None = None) -> dict:
        now = time.time() if now is None else float(now)
        with self._locked():
            trails = self._read()
        mass = sum(effective_reward(t, now) for t in trails.values())
        return {
            "trails": len(trails),
            "walks": sum(t.deposits for t in trails.values()),
            "scent_mass": round(mass, 4),
        }


# --------------------------------------------------------------------------
# Sniffing: read the shared scent at a URL and rank it for *this* agent.
# --------------------------------------------------------------------------

def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 1.0  # a cold agent gets full-confidence hints
    union = sa | sb
    return len(sa & sb) / len(union) if union else 1.0


def sniff(url: str, dom_sha: str | None = None, my_tokens: list[str] | None = None,
          k: int = 3, now: float | None = None, store: TrailStore | None = None
          ) -> SniffResult:
    """Sniff the scent at ``url``.

    Ranks trails for the querying agent:
      rank 3 – same URL *and* same DOM fingerprint: follow it.
      rank 2 – same URL, DOM differs: DRIFT WARNING, verify before replay.
      rank 1 – same host only: thin scent, loose hint.
    """
    store = store or TrailStore()
    now = time.time() if now is None else float(now)
    my_tokens = my_tokens or []
    key = canonical_url(url)
    hits: list[TrailHit] = []
    for t in store.live_for_url(key, now):
        anchored = dom_sha and t.dom_sha and t.dom_sha != "unanchored"
        rank = 3 if (anchored and t.dom_sha == dom_sha) else 2
        sim = _jaccard(my_tokens, t.tokens)
        hits.append(TrailHit(trail=t, intensity=effective_reward(t, now),
                             rank=rank, similarity=sim))
    hits.sort(key=lambda h: (-h.rank, -h.intensity))
    drift = None
    if dom_sha and any(h.rank == 2 for h in hits):
        drift = {
            "expected": sorted({h.trail.dom_sha for h in hits if h.rank == 2}),
            "observed": dom_sha,
        }
    return SniffResult(url=key, hits=hits[:max(k, 0)], drift=drift)
