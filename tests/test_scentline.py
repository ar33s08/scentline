"""Scentline test suite: canonicalization, fingerprinting, decay physics,
store merging/locking, sniffing ranks, projection, secret scrubbing."""

import json
import os
import subprocess
import sys
import time

import pytest

from scentline import (KIND_HAZARD, Step, Trail, TrailStore, canonical_url,
                       fingerprint_dom, is_live, mark, render_sniff, sniff)
from scentline.decay import effective_reward

PAGE_V1 = """<html><head><style>.a{color:red}</style><script>var x=1;</script></head>
<body><nav><a href="/shop">Shop</a></nav><main><input type="search" placeholder="Search"/>
<button class="btn btn-primary" id="submit">Add to cart</button></main></body></html>"""

PAGE_V1_REDECORATED = """<html><head><style>.zz{color:blue}</style><script>var y=9;</script></head>
<body><nav><a class="link-2024" href="/shop">Shop</a></nav><main><input type="search"
placeholder="Search"/><button class="new-theme" data-x="1">Add to cart</button></main></body></html>"""

PAGE_V2_RELABELLED = PAGE_V1_REDECORATED.replace("Add to cart", "Buy now")


# ---------------------------------------------------------------- URLs
def test_canonical_url_strips_tracking():
    a = canonical_url("https://www.shop.example.com/p/1?utm_source=email&fbclid=x&id=9")
    b = canonical_url("https://shop.example.com/p/1?id=9")
    assert a == b


def test_canonical_url_param_order_insensitive():
    assert (canonical_url("https://e.com/x?a=1&b=2")
            == canonical_url("https://e.com/x?b=2&a=1"))


def test_canonical_url_keeps_essential_params():
    assert "id=9" in canonical_url("https://e.com/p?id=9")


# ---------------------------------------------------------------- fingerprint
def test_fingerprint_survives_cosmetic_redesign():
    assert fingerprint_dom(PAGE_V1) == fingerprint_dom(PAGE_V1_REDECORATED)


def test_fingerprint_detects_label_change():
    assert fingerprint_dom(PAGE_V1_REDECORATED) != fingerprint_dom(PAGE_V2_RELABELLED)


def test_fingerprint_is_stable_sha():
    assert fingerprint_dom(PAGE_V1) == fingerprint_dom(PAGE_V1)


# ---------------------------------------------------------------- steps/trails
def test_step_token_excludes_value():
    assert (Step("fill", "#email", "a@b.c").token()
            == Step("fill", "#email", "x@y.z").token() == "fill:#email")


def test_trail_identity_keys_on_shape():
    a = Trail(url="https://e.com", dom_sha="d1", steps=[Step("click", "#go")])
    b = Trail(url="https://e.com?utm_source=x", dom_sha="d1", steps=[Step("click", "#go")])
    assert a.identity() == b.identity()


# ---------------------------------------------------------------- store
def _fresh_store(tmp_path):
    return TrailStore(tmp_path / "trails.jsonl")


def test_deposit_merge_adds_reward(tmp_path):
    s = _fresh_store(tmp_path)
    t1 = s.deposit(Trail(url="https://e.com/p", dom_sha="d", steps=[Step("click", "#a")]), now=100.0)
    t2 = s.deposit(Trail(url="https://e.com/p", dom_sha="d", steps=[Step("click", "#a")]), now=200.0)
    assert t2.id == t1.id and t2.deposits == 2 and len(t2.walks) == 2


def test_distinct_routes_stay_separate(tmp_path):
    s = _fresh_store(tmp_path)
    s.deposit(Trail(url="https://e.com", dom_sha="d", steps=[Step("click", "#a")]), now=100.0)
    s.deposit(Trail(url="https://e.com", dom_sha="d", steps=[Step("click", "#b")]), now=100.0)
    assert s.stat()["trails"] == 2


def test_evaporation_fades_old_trail(tmp_path):
    s = _fresh_store(tmp_path)
    t = s.deposit(Trail(url="https://e.com", dom_sha="d", steps=[Step("click", "#a")]), now=100.0)
    live = s.live_for_url("https://e.com", now=100.0 + 90 * 24 * 3600)  # 90 days later
    assert live == [] and not is_live(t, 100.0 + 90 * 24 * 3600)


def test_decay_stack_beats_single_walk():
    t = Trail(url="u", dom_sha="d", deposits=2,
              walks=[(0.0, 1.0), (1000.0, 1.0)])
    single = Trail(url="u", dom_sha="d", deposits=1, walks=[(0.0, 1.0)])
    assert effective_reward(t, 1000.0) > effective_reward(single, 1000.0)


