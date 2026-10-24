"""Source identity and quote checks for the evidence ledger (wave 3, KA-08/KA-09).

Independence is a property of where data came from, not of the tool that
delivered it: a web search and a page scraper reading one URL are one source.

* A claim with a URL is keyed by its **publisher** — the registrable domain of the
  normalized URL — so two pages of one site are one source too.
* A claim without a URL is keyed by its **data provider** — the tool name's prefix
  (`spyfu_get_domain_stats` → `spyfu`): two endpoints of one provider are one
  source, two providers are two.
* A claim without a URL is keyed by its **data provider** after delivery
  wrappers are removed: `serpapi_google_trends` and `google_trends` read one
  upstream dataset (`google:trends`), so they are one source.
* A transform (an LLM summary of earlier steps) and an **LLM-answer tool**
  (perplexity, gemini, AI-mode/overview, `*_responses`) have **no** key and never
  span-verify: an LLM's text is not a primary source (B-007, runbook rule).
* A web search/scrape/crawl tool's claim without a URL has no key: which page it
  came from is unknown.

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
#: The one transform-tool set (orchestrator and migration import it).
TRANSFORM_TOOLS = frozenset({"transform", "llm_transform"})
#: Tools whose payload is an LLM's answer (judge's "LLM-derived" metric reads this too).
_LLM_ANSWER_PREFIXES = (
    "perplexity_", "gemini_", "llm_query_", "openai_", "claude_", "exa_answer",
    "google_ai_mode", "serpapi_google_ai_overview", "dataforseo_serp_google_ai_mode",
)
_LLM_ANSWER_SUFFIXES = ("_responses", "_scraper")
#: Delivery wrappers in front of an upstream dataset's own name.
_DELIVERY_PREFIXES = ("serpapi_", "searchapi_", "dataforseo_serp_", "dataforseo_biz_social_", "dataforseo_biz_")
#: Google product families whose tool names differ between delivery vendors.
_GOOGLE_FAMILY = {
    "maps_reviews": "reviews", "reviews": "reviews", "qna": "reviews", "place": "maps", "local": "maps",
    "organic": "search", "search": "search", "rank_tracking": "search",
    "trending_now": "trends", "trending_now_news": "trends", "trends_autocomplete": "trends",
    "news_light": "news", "news_portal": "news", "ai_overview": "ai", "ai_mode": "ai",
}
#: Providers whose payload is pages of the open web: a claim from them without a
#: URL came from some page, which one is unknown.
_WEB_PROVIDERS = frozenset({"web", "page", "firecrawl", "exa", "scrape", "crawl", "fetch",
                            "google:search", "google:news", "google:forums", "google:scholar"})


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


def is_transform(tool: str | None) -> bool:
    return bool(tool) and tool.strip().lower() in TRANSFORM_TOOLS


def is_llm_answer(tool: str | None) -> bool:
    """The tool returns an LLM's answer — never a primary source."""
    if not tool:
        return False
    name = tool.strip().lower()
    if name.startswith(_LLM_ANSWER_PREFIXES):
        return True
    return name.startswith("dataforseo_ai_") and name.endswith(_LLM_ANSWER_SUFFIXES)


def is_web_tool(tool: str | None) -> bool:
    name = (tool or "").strip().lower()
    return provider(name) in _WEB_PROVIDERS or any(m in name for m in ("scrape", "crawl"))


def provider(tool: str | None) -> str | None:
    """The upstream data provider/dataset a tool reads, with delivery wrappers
    removed (`serpapi_google_trends` == `google_trends` == `google:trends`)."""
    if not tool or is_transform(tool) or is_llm_answer(tool):
        return None
    name = tool.strip().lower()
    for prefix in _DELIVERY_PREFIXES:
        if name.startswith(prefix) and len(name) > len(prefix):
            name = name[len(prefix):]
            break
    if name.startswith("google_"):
        rest = name[len("google_"):]
        family = _GOOGLE_FAMILY.get(rest)
        if family is None:
            family = next((v for k, v in _GOOGLE_FAMILY.items() if rest.startswith(k + "_")), None)
        return "google:" + (family or rest.split("_", 1)[0])
    if name.startswith(("meta_ad_library", "facebook_ad")):
        return "meta:ad_library"
    return name.split("_", 1)[0] or None


def independence_key(tool: str | None, url: str | None) -> str | None:
    """Two claims corroborate only with two DIFFERENT known keys. None = unknown,
    which never counts."""
    if is_transform(tool) or is_llm_answer(tool):
        return None
    site = publisher(url)
    if site:
        return f"publisher:{site}"
    if is_web_tool(tool):
        return None  # a page was read, but which one is unknown
    source = provider(tool)
    return f"provider:{source}" if source else None


def url_in_text(url: str | None, *texts: str) -> bool:
    """The URL's host occurs in one of the texts — the extractor did not invent it."""
    normalized = normalize_url(url)
    if normalized is None:
        return False
    host = urlsplit(normalized).hostname or ""
    if not host:
        return False
    return any(host in (text or "").casefold() for text in texts)


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


def normalize_space(text: str) -> str:
    return _WS.sub(" ", text).strip()


def find_quote(quote: str | None, text: str) -> tuple[int, int] | None:
    """(start, end) of the quote in `text` (offsets into `text` itself),
    whitespace-normalized and case-insensitive, matched on token boundaries.

    A quote must say more than a bare number: `1200` alone would be "found"
    inside any id or larger figure, so a quote needs at least one word."""
    if not quote or not isinstance(quote, str):
        return None
    needle = normalize_space(quote)
    if len(needle) < 4 or not re.search(r"[^\W\d_]{2,}", needle):
        return None
    words = [re.escape(w) for w in needle.split(" ")]
    pattern = r"\s+".join(words)
    if needle[0].isalnum():
        pattern = r"(?<![0-9A-Za-z])" + pattern
    if needle[-1].isalnum():
        pattern += r"(?![0-9A-Za-z])"
    match = re.search(pattern, text, re.IGNORECASE)
    return (match.start(), match.end()) if match else None


_GROUP_SEP = re.compile(r"(?<=\d)[,\u00a0\u202f' ](?=\d{3}(?!\d))")
_NUMERIC_TEXT = re.compile(r"[$€£]?\s*[-+]?[\d][\d.,\s\u00a0\u202f']*%?")


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not _NUMERIC_TEXT.fullmatch(text):
        return None
    packed = _GROUP_SEP.sub("", text.strip("$€£% ").strip())
    try:
        return float(packed.replace(" ", ""))
    except ValueError:
        return None


def value_in_quote(value: Any, quote: str) -> bool:
    """The claim's value is literally present in the quote it cites. Numbers
    match on number boundaries (1200 is not inside 11,200, nor 1,200.5);
    thousands separators inside a digit group are ignored."""
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    number = _as_number(value)
    if number is not None:
        candidates = {repr(number) if not number.is_integer() else str(int(number))}
        if not number.is_integer():
            candidates.add(str(number))
        packed = _GROUP_SEP.sub("", quote)
        return any(re.search(rf"(?<![\d.]){re.escape(c)}(?!\.\d|\d)", packed) for c in candidates)
    text = str(value).strip()
    if not text:
        return False
    return text.casefold() in quote.casefold()
