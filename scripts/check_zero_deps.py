"""CI gate: Scentline's core must import and run with zero third-party packages.

Simulates a bare environment by blocking every non-stdlib import at the meta-
path level, then deposits + sniffs a real trail. Any phantom dependency in
the package fails this gate.
"""

from __future__ import annotations

import importlib.abc
import sys
import tempfile


class BareEnvironmentFinder(importlib.abc.MetaPathFinder):
    """Block any top-level import that is not stdlib or explicitly allowed."""

    def __init__(self, allowed: set[str]) -> None:
        self.allowed = allowed

    def find_spec(self, fullname, path=None, target=None):
        root = fullname.split(".")[0]
        if root in sys.stdlib_module_names or root in self.allowed:
            return None
        raise ImportError(f"non-stdlib import blocked by zero-dep gate: {fullname}")


def main() -> int:
    gate = BareEnvironmentFinder(allowed={"scentline"})
    sys.meta_path.insert(0, gate)
    try:
        import scentline

        assert scentline.__version__
        with tempfile.TemporaryDirectory() as td:
            store = scentline.TrailStore(f"{td}/gate.trails.jsonl")
            trail = scentline.Trail(url="https://gate.example.com", dom_sha="d",
                                    steps=[scentline.Step("click", "#a")])
            stored = store.deposit(trail)
            hit = scentline.sniff("https://gate.example.com", dom_sha="d", store=store)
            assert hit.hits and hit.hits[0].rank == 3
            assert "click:#a" in hit.render()
            print(f"zero-dep gate OK: scentline {scentline.__version__}, "
                  f"trail {stored.id} deposited and sniffed")
        return 0
    finally:
        sys.meta_path.remove(gate)


if __name__ == "__main__":
    raise SystemExit(main())
