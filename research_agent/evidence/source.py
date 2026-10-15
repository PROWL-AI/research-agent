"""Source identity and quote checks for the evidence ledger (wave 3, KA-08/KA-09).

Independence is a property of where data came from, not of the tool that
delivered it: a web search and a page scraper reading one URL are one source.

* A claim with a URL is keyed by its **publisher** — the registrable domain of the
  normalized URL — so two pages of one site are one source too.
* A claim without a URL is keyed by its **data provider** — the tool name's prefix
  (`spyfu_get_domain_stats` → `spyfu`): two endpoints of one provider are one
  source, two providers are two.
* A transform (an LLM summary of earlier steps) has **no** key: it never adds
  independence (B-007).

The registrable-domain rule uses a small built-in list of multi-label public
suffixes (`co.uk`, `com.au`, …) rather than the full Public Suffix List; a domain
under an unlisted multi-label suffix is keyed one label too wide, which errs
toward treating two sources as one — the safe direction for `verified`.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

#: Multi-label public suffixes under which the registrable domain has three labels.
_MULTI_LABEL_SUFFIXES = frozenset({
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "ltd.uk", "plc.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp",
    "co.nz", "org.nz", "govt.nz", "co.za", "org.za", "gov.za",
    "com.br", "net.br", "org.br", "gov.br", "com.mx", "org.mx", "gob.mx",
    "com.cn", "net.cn", "org.cn", "gov.cn", "com.hk", "org.hk",
    "com.sg", "edu.sg", "gov.sg", "com.tw", "org.tw", "co.kr", "or.kr",
    "co.in", "net.in", "org.in", "gov.in", "co.il", "org.il",
    "com.tr", "org.tr", "com.ar", "com.co", "com.pl", "com.ua", "co.id", "or.id",
})
_TRACKING_PARAMS = re.compile(r"^(utm_[a-z]+|gclid|fbclid|msclkid|mc_cid|mc_eid|ref|ref_src)$", re.I)
_DEFAULT_PORTS = {"http": "80", "https": "443"}
_TRANSFORM_TOOLS = frozenset({"transform", "llm_transform"})


def normalize_url(url: str | None) -> str | None:
    """Lowercase scheme and host, drop `www.`, default ports, fragments,
    tracking parameters and a trailing slash."""
    if not url or not isinstance(url, str):
        return None
    text = url.strip()
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host if port is None or str(port) == _DEFAULT_PORTS.get(parts.scheme.lower()) else f"{host}:{port}"
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not _TRACKING_PARAMS.match(k)])
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower() or "https", netloc, path, query, ""))


def publisher(url: str | None) -> str | None:
    """The registrable domain of a URL (`news.bbc.co.uk` → `bbc.co.uk`)."""
    normalized = normalize_url(url)
    if normalized is None:
        return None
    host = urlsplit(normalized).hostname or ""
    labels = host.split(".")
    if len(labels) <= 2 or re.fullmatch(r"[\d.]+", host):
        return host
    keep = 3 if ".".join(labels[-2:]) in _MULTI_LABEL_SUFFIXES else 2
    return ".".join(labels[-keep:])


def provider(tool: str | None) -> str | None:
    if not tool:
        return None
    name = tool.strip().lower()
    if name in _TRANSFORM_TOOLS:
        return None
    return name.split("_", 1)[0] or None


def independence_key(tool: str | None, url: str | None) -> str | None:
    """Two claims corroborate only with two DIFFERENT known keys. None = unknown,
    which never counts."""
    if tool and tool.strip().lower() in _TRANSFORM_TOOLS:
        return None
    site = publisher(url)
    if site:
        return f"publisher:{site}"
    source = provider(tool)
    return f"provider:{source}" if source else None


# ── quotes against the stored raw ────────────────────────────────────────────

_WS = re.compile(r"\s+")


def flatten_text(payload: Any) -> str:
    """Every string and number in a raw payload, whitespace-normalized and
    joined — the text a quote is searched in. JSON escaping never hides a quote,
    and nothing is truncated (the extractor only saw the first 12k chars; the
    check reads all of it)."""
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
        elif isinstance(node, bool) or node is None:
            return
        elif isinstance(node, (int, float, str)):
            parts.append(str(node))

    walk(payload)
    return _WS.sub(" ", " ".join(parts)).strip()


def find_quote(quote: str | None, text: str) -> tuple[int, int] | None:
    """(start, end) of the whitespace-normalized quote in `text`, case-insensitive."""
    if not quote or not isinstance(quote, str):
        return None
    needle = _WS.sub(" ", quote).strip().casefold()
    if len(needle) < 3:
        return None
    start = text.casefold().find(needle)
    return (start, start + len(needle)) if start >= 0 else None


def _digits(text: str) -> str:
    return re.sub(r"[\s,  ']", "", text)


def value_in_quote(value: Any, quote: str) -> bool:
    """The claim's value is literally present in the quote it cites (numbers
    compared without thousands separators: `1,200` == 1200)."""
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        candidates = {str(value)}
        if float(value).is_integer():
            candidates.add(str(int(value)))
        packed = _digits(quote)
        return any(re.search(rf"(?<![\d.]){re.escape(c)}(?![\d])", packed) for c in candidates)
    text = str(value).strip()
    if not text:
        return True
    if re.fullmatch(r"[\d.,\s]+", text):
        return _digits(text) in _digits(quote)
    return text.casefold() in quote.casefold()
