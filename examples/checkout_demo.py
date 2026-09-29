# Demo: two scentline sessions sharing one colony file.
# Session A walks a cold site and lays a trail on success.
# Session B (a different process, maybe a different framework) sniffs first.

import scentline

FILE = "demo.trails.jsonl"
URL = "https://shop.example.com/sale"

COLD_HTML = """<html><body>
  <input type="search" placeholder="Search products"/>
  <button>Add to cart</button><a href="/checkout">Checkout</a>
</body></html>"""


def session_a():
    """First agent: no scent exists; it explores, hits a trap, recovers."""
    store = scentline.TrailStore(FILE)
    print(scentline.sniff(URL, store=store).render())
    with scentline.mark(URL, html=COLD_HTML, author="agent-a", store=store) as rec:
        rec.step("fill", "input[type=search]", "headphones", persist_value=True)
        rec.step("click", "button")
        rec.step("click", "a[href='/sponsored-landing']")   # a trap: dead end
        rec.leave_hazard(note="sponsored landing is a dead end — go straight to /checkout")
        rec.step("click", "a[href='/checkout']")
        trail = rec.leave_trail(note="use product search, then /checkout link")
        print(f"agent-a deposited route {trail.id} + 1 hazard")


def session_b():
    """Second agent: sniffs the shared file before acting on the cold page."""
    store = scentline.TrailStore(FILE)
    print(scentline.sniff(URL, dom_sha=scentline.fingerprint_dom(COLD_HTML),
                          store=store).render())
    # -> hazard first (! AVOID ...), then the rank-3 route to follow


if __name__ == "__main__":
    session_a()
    session_b()
