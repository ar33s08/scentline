"""End-to-end tests: the example colony and the MCP server, run as real
subprocesses so what we demo is what CI checks (demo rot = red build)."""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONPATH": str(REPO)}


def test_checkout_demo_end_to_end(tmp_path):
    """Session A deposits (trap hazard + recovery route); session B sniffs it."""
    demo = REPO / "examples" / "checkout_demo.py"
    r = subprocess.run([sys.executable, str(demo)], capture_output=True,
                       text=True, timeout=120, cwd=tmp_path, env=ENV)
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "no scent here" in out                 # cold start is honest
    assert "! AVOID" in out                       # hazard reaches the follower
    assert "use product search" in out            # the route note travels
    # the colony file the demo wrote is valid JSONL with a hazard + a route
    colony = tmp_path / "demo.trails.jsonl"
    lines = [l for l in colony.read_text().splitlines() if l.strip()]
    kinds = [json.loads(l)["kind"] for l in lines]
    assert sorted(kinds) == ["hazard", "route"]


def test_mcp_server_smoke(tmp_path):
    """initialize + tools/list through the server binary, as a client would."""
    trail_file = str(tmp_path / "colony.trails.jsonl")
    msgs = "\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "scentline_stat", "arguments": {}}},
    ]) + "\n"
    r = subprocess.run([sys.executable, "-m", "scentline.mcp"], input=msgs,
                       capture_output=True, text=True, timeout=120, env=ENV)
    assert r.returncode == 0, r.stderr
    lines = [json.loads(l) for l in r.stdout.splitlines() if l.strip()]
    assert len(lines) == 3                        # notification got no reply
    assert len(lines[1]["result"]["tools"]) == 6
    assert "trails:" in lines[2]["result"]["content"][0]["text"]
