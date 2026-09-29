"""Scentline: stigmergic trail memory for web agents.

The live web becomes a pheromone substrate: agents lay evaporating,
DOM-anchored trails over the routes they walk, and every later session —
any framework, any process — sniffs those trails instead of re-deriving
the route from a cold page. Zero dependencies; standard library only.
"""

from .context import render_sniff
from .decay import effective_reward, is_live
from .fingerprint import canonical_url, fingerprint_dom
from .hooks import RouteRecorder, mark, sniff
from .store import TrailStore, default_path
from .types import SniffResult, Step, Trail, TrailHit

__version__ = "0.1.0"

__all__ = [
    "mark",
    "sniff",
    "RouteRecorder",
    "TrailStore",
    "default_path",
    "Trail",
    "Step",
    "TrailHit",
    "SniffResult",
    "render_sniff",
    "fingerprint_dom",
    "canonical_url",
    "effective_reward",
    "is_live",
    "__version__",
]
