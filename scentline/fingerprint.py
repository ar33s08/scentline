"""URL canonicalization and DOM structural fingerprinting.

These two functions are what make trails survive the web's noise:

* ``canonical_url``   – kills tracking params / fragments / case churn so two
                        agents landing on the "same" page share one scent key.
* ``fingerprint_dom`` – hashes the *structure* of a page (tags, roles, labels,
                        link paths) while ignoring the things that churn every
                        render: class names, ids, whitespace, script/style
                        content. Trails anchor to this, so a re-decorated page
                        still smells the same — and a genuinely redesigned page
                        is detected as drift instead of being followed blindly.
"""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "fbclid", "gclid", "dclid", "msclkid", "mc_eid", "igshid",
    "yclid", "_ga", "ref", "ref_src", "ref_url", "si", "spm", "from",
    "sessionid", "phpsessid", "jsessionid", "aspxautodetectcookiesupport",
    "vero_id", "mkt_tok", "trk_contact", "trk_msg", "trk_module", "trk_sid",
}

_WS = re.compile(r"\s+")


def canonical_url(url: str) -> str:
    """Normalize a URL into the shared scent key for a page."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if (scheme == "https" and parts.port == 443) or (scheme == "http" and parts.port == 80):
        host = host.split(":", 1)[0]
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
         if k.lower() not in TRACKING_PARAMS]
    q.sort()
    query = urlencode(q)
    return urlunsplit((scheme, host, path, query, ""))  # fragment always dropped


def _norm_label(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()[:80]


class _Outline(HTMLParser):
    """Extract a drift-stable structural outline from HTML."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr"}
    SKIP = {"script", "style", "svg", "noscript", "template", "head", "iframe"}
    INTERACTIVE = {"a", "button", "input", "select", "textarea", "label", "option"}
    STRUCTURAL = {"header", "nav", "main", "footer", "section", "article",
                  "aside", "form", "ul", "ol", "table", "dialog", "details",
                  "fieldset", "figure"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._skip_depth = 0
        self._interactive_depth = 0
        self._interactive_line = -1

    def handle_starttag(self, tag, attrs):
        if self._skip_depth:
            if tag not in self.VOID:
                self._skip_depth += 1
            return
        if tag in self.SKIP:
            self._skip_depth = 1
            return
        a = dict(attrs)
        if tag in self.INTERACTIVE:
            role = a.get("role") or ("link" if tag == "a" else tag)
            label = (a.get("aria-label") or a.get("placeholder")
                     or a.get("value") or a.get("name") or a.get("title")
                     or a.get("alt") or "")
            extra = ""
            if tag == "a" and a.get("href"):
                extra = " href=" + a["href"].split("?", 1)[0].split("#", 1)[0]
            if a.get("type") and tag in {"input", "button"}:
                extra += " type=" + a["type"]
            self.lines.append(f"{tag}[{role}] {_norm_label(label)}{extra}")
            self._interactive_line = len(self.lines) - 1
            self._interactive_depth += 1
            if tag not in self.VOID:
                return
        if tag in self.STRUCTURAL:
            self.lines.append(f"<{tag} role={a.get('role', '')}>")

    def handle_startendtag(self, tag, attrs):
        if self._skip_depth:
            return
        self.handle_starttag(tag, attrs)
        if tag in self.INTERACTIVE:
            self._interactive_depth = max(0, self._interactive_depth - 1)

    def handle_endtag(self, tag):
        if self._skip_depth:
            if tag not in self.VOID:
                self._skip_depth -= 1
            return
        if tag in self.INTERACTIVE and self._interactive_depth:
            self._interactive_depth -= 1
            self._interactive_line = -1

    def handle_data(self, data):
        if self._skip_depth or self._interactive_depth == 0 or self._interactive_line < 0:
            return
        text = _norm_label(data)
        if text:
            line = self.lines[self._interactive_line]
            if not line.endswith("]") and len(line) < 120:
                self.lines[self._interactive_line] = (line + " " + text)[:120]


def fingerprint_dom(html: str) -> str:
    """sha256 of the page's structural outline. Stable across cosmetic churn."""
    p = _Outline()
    try:
        p.feed(html)
        p.close()
    except Exception:  # malformed HTML must never crash an agent
        pass
    return hashlib.sha256("\n".join(p.lines).encode("utf-8")).hexdigest()
