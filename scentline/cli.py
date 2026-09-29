"""scentline CLI: deposit / sniff / gc / stat.

Examples:
    scentline sniff "https://shop.example.com/sale" --dom-sha <fp>
    scentline deposit trail.json
    scentline gc
    scentline stat
"""

from __future__ import annotations

import argparse
import json
import sys

from .context import render_sniff
from .store import TrailStore, sniff as _sniff
from .types import KIND_ROUTE, Step, Trail


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="scentline",
        description="Stigmergic trail memory for web agents.")
    p.add_argument("--file", default=None,
                   help="trail file (default: $SCENTLINE_FILE or ~/.scentline/trails.jsonl)")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("deposit", help="deposit a trail from a JSON file ('-' = stdin)")
    d.add_argument("payload", nargs="?", default="-")

    s = sub.add_parser("sniff", help="sniff the shared scent at a URL")
    s.add_argument("url")
    s.add_argument("--dom-sha", default=None, help="live page fingerprint (enables drift detection)")
    s.add_argument("--json", action="store_true", dest="as_json")

    g = sub.add_parser("gc", help="evaporate dead trails (below floor / past TTL)")
    g.add_argument("--json", action="store_true", dest="as_json")

    st = sub.add_parser("stat", help="colony stats")
    st.add_argument("--json", action="store_true", dest="as_json")

    args = p.parse_args(argv)
    store = TrailStore(args.file)

    if args.cmd == "deposit":
        try:
            if args.payload == "-":
                raw = sys.stdin.read()
            else:
                with open(args.payload, encoding="utf-8") as fh:
                    raw = fh.read()
            data = json.loads(raw)
        except FileNotFoundError:
            print(f"scentline: payload file not found: {args.payload}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as e:
            print(f"scentline: payload is not valid JSON: {e}", file=sys.stderr)
            return 2
        trail = Trail(url=data["url"], dom_sha=data.get("dom_sha", "unanchored"),
                      steps=[Step.from_dict(x) for x in data.get("steps", [])],
                      author=data.get("author", "cli"), note=data.get("note"),
                      ttl_seconds=data.get("ttl_seconds"),
                      kind=data.get("kind", KIND_ROUTE))
        stored = store.deposit(trail)
        print(json.dumps({"id": stored.id, "kind": stored.kind,
                          "deposits": stored.deposits, "reward": stored.reward}))
        return 0

    if args.cmd == "sniff":
        result = _sniff(args.url, dom_sha=args.dom_sha, store=store)
        if args.as_json:
            def hit_json(h):
                return {"id": h.trail.id, "kind": h.trail.kind, "rank": h.rank,
                        "intensity": round(h.intensity, 3),
                        "similarity": round(h.similarity, 3),
                        "confidence": round(h.confidence, 3),
                        "walks": h.trail.deposits,
                        "tokens": h.trail.tokens,
                        "note": h.trail.note}
            print(json.dumps({
                "url": result.url,
                "drift": result.drift,
                "hits": [hit_json(h) for h in result.hits],
                "hazards": [hit_json(h) for h in result.hazards],
                "host_hints": [hit_json(h) for h in result.host_hints],
            }, indent=2))
        else:
            print(render_sniff(result))
        return 0

    if args.cmd == "gc":
        n = store.evict_dead()
        print(json.dumps({"evicted": n}) if args.as_json
              else f"evaporated {n} dead trail(s)")
        return 0

    if args.cmd == "stat":
        s = store.stat()
        print(json.dumps(s) if args.as_json
              else f"trails: {s['trails']} | walks: {s['walks']} | "
                   f"hazards: {s['hazards']} | scent mass: {s['scent_mass']}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
