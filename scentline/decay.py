"""Evaporation: the ant-colony physics that keep trails honest.

Every walk of a route deposits its own scent contribution, and each
contribution evaporates from its own timestamp:

    intensity(t) = Σ rᵢ · 2^(−(t−tᵢ)/half_life)

Routes agents keep walking stay hot; routes nobody walks fade walk-by-walk
and vanish from projections (and from the live set once past TTL / floor).
"""

from __future__ import annotations

import math

from .types import Trail

DEFAULT_HALF_LIFE_SECONDS = 3 * 24 * 3600   # 3 days: web UIs change too fast for month-old routes
DEFAULT_TTL_SECONDS = 30 * 24 * 3600        # hard kill after 30 days of silence
INTENSITY_FLOOR = 0.05                      # below this, a trail is invisible to sniff()


def effective_reward(
    trail: Trail,
    now: float,
    half_life_seconds: float = DEFAULT_HALF_LIFE_SECONDS,
    default_ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> float:
    """Live scent of a trail at ``now``: the sum of every walk's
    contribution, each decaying exponentially from its own walk time.
    Returns 0.0 once the newest walk is older than the TTL."""
    lam = math.log(2.0) / max(half_life_seconds, 1e-9)
    ttl = trail.ttl_seconds if trail.ttl_seconds is not None else default_ttl_seconds
    if trail.walks:
        newest = max(w[0] for w in trail.walks)
    else:
        newest = trail.last_deposit_at
    if ttl is not None and (now - newest) > ttl:
        return 0.0
    records = trail.walks or [(newest, trail.reward)]
    return sum(float(r) * math.exp(-lam * max(0.0, now - float(t)))
               for t, r in records)


def is_live(trail: Trail, now: float, floor: float = INTENSITY_FLOOR) -> bool:
    return effective_reward(trail, now) >= floor