def test_ttl_hard_kill():
    t = Trail(url="u", dom_sha="d", ttl_seconds=3600, walks=[(0.0, 5.0)])
    assert effective_reward(t, 3601.0) == 0.0


def test_events_log_written(tmp_path):
    s = _fresh_store(tmp_path)
    t = s.deposit(Trail(url="https://e.com", dom_sha="d", steps=[]), now=1.0)
    events = (tmp_path / "trails.jsonl.events.log").read_text()
    assert t.id in events and "deposit" in events


def test_cross_process_flock(tmp_path):
    """Two concurrent processes depositing the same route must merge cleanly."""
    script = tmp_path / "worker.py"
    script.write_text(
        "import sys, time\n"
        "from scentline import TrailStore, Trail, Step\n"
        "s = TrailStore(sys.argv[1])\n"
        "time.sleep(0.05)\n"
        "s.deposit(Trail(url='https://e.com', dom_sha='d', "
        "steps=[Step('click', '#a')]), now=time.time())\n")
    procs = [subprocess.Popen([sys.executable, str(script), str(tmp_path / "trails.jsonl")],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
             for _ in range(2)]
    errs = [p.communicate()[1].decode() for p in procs]
    assert all(p.returncode == 0 for p in procs), errs
    assert TrailStore(tmp_path / "trails.jsonl").stat()["walks"] == 2


# ---------------------------------------------------------------- sniffing
def test_sniff_ranks_exact_above_drift(tmp_path):
    s = _fresh_store(tmp_path)
    steps = [Step("click", "#a"), Step("fill", "#q")]
    s.deposit(Trail(url="https://e.com/x", dom_sha="AAA", steps=steps), now=100.0)
    s.deposit(Trail(url="https://e.com/x", dom_sha="BBB", steps=steps), now=100.0)
    r = sniff("https://e.com/x", dom_sha="AAA", store=s, now=101.0)
    assert r.hits[0].rank == 3 and r.hits[0].trail.dom_sha == "AAA"
    assert r.drift is not None and "BBB" in r.drift["expected"]


def test_sniff_cold_start_message(tmp_path):
    r = sniff("https://nothing.example.com", store=_fresh_store(tmp_path))
    assert r.hits == [] and "no scent" in render_sniff(r)


def test_render_budget_respected(tmp_path):
    s = _fresh_store(tmp_path)
    steps = [Step("click", f"#el{i}") for i in range(6)]
    s.deposit(Trail(url="https://e.com/x", dom_sha="AAA", steps=steps, note="hi"), now=100.0)
    r = sniff("https://e.com/x", dom_sha="AAA", store=s, now=101.0)
    assert len(render_sniff(r, budget_tokens=25)) <= 25 * 4 + 200  # header + one block


def test_render_note_survives(tmp_path):
    s = _fresh_store(tmp_path)
    s.deposit(Trail(url="https://e.com/x", dom_sha="AAA", steps=[Step("click", "#a")],
                    note="use catalog search, homepage search is broken"), now=100.0)
    r = sniff("https://e.com/x", dom_sha="AAA", store=s, now=101.0)
    assert "catalog search" in render_sniff(r)


# ---------------------------------------------------------------- recorder
def test_scrub_hides_typed_values(tmp_path):
    s = _fresh_store(tmp_path)
    with mark("https://e.com/login", html=PAGE_V1, store=s) as rec:
        rec.step("fill", "#email", "secret@x.com")
        rec.step("fill", "#pw", "hunter2")
        rec.step("click", "button[type=submit]")
        trail = rec.leave_trail(note="ok")
    assert all(st.value is None for st in trail.steps)
    assert "hunter2" not in json.dumps(trail.to_dict())


def test_persist_value_opt_in(tmp_path):
    with mark("https://e.com", html=PAGE_V1) as rec:
        rec.step("fill", "#q", "wireless headphones", persist_value=True)
        trail = rec.leave_trail()
    assert trail.steps[0].value == "wireless headphones"


def test_no_deposit_on_failure(tmp_path):
    s = _fresh_store(tmp_path)
    try:
        with mark("https://e.com", html=PAGE_V1, store=s) as rec:
            rec.step("click", "#a")
            raise RuntimeError("task failed")
    except RuntimeError:
        pass
    assert s.stat()["trails"] == 0


def test_evict_dead_gc(tmp_path):
    s = _fresh_store(tmp_path)
    s.deposit(Trail(url="https://e.com", dom_sha="d", steps=[Step("click", "#a")]), now=100.0)
    n = s.evict_dead(now=100.0 + 90 * 24 * 3600)
    assert n == 1 and s.stat()["trails"] == 0


# ---------------------------------------------------------------- hazards (negative pheromone)
def test_hazard_deposit_and_sniff(tmp_path):
    s = _fresh_store(tmp_path)
    steps = [Step("click", "#newsletter-modal")]
    s.deposit(Trail(url="https://e.com/x", dom_sha="AAA", steps=steps,
                    note="modal traps the agent forever", kind=KIND_HAZARD), now=100.0)
    r = sniff("https://e.com/x", dom_sha="AAA", store=s, now=101.0)
    assert len(r.hazards) == 1 and r.hits == []
    assert "AVOID" in render_sniff(r)
    assert "modal traps" in render_sniff(r)


def test_hazard_and_route_coexist_ranked(tmp_path):
    s = _fresh_store(tmp_path)
    steps = [Step("click", "#a")]
    s.deposit(Trail(url="https://e.com/x", dom_sha="AAA", steps=steps), now=100.0)
    s.deposit(Trail(url="https://e.com/x", dom_sha="AAA", steps=[Step("click", "#trap")],
                    kind=KIND_HAZARD), now=100.0)
    r = sniff("https://e.com/x", dom_sha="AAA", store=s, now=101.0)
    out = render_sniff(r)
    assert out.index("AVOID") < out.index("click:#a")  # hazards render first


def test_hazard_merges_by_identity(tmp_path):
    s = _fresh_store(tmp_path)
    steps = [Step("click", "#trap")]
    s.deposit(Trail(url="https://e.com/x", dom_sha="AAA", steps=steps, kind=KIND_HAZARD), now=100.0)
    t = s.deposit(Trail(url="https://e.com/x", dom_sha="AAA", steps=steps, kind=KIND_HAZARD), now=200.0)
    assert t.deposits == 2
    # a route deposit with the same shape must NOT merge into the hazard
    r = s.deposit(Trail(url="https://e.com/x", dom_sha="AAA", steps=steps), now=300.0)
    assert r.kind != KIND_HAZARD and r.deposits == 1
    assert s.stat()["trails"] == 2


def test_recorder_leave_hazard_clears_buffer(tmp_path):
    s = _fresh_store(tmp_path)
    with mark("https://e.com", html=PAGE_V1, store=s) as rec:
        rec.step("click", "#trap-link")
        rec.leave_hazard(note="infinite modal")
        rec.step("click", "#recovery-path")
        trail = rec.leave_trail(note="recovered via direct URL")
    assert s.stat()["hazards"] == 1
    assert [st.token() for st in trail.steps] == ["click:#recovery-path"]


def test_leave_hazard_requires_steps():
    with mark("https://e.com") as rec:
        with pytest.raises(RuntimeError):
            rec.leave_hazard()


# ---------------------------------------------------------------- host hints
def test_host_hints_returned_for_cold_page(tmp_path):
    s = _fresh_store(tmp_path)
    s.deposit(Trail(url="https://e.com/products/list", dom_sha="AAA",
                    steps=[Step("click", "#filter-price")]), now=100.0)
    r = sniff("https://e.com/products/42", dom_sha="ZZZ", store=s, now=101.0)
    assert r.hits == [] and len(r.host_hints) == 1
    assert r.host_hints[0].rank == 1 and r.host_hints[0].confidence < 1.0
    assert "hint" in render_sniff(r)


def test_host_hints_exclude_same_url_trails(tmp_path):
    s = _fresh_store(tmp_path)
    steps = [Step("click", "#a")]
    s.deposit(Trail(url="https://e.com/x", dom_sha="AAA", steps=steps), now=100.0)
    s.deposit(Trail(url="https://e.com/y", dom_sha="AAA", steps=steps), now=100.0)
    r = sniff("https://e.com/x", dom_sha="AAA", store=s, now=101.0)
    assert len(r.hits) == 1 and len(r.host_hints) == 1
    assert r.host_hints[0].trail.url == "https://e.com/y"


# ---------------------------------------------------------------- MCP server
def _rpc(msgs, tmp_path):
    trail_file = str(tmp_path / "mcp.trails.jsonl")
    proc = subprocess.run(
        [sys.executable, "-m", "scentline.mcp"],
        input="\n".join(json.dumps(m) for m in msgs) + "\n",
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "SCENTLINE_FILE": trail_file})
    assert proc.returncode == 0, proc.stderr
    return [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]


