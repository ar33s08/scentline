"""Scentline test suite: canonicalization, fingerprinting, decay physics,
store merging/locking, sniffing ranks, projection, secret scrubbing."""

import json
import subprocess
import sys
import time

import pytest

from scentline import (Step, Trail, TrailStore, canonical_url,
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
