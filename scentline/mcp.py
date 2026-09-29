"""Scentline MCP server: any MCP client shares the colony. Zero dependencies.

Implements the Model Context Protocol stdio transport (newline-delimited
JSON-RPC 2.0) with nothing but the standard library — no `mcp` package, no
SDK. Run it with any client:

    claude mcp add scentline -- python -m scentline.mcp
    # or in an MCP client config:
    {"command": "python", "args": ["-m", "scentline.mcp"],
     "env": {"SCENTLINE_FILE": "/path/to/trails.jsonl"}}

Tools exposed:
    scentline_sniff           – read the scent at a URL (routes + hazards + hints)
    scentline_deposit_route   – deposit a successful route (positive pheromone)
    scentline_deposit_hazard  – deposit a failure warning (negative pheromone)
    scentline_reinforce       – add/evaporate pheromone on a trail by id
    scentline_gc              – evaporate dead trails
    scentline_stat            – colony stats

Protocol hygiene: stdout carries ONLY protocol messages; all diagnostics go
to stderr; malformed requests get JSON-RPC errors, never a crash.
"""

from __future__ import annotations

import json
import sys

from .context import render_sniff
from .store import TrailStore, sniff as _sniff
from .types import KIND_HAZARD, KIND_ROUTE, Step, Trail

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "scentline", "version": "0.2.0"}

_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string",
                   "description": "click|fill|select|press|scroll|goto|extract|wait"},
        "target": {"type": "string",
                   "description": "CSS selector or accessible label of the element"},
        "value": {"type": "string",
                  "description": "payload; scrubbed for fill/press/select unless persist_value"},
        "persist_value": {"type": "boolean",
                          "description": "keep the value (ONLY for public data like search queries)"},
    },
    "required": ["action", "target"],
}

_URL_PROPS = {
    "url": {"type": "string", "description": "page URL the trail lives on"},
    "dom_sha": {"type": "string",
                "description": "structural fingerprint of the page state "
                               "(scentline.fingerprint_dom of the live HTML)"},
    "steps": {"type": "array", "items": _STEP_SCHEMA},
    "note": {"type": "string",
             "description": "why this route works / failed — shown to every later agent"},
    "ttl_seconds": {"type": "number",
                    "description": "hard expiry override (e.g. 3600 for volatile pages)"},
    "author": {"type": "string", "description": "agent/session id"},
}

TOOLS = [
    {
        "name": "scentline_sniff",
        "description": "Sniff shared trail memory at a URL before acting: returns live "
                       "routes to follow, hazards to avoid (negative pheromone), drift "
                       "warnings, and same-host hints. Cold-start cost killer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "dom_sha": {"type": "string",
                            "description": "fingerprint of the live page; enables drift detection"},
                "my_tokens": {"type": "array", "items": {"type": "string"},
                              "description": "your steps so far (Step.token() strings)"},
                "k": {"type": "integer", "description": "max routes returned (default 3)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "scentline_deposit_route",
        "description": "Deposit a SUCCESSFUL route as positive pheromone. Same route "
                       "shape from any agent merges into one collective trail.",
        "inputSchema": {"type": "object",
                        "properties": _URL_PROPS,
                        "required": ["url", "steps"]},
    },
    {
        "name": "scentline_deposit_hazard",
        "description": "Deposit a FAILURE as negative pheromone: warn every later agent "
                       "away from this route shape. Hazards evaporate like any scent.",
        "inputSchema": {"type": "object",
                        "properties": _URL_PROPS,
                        "required": ["url", "steps"]},
    },
    {
        "name": "scentline_reinforce",
        "description": "Add positive (or negative) pheromone to a trail by id.",
        "inputSchema": {"type": "object",
                        "properties": {"trail_id": {"type": "string"},
                                       "delta": {"type": "number"}},
                        "required": ["trail_id", "delta"]},
    },
    {
        "name": "scentline_gc",
        "description": "Evaporate dead trails (below intensity floor / past TTL).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "scentline_stat",
        "description": "Colony stats: trails, walks, hazards, scent mass.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _trail_from_args(args: dict, kind: str) -> Trail:
    steps = []
    for raw in args.get("steps", []):
        action = str(raw.get("action", "")).lower()
        value = raw.get("value")
        # server-side scrubbing, mirroring the recorder defaults
        if action in ("fill", "press", "select") and not raw.get("persist_value"):
            value = None
        steps.append(Step(action=action, target=str(raw.get("target", "")),
                          value=value, dom_sha=raw.get("dom_sha")))
    return Trail(url=args["url"], dom_sha=args.get("dom_sha") or "unanchored",
                 steps=steps, author=args.get("author", "mcp-client"),
                 note=args.get("note"), ttl_seconds=args.get("ttl_seconds"), kind=kind)


def _call_tool(store: TrailStore, name: str, args: dict) -> str:
    if name == "scentline_sniff":
        result = _sniff(args["url"], dom_sha=args.get("dom_sha"),
                        my_tokens=args.get("my_tokens"), k=int(args.get("k", 3)),
                        store=store)
        return render_sniff(result)

    if name == "scentline_deposit_route":
        stored = store.deposit(_trail_from_args(args, KIND_ROUTE))
        return (f"deposited route {stored.id}: {len(stored.steps)} steps, "
                f"{stored.deposits} walk(s) total")

    if name == "scentline_deposit_hazard":
        if not args.get("steps"):
            raise ValueError("a hazard needs at least one step: which path failed?")
        stored = store.deposit(_trail_from_args(args, KIND_HAZARD))
        return (f"deposited hazard {stored.id}: later agents will be warned "
                f"away from this route")

    if name == "scentline_reinforce":
        t = store.reinforce(args["trail_id"], float(args["delta"]))
        return f"trail {args['trail_id']} updated" if t else \
            f"trail {args['trail_id']} not found (evaporated?)"

    if name == "scentline_gc":
        n = store.evict_dead()
        return f"evaporated {n} dead trail(s)"

    if name == "scentline_stat":
        s = store.stat()
        return (f"trails: {s['trails']} | walks: {s['walks']} | "
                f"hazards: {s['hazards']} | scent mass: {s['scent_mass']}")

    raise KeyError(f"unknown tool: {name}")


def _handle(store: TrailStore, msg: dict) -> dict | None:
    if msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return {"jsonrpc": "2.0", "id": msg.get("id"), "error":
                {"code": -32600, "message": "not a JSON-RPC 2.0 request"}}

    method = msg["method"]
    msg_id = msg.get("id")
    is_notification = msg_id is None

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }}
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            text = _call_tool(store, name, args)
        except Exception as e:  # tool errors are results, not protocol errors
            return {"jsonrpc": "2.0", "id": msg_id, "result": {
                "content": [{"type": "text", "text": f"error: {e}"}],
                "isError": True}}
        return {"jsonrpc": "2.0", "id": msg_id,
                "result": {"content": [{"type": "text", "text": text}]}}
    if method.startswith("notifications/"):
        return None
    if is_notification:
        return None
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"method not found: {method}"}}


def serve(store: TrailStore | None = None) -> int:
    store = store or TrailStore()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32700, "message": "parse error"}}
        else:
            try:
                resp = _handle(store, msg)
            except Exception as e:  # a bug must never kill the server
                print(f"[scentline-mcp] internal error: {e}", file=sys.stderr, flush=True)
                resp = {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                        "error": {"code": -32603, "message": "internal error"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