def test_mcp_initialize_and_tools_list(tmp_path):
    out = _rpc([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ], tmp_path)
    assert out[0]["result"]["serverInfo"]["name"] == "scentline"
    names = {t["name"] for t in out[1]["result"]["tools"]}
    assert {"scentline_sniff", "scentline_deposit_route",
            "scentline_deposit_hazard", "scentline_stat"} <= names


def test_mcp_deposit_then_sniff_roundtrip(tmp_path):
    steps = [{"action": "click", "target": "#buy"}]
    out = _rpc([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "scentline_deposit_route",
            "arguments": {"url": "https://e.com/x", "steps": steps, "note": "works"}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "scentline_sniff",
            "arguments": {"url": "https://e.com/x"}}},
    ], tmp_path)
    assert "deposited route" in out[1]["result"]["content"][0]["text"]
    assert "click:#buy" in out[2]["result"]["content"][0]["text"]


def test_mcp_hazard_tool(tmp_path):
    out = _rpc([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "scentline_deposit_hazard",
            "arguments": {"url": "https://e.com/x",
                          "steps": [{"action": "click", "target": "#trap"}]}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "scentline_sniff",
            "arguments": {"url": "https://e.com/x"}}},
    ], tmp_path)
    assert "hazard" in out[1]["result"]["content"][0]["text"]
    assert "AVOID" in out[2]["result"]["content"][0]["text"]


def test_mcp_scrubs_secret_values(tmp_path):
    out = _rpc([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "scentline_deposit_route",
            "arguments": {"url": "https://e.com/x",
                          "steps": [{"action": "fill", "target": "#pw",
                                     "value": "hunter2"}]}}},
    ], tmp_path)
    assert "deposited route" in out[1]["result"]["content"][0]["text"]
    trail_file = tmp_path / "mcp.trails.jsonl"
    assert "hunter2" not in trail_file.read_text()


def test_mcp_error_handling(tmp_path):
    out = _rpc([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "scentline_reinforce",
            "arguments": {"trail_id": "nope", "delta": 1.0}}},
        {"jsonrpc": "2.0", "id": 3, "method": "bogus/method"},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "no_such_tool", "arguments": {}}},
    ], tmp_path)
    # reinforcing an evaporated trail is a domain outcome, not a tool error
    assert "not found" in out[1]["result"]["content"][0]["text"]
    assert out[2]["error"]["code"] == -32601
    assert out[3]["result"]["isError"] is True


def test_mcp_survives_parse_error_and_empty_lines(tmp_path):
    trail_file = str(tmp_path / "mcp.trails.jsonl")
    proc = subprocess.run(
        [sys.executable, "-m", "scentline.mcp"],
        input="{broken json\n\n{\"jsonrpc\": \"2.0\", \"id\": 9, \"method\": \"ping\"}\n",
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "SCENTLINE_FILE": trail_file})
    assert proc.returncode == 0
    lines = [json.loads(l) for l in proc.stdout.splitlines() if l.strip()]
    assert lines[0]["error"]["code"] == -32700
    assert lines[1]["result"] == {}


# ---------------------------------------------------------------- CLI errors
def test_cli_deposit_missing_file(tmp_path):
    r = subprocess.run([sys.executable, "-m", "scentline.cli", "--file",
                        str(tmp_path / "t.jsonl"), "deposit", "/nonexistent.json"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "not found" in r.stderr


def test_cli_deposit_bad_json(tmp_path):
    r = subprocess.run([sys.executable, "-m", "scentline.cli", "--file",
                        str(tmp_path / "t.jsonl"), "deposit", "-"],
                       input="{not json", capture_output=True, text=True)
    assert r.returncode == 2 and "not valid JSON" in r.stderr


def test_cli_sniff_json_shows_hazards(tmp_path):
    s = _fresh_store(tmp_path)
    now = time.time()
    s.deposit(Trail(url="https://e.com/x", dom_sha="AAA",
                    steps=[Step("click", "#trap")], kind=KIND_HAZARD), now=now)
    r = subprocess.run([sys.executable, "-m", "scentline.cli", "--file",
                        str(tmp_path / "trails.jsonl"),
                        "sniff", "https://e.com/x", "--json"],
                       capture_output=True, text=True,
                       env={**os.environ,
                            "PYTHONPATH": os.path.dirname(os.path.dirname(
                                os.path.abspath(__file__)))})
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["hazards"][0]["kind"] == "hazard"
