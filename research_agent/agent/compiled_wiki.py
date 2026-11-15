# vendored from patterns/compiled-wiki/code/compiled_wiki.py@1.0.0
"""A compiled wiki: a map of pages a model keeps over immutable raw sources, written only by code (pattern compiled-wiki).

The model reads a source and proposes an ingest plan (which pages it touches, each claim with a verbatim quote); this
module checks the plan against the source and writes everything itself: the pages (frontmatter as the truth, the body
rendered from it), `index.md`, the append-only `log.md` and the open items. Nothing a model writes reaches a page
unchecked, and nothing is overwritten in silence:

* raw sources are immutable and content-hashed: the same id with other text is refused; a new version is a new id;
* every claim on a page rests on a source span (`sha256` of the source, character span, the quote that sits there);
  a claim whose quote is not in the source, or that adds a number its quote lacks, is rejected and named. What is
  checked is the quote and the claim's numbers, not the meaning of the paraphrase: the page shows the quote beside the
  claim, and a stricter check (research `code/quotes.py`) can be injected as `claim_check`;
* a claim from another source that disagrees with a live claim on the same page and key (other numbers, or other
  words when neither has a number) is kept beside it, both `contested`, and an open item is filed first; only
  `resolve` with a reason marks one `superseded`; a withdrawn source's claims become `withdrawn`, never deleted;
* `lint` finds open contradictions, stale claims (a newer source disagrees), orphan pages, links to missing pages,
  missing cross-links, sources whose bytes changed, claims no longer found at their span, pages edited by hand and a
  rewritten log;
* a query reads the map AND the raw spans its pages cite, and falls back to raw-source windows when the pages do not
  cover the question (a compiled page loses detail: the wiki is a map beside retrieval, never the only source);
* an answer is checked claim by claim against what was retrieved; a good one is filed back as a `derived` page whose
  claims keep their raw source spans;
* source text reaches a model only through a fence the caller supplies (`patterns/untrusted-fence`), and a page or an
  answer leaves only through an outbound guard the caller supplies (`patterns/privacy-filter`); without them the call
  is refused.

What to replace: the storage root, the fence, the scan and the outbound guard (the template's vendored copies), the
claim check, `today`, and the retrieval floor (uncalibrated: set it from the template's own gold set). One writer at a
time: every write takes an exclusive lock on `wiki/.lock` (POSIX `flock`). Retrieval is linear in the corpus: meant for
a few hundred pages and sources; above that, replace `retrieve` in an adapter with the template's own index. Stdlib
only.
"""
from __future__ import annotations

import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import secrets
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

__version__ = "1.0.0"

KINDS = ("source", "entity", "concept", "comparison", "overview", "synthesis", "derived")
PLAN_KINDS = ("entity", "concept", "comparison", "overview", "synthesis")
LOG_KINDS = ("ingest", "query", "lint", "resolve", "retire")
STATES = ("current", "contested", "superseded", "withdrawn")
LIVE = ("current", "contested")
GROUPS = (("overview", "Overview"), ("entity", "Entities"), ("concept", "Concepts"), ("comparison", "Comparisons"),
          ("synthesis", "Syntheses"), ("derived", "Answers filed back"), ("source", "Sources"))

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
QUOTE_MIN = 12
QUOTE_MAX = 400
TEXT_MAX = 600
TITLE_MAX = 160
SUMMARY_MAX = 300
FLOOR = 0.6
PREFIX = 6
QUOTES = {"\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "`": "'", "\u201c": '"', "\u201d": '"',
          "\u201e": '"', "\u201f": '"', "\u00ab": '"', "\u00bb": '"', "\u2010": "-", "\u2011": "-", "\u2012": "-",
          "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-"}
MARKS = frozenset("*_#|\\")  # Markdown emphasis, heading and table marks and escapes: dropped on both sides
COMPARATORS = frozenset("<>=~\u2264\u2265")
STOP = frozenset("the and for with that this from what which when where who how are was were has have had not but "
                 "its into about does did can could would should there their they them than then also only "
                 "что как это для или при его она они был была было были где кто чем так все".split())
PLAN_KEYS = {"source", "summary", "pages"}
PAGE_KEYS = {"slug", "title", "kind", "summary", "claims", "links"}
CLAIM_KEYS = {"key", "text", "quote"}
ANSWER_KEYS = {"text", "cites", "quote"}


class WikiError(ValueError):
    """A refused call: `code` is stable, the message names what to fix."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


# ---------------------------------------------------------------------------------------------- text helpers

def _date_ok(value) -> bool:
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _quote_line(text: str) -> str:
    """A source slice as it is stored and shown: one line (line and paragraph separators and newlines become spaces);
    the lint compares it with the source after the same normalisation, so nothing is lost for the check."""
    return re.sub(r"\s+", " ", text).strip()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _norm(text: str):
    """NFKC, case-fold, quotes and dashes unified, whitespace collapsed; returns the text and, per character, the index
    of the original character it came from (so a span found in the normal form maps back to the source)."""
    out, idx, space = [], [], True
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch).casefold():
            c = QUOTES.get(c, c)
            if c in MARKS:
                continue
            if c.isspace() or unicodedata.category(c) == "Cc":
                if space:
                    continue
                c, space = " ", True
            else:
                space = False
            out.append(c)
            idx.append(i)
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def normal(text: str) -> str:
    return _norm(text)[0]


def _cut(t: str, pos: int, end: int) -> bool:
    """True when the match at t[pos:end] is cut out of a longer number or out of a comparison."""
    before, after = t[pos - 1] if pos else "", t[end] if end < len(t) else ""
    if t[pos].isdigit():
        if before.isdigit() or (before in ".," and pos >= 2 and t[pos - 2].isdigit()):
            return True
        lead = t[max(0, pos - 3):pos].strip()
        if lead and lead[-1] in COMPARATORS:
            return True
    if t[end - 1].isdigit() and (after.isdigit() or (after in ".," and end + 1 < len(t) and t[end + 1].isdigit())):
        return True
    return False


def locate(quote: str, text: str) -> Optional[tuple]:
    """The span (start, end) of `quote` in `text` after normalisation on both sides, or None. A match cut out of a
    longer number ("200 ms" of "10,200 ms") or out of a comparison ("100" of "<= 100") does not count."""
    q = normal(quote)
    if not q:
        return None
    t, idx = _norm(text)
    pos = t.find(q)
    while pos >= 0:
        if not _cut(t, pos, pos + len(q)):
            return idx[pos], idx[pos + len(q) - 1] + 1
        pos = t.find(q, pos + 1)
    return None


def numbers(text: str) -> set:
    """The numbers a text states, separators dropped ("18,400" and "18400" are one number)."""
    return {re.sub(r"[.,]", "", n) for n in re.findall(r"\d+(?:[.,]\d+)*", normal(text))}


def disagree(a: str, b: str) -> bool:
    """Two claims on one key disagree when both state numbers and the numbers differ, or when neither states one and
    the words differ; one with numbers and one without cannot be compared and do not open an item."""
    na, nb = numbers(a), numbers(b)
    if na and nb:
        return na != nb
    if na or nb:
        return False
    return normal(a) != normal(b)


def tokens(text: str) -> set:
    return {w[:PREFIX] for w in re.findall(r"[^\W_]{3,}", normal(text)) if w not in STOP}


def _clean_line(value, limit: int) -> str:
    """One line of text a model proposed: control characters and newlines become spaces, bounded."""
    if not isinstance(value, str):
        raise WikiError("plan_invalid", "a text field is not a string")
    s = "".join(" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c for c in value)
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        raise WikiError("plan_invalid", "an empty text field")
    if len(s) > limit:
        raise WikiError("plan_invalid", f"a text field longer than {limit} characters")
    return s


def _one_line(value, limit: int) -> str:
    """A log line: one line, cut with a marker when longer than `limit` (a log entry is never refused for length)."""
    s = re.sub(r"\s+", " ", "".join(" " if unicodedata.category(c)[0] in "CZ" else c for c in str(value))).strip()
    return s if len(s) <= limit else s[:limit - 3] + "..."


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------------------------- pages

def dump_page(page: dict) -> str:
    """Frontmatter (one `key: <JSON>` line per field, valid YAML) then the body rendered from it."""
    head = "".join(f"{k}: {json.dumps(page[k], ensure_ascii=False, sort_keys=True)}\n" for k in sorted(page))
    return f"---\n{head}---\n{render_body(page)}"


def parse_page(text: str) -> dict:
    if not text.startswith("---\n"):
        raise WikiError("page_unreadable", "no frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise WikiError("page_unreadable", "frontmatter not closed")
    page = {}
    for line in text[4:end].split("\n"):
        k, sep, v = line.partition(": ")
        if not sep:
            raise WikiError("page_unreadable", f"frontmatter line without a value: {k[:40]}")
        try:
            page[k] = json.loads(v)
        except json.JSONDecodeError:
            raise WikiError("page_unreadable", f"frontmatter field {k[:40]} is not JSON") from None
    for k in ("page", "title", "kind", "summary"):
        if not isinstance(page.get(k), str):
            raise WikiError("page_unreadable", f"frontmatter lacks {k}")
    if page["kind"] not in KINDS or not isinstance(page.get("claims", []), list):
        raise WikiError("page_unreadable", "kind or claims malformed")
    page["_body"] = text[end + 5:]
    return page


def render_body(page: dict) -> str:
    lines = [f"# {page['title']}", "", page["summary"], ""]
    if page["kind"] == "derived":
        lines += [f"Question: {page.get('question', '')}", ""]
    claims = page.get("claims") or []
    if claims:
        lines += ["## Claims", ""]
        for c in claims:
            mark = "" if c["state"] == "current" else f" ({c['state']})"
            lines.append(f"- {c['text']}{mark} (quote: \"{c['quote']}\"; [[source-{c['source']}]] chars "
                         f"{c['span'][0]}-{c['span'][1]}, sha256 {c['sha256'][:12]})")
        lines.append("")
    if page.get("links"):
        lines += ["## Links", ""] + [f"- [[{s}]]" for s in page["links"]] + [""]
    return "\n".join(lines)


def confidence(page: dict) -> str:
    """Computed by rule, never set by a model."""
    if page["kind"] == "derived":
        return "derived"
    claims = page.get("claims") or []
    if any(c["state"] == "contested" for c in claims):
        return "contested"
    current = {c["source"] for c in claims if c["state"] == "current"}  # withdrawn and superseded never count
    return "corroborated" if len(current) >= 2 else "single-source" if current else "none"


def _sources_of(page: dict) -> list:
    out = {}
    for c in page.get("claims") or []:
        s = out.setdefault(c["source"], {"id": c["source"], "sha256": c["sha256"], "spans": []})
        s["spans"].append(list(c["span"]))
    return [out[k] for k in sorted(out)]


def _claim_id(slug: str, key: str, source: str, text: str) -> str:
    return "c-" + sha256_text(f"{slug}|{key}|{source}|{normal(text)}")[:12]


# ---------------------------------------------------------------------------------------------- results

@dataclass
class IngestResult:
    source: str
    written: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    opened: list = field(default_factory=list)
    repeat: bool = False


@dataclass
class Finding:
    kind: str
    page: str
    detail: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "page": self.page, "detail": self.detail}


@dataclass
class LintReport:
    findings: list

    @property
    def counts(self) -> dict:
        out = {}
        for f in self.findings:
            out[f.kind] = out.get(f.kind, 0) + 1
        return dict(sorted(out.items()))


# ---------------------------------------------------------------------------------------------- the wiki

# ---------------------------------------------------------------------------------------------- the wiki

def _verdict(reading) -> str:
    v = getattr(reading, "verdict", reading)
    return v if isinstance(v, str) else "unknown"


class Wiki:
    """One wiki under `root`: `raw/` (immutable sources), `wiki/` (pages, index.md, log.md, open.json).

    Injected: `fence(text, label)` returns the fenced text (a `str`, or an object whose `str()` is the prompt, as
    `untrusted_fence.fence` returns); `scan(text)` returns a verdict (`clean`, `suspicious`, `injection`, or an object
    with `.verdict`, as `untrusted_fence.scan` returns); `claim_check(claim_text, quote)` returns a reason to reject or
    None (a stricter checker such as research `code/quotes.py`). `today` fixes the date (tests); by default every write
    takes the day it runs."""

    def __init__(self, root, *, fence: Optional[Callable] = None, scan: Optional[Callable] = None,
                 claim_check: Optional[Callable[[str, str], Optional[str]]] = None, today: Optional[str] = None):
        self.root = Path(root)
        self.raw = self.root / "raw"
        self.dir = self.root / "wiki"
        self.fence, self.scan, self.claim_check = fence, scan, claim_check
        if today is not None and not _date_ok(today):
            raise WikiError("bad_date", today)
        self._today = today
        self._depth = 0
        self._lock_fh = None
        self.unreadable = {}
        self.unreadable_sources = []

    @property
    def today(self) -> str:
        return self._today or datetime.date.today().isoformat()

    @contextlib.contextmanager
    def _locked(self):
        """One writer at a time across processes: an exclusive `flock` on wiki/.lock, re-entrant in this object."""
        if self._depth == 0:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._lock_fh = open(self.dir / ".lock", "a+")
            fcntl.flock(self._lock_fh, fcntl.LOCK_EX)
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
            if self._depth == 0:
                fcntl.flock(self._lock_fh, fcntl.LOCK_UN)
                self._lock_fh.close()
                self._lock_fh = None

    # -- sources

    def add_source(self, sid: str, text: str, *, title: str, date: str) -> dict:
        """Store a raw source once. The same id with the same text is a repeat (the first title and date stay); with
        other text it is refused."""
        if not ID_RE.match(sid or ""):
            raise WikiError("bad_id", repr(sid))
        if not _date_ok(date):
            raise WikiError("bad_date", repr(date))
        if not isinstance(text, str) or not text.strip():
            raise WikiError("empty_source", sid)
        digest = sha256_text(text)
        meta_path = self.raw / f"{sid}.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta["sha256"] != digest:
                raise WikiError("source_immutable", f"{sid} is stored with other text; add the new version as a new id")
            return dict(meta, repeat=True)
        meta = {"id": sid, "title": _clean_line(title, TITLE_MAX), "date": date, "sha256": digest,
                "added": self.today, "chars": len(text)}
        if self.scan is not None:
            meta["scan"] = _verdict(self.scan(text))
        _atomic_write(self.raw / f"{sid}.txt", text)
        _atomic_write(meta_path, json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
        return dict(meta, repeat=False)

    def source(self, sid: str) -> dict:
        p = self.raw / f"{sid}.json"
        if not ID_RE.match(sid or "") or not p.exists():
            raise WikiError("unknown_source", repr(sid))
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise WikiError("source_unreadable", sid) from None
        if not isinstance(meta, dict) or meta.get("id") != sid or not isinstance(meta.get("sha256"), str):
            raise WikiError("source_unreadable", sid)
        return meta

    def source_text(self, sid: str) -> str:
        """The source's text, only while its bytes still match the recorded hash."""
        meta = self.source(sid)
        p = self.raw / f"{sid}.txt"
        if not p.exists():
            raise WikiError("source_missing", sid)
        text = p.read_text(encoding="utf-8")
        if sha256_text(text) != meta["sha256"]:
            raise WikiError("source_changed", f"{sid} no longer matches its recorded hash")
        return text

    def sources(self) -> list:
        """Every readable source's record; one that cannot be read is kept in `self.unreadable_sources`."""
        out, self.unreadable_sources = [], []
        for p in sorted(self.raw.glob("*.json")) if self.raw.is_dir() else []:
            try:
                out.append(self.source(p.stem))
            except WikiError:
                self.unreadable_sources.append(p.stem)
        return out

    def _usable(self, meta: dict) -> Optional[str]:
        """Why a source may not reach a model or a page, or None."""
        if meta.get("retired"):
            return "source_retired"
        if meta.get("scan") == "injection":
            return "source_held"
        return None

    def _fenced(self, text: str, label: str) -> str:
        if self.fence is None:
            raise WikiError("no_fence", "source text reaches a model only through a fence (patterns/untrusted-fence)")
        return str(self.fence(text, label))

    def ingest_material(self, sid: str) -> dict:
        """What the model reads to write its plan: the fenced source and the fenced current index."""
        why = self._usable(self.source(sid))
        if why:
            raise WikiError(why, sid)
        return {"source": sid, "text": self._fenced(self.source_text(sid), f"source {sid}"),
                "index": self._fenced(self.read_index(), "wiki index")}

    def retire_source(self, sid: str, reason: str, by: str) -> dict:
        """Withdraw a source: its claims become `withdrawn` with the reason, never deleted; it reaches no model again.
        Erasing its bytes (a privacy request) is the template's procedure: retire first, then remove the raw file and
        rewrite Git history under the template's own rule; the lint then names nothing, since only live claims cite."""
        reason, by = _clean_line(reason, SUMMARY_MAX), _clean_line(by, 80)
        with self._locked():
            meta = self.source(sid)
            if meta.get("retired"):
                raise WikiError("source_retired", sid)
            meta["retired"] = {"date": self.today, "reason": reason, "by": by}
            touched = []
            for slug, page in self.pages().items():
                hit = False
                for c in page.get("claims") or []:
                    if c["source"] == sid and c["state"] != "withdrawn":
                        c["state"], c["withdrawn"], hit = "withdrawn", {"reason": reason, "date": self.today}, True
                if hit:
                    page["updated"] = self.today
                    self._write_page(page)
                    touched.append(slug)
            _atomic_write(self.raw / f"{sid}.json", json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
            items, closed = self.open_items(), []
            pages = self.pages()
            for item in items:
                if item["status"] != "open" or item["page"] not in pages:
                    continue
                claims = {c["id"]: c for c in pages[item["page"]]["claims"]}
                live = [c for c in item["claims"] if (claims.get(c) or {}).get("state") in LIVE]
                if len(live) <= 1:
                    item.update(status="withdrawn", decision={"reason": f"source {sid} retired: {reason}", "by": by,
                                                               "date": self.today, "keep": live[0] if live else None})
                    closed.append(item)
            if closed:
                self._save_open(items)
                for item in closed:
                    page = self.page(item["page"])
                    for c in page["claims"]:
                        if c["id"] == item["decision"]["keep"] and c["state"] == "contested" and not any(
                                c["id"] in i["claims"] for i in items if i["status"] == "open"):
                            c["state"] = "current"
                    self._write_page(page)
            self.write_index()
            self._append_log("retire", meta["title"], [f"source: {sid}", f"pages: {', '.join(touched) or 'none'}",
                                                       f"by: {by}", f"reason: {reason}"])
            return meta

    # -- pages

    def page_path(self, slug: str) -> Path:
        if not isinstance(slug, str) or not SLUG_RE.match(slug) or slug in ("index", "log"):
            raise WikiError("bad_slug", repr(slug))
        return self.dir / f"{slug}.md"

    def page(self, slug: str) -> Optional[dict]:
        p = self.page_path(slug)
        return parse_page(p.read_text(encoding="utf-8")) if p.exists() else None

    def pages(self) -> dict:
        """Every readable page; an unreadable one is kept in `self.unreadable` (slug: reason) for the lint."""
        out, self.unreadable = {}, {}
        for p in sorted(self.dir.glob("*.md")) if self.dir.is_dir() else []:
            if p.stem in ("index", "log"):
                continue
            try:
                out[p.stem] = parse_page(p.read_text(encoding="utf-8"))
            except (WikiError, UnicodeDecodeError) as e:
                self.unreadable[p.stem] = str(e)
        return out

    def _write_page(self, page: dict) -> None:
        page = {k: v for k, v in page.items() if not k.startswith("_")}
        page["sources"] = _sources_of(page)
        page["confidence"] = confidence(page)
        _atomic_write(self.page_path(page["page"]), dump_page(page))

    # -- open items

    def open_items(self) -> list:
        p = self.dir / "open.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []

    def _save_open(self, items: list) -> None:
        _atomic_write(self.dir / "open.json", json.dumps(items, ensure_ascii=False, sort_keys=True, indent=1) + "\n")

    # -- ingest

    def check_plan(self, plan: dict) -> tuple:
        """Validate the plan's shape (closed keys) and every claim against its source. Returns (pages, rejected):
        pages carry only claims that passed, each with its span; rejected names every claim left out and why."""
        if not isinstance(plan, dict) or set(plan) - PLAN_KEYS or not {"source", "pages"} <= set(plan):
            raise WikiError("plan_invalid", f"plan keys must be {sorted(PLAN_KEYS)}")
        sid = plan["source"]
        why = self._usable(self.source(sid))
        if why:
            raise WikiError(why, sid)
        text = self.source_text(sid)
        if not isinstance(plan["pages"], list) or not plan["pages"]:
            raise WikiError("plan_invalid", "pages must be a non-empty list")
        out, rejected, seen = [], [], set()
        for pg in plan["pages"]:
            if not isinstance(pg, dict) or set(pg) - PAGE_KEYS or not {"slug", "title", "kind"} <= set(pg):
                raise WikiError("plan_invalid", f"page keys must be {sorted(PAGE_KEYS)}")
            slug = pg["slug"]
            self.page_path(slug)
            if slug.startswith(("source-", "answer-")) or slug in seen:
                raise WikiError("plan_invalid", f"page {slug}: reserved or repeated")
            seen.add(slug)
            if pg["kind"] not in PLAN_KINDS:
                raise WikiError("plan_invalid", f"page {slug}: kind must be one of {PLAN_KINDS}")
            links = pg.get("links") or []
            if not isinstance(links, list):
                raise WikiError("plan_invalid", f"page {slug}: links must be a list")
            for s in links:
                self.page_path(s)
            claims = []
            for c in pg.get("claims") or []:
                if not isinstance(c, dict) or set(c) != CLAIM_KEYS:
                    raise WikiError("plan_invalid", f"page {slug}: claim keys must be {sorted(CLAIM_KEYS)}")
                if not KEY_RE.match(c["key"] if isinstance(c["key"], str) else ""):
                    raise WikiError("plan_invalid", f"page {slug}: bad claim key {c['key']!r}")
                ctext = _clean_line(c["text"], TEXT_MAX)
                quote = c["quote"] if isinstance(c["quote"], str) else ""
                size = len(normal(quote))
                span = locate(quote, text) if QUOTE_MIN <= size <= QUOTE_MAX else None
                if span is None:
                    reason = "quote_too_short" if size < QUOTE_MIN else "quote_too_long" if size > QUOTE_MAX \
                        else "quote_not_found"
                    rejected.append({"page": slug, "key": c["key"], "reason": reason})
                    continue
                extra = numbers(ctext) - numbers(quote)
                if extra:
                    rejected.append({"page": slug, "key": c["key"], "reason": "number_not_in_quote",
                                     "numbers": sorted(extra)})
                    continue
                stricter = self.claim_check(ctext, _quote_line(text[span[0]:span[1]])) if self.claim_check else None
                if stricter:
                    rejected.append({"page": slug, "key": c["key"], "reason": f"claim_check: {stricter}"[:120]})
                    continue
                claims.append({"key": c["key"], "text": ctext, "quote": _quote_line(text[span[0]:span[1]]),
                               "span": list(span)})
            out.append({"slug": slug, "title": _clean_line(pg["title"], TITLE_MAX), "kind": pg["kind"],
                        "summary": _clean_line(pg.get("summary") or pg["title"], SUMMARY_MAX),
                        "links": sorted(set(links) - {slug}), "claims": claims})
        return out, rejected

    def apply_plan(self, plan: dict) -> IngestResult:
        """Write the open items first, then the pages a checked plan names, the source's own page, the index and one
        log entry, all under the writer's lock."""
        with self._locked():
            return self._apply(plan)

    def _apply(self, plan: dict) -> IngestResult:
        pages, rejected = self.check_plan(plan)
        sid = plan["source"]
        meta = self.source(sid)
        result = IngestResult(source=sid, rejected=rejected)
        items = self.open_items()
        staged = []
        for pg in pages:
            old = self.page(pg["slug"])
            page = old or {"page": pg["slug"], "kind": pg["kind"], "claims": [], "links": [], "history": []}
            before = json.dumps({k: v for k, v in page.items() if not k.startswith("_") and k != "updated"},
                                sort_keys=True)
            if old and (old["title"], old["summary"]) != (pg["title"], pg["summary"]):
                page.setdefault("history", []).append({"title": old["title"], "summary": old["summary"],
                                                       "until": self.today, "by_source": sid})
            page.update(title=pg["title"], summary=pg["summary"])
            page["links"] = sorted(set(page.get("links") or []) | set(pg["links"]))
            for c in pg["claims"]:
                cid = _claim_id(pg["slug"], c["key"], sid, c["text"])
                if any(x["id"] == cid for x in page["claims"]):
                    continue
                new = {"id": cid, "key": c["key"], "text": c["text"], "quote": c["quote"], "source": sid,
                       "sha256": meta["sha256"], "span": c["span"], "date": meta["date"], "state": "current"}
                rivals = [x for x in page["claims"] if x["key"] == c["key"] and x["state"] in LIVE
                          and x["source"] != sid and disagree(x["text"], c["text"])]
                if rivals:
                    new["state"] = "contested"
                    for x in rivals:
                        x["state"] = "contested"
                    iid = "ct-" + sha256_text(f"{pg['slug']}|{c['key']}|{cid}")[:12]
                    items.append({"id": iid, "kind": "contradiction", "page": pg["slug"], "key": c["key"],
                                  "claims": sorted([x["id"] for x in rivals] + [cid]), "status": "open",
                                  "opened": self.today})
                    result.opened.append(iid)
                page["claims"].append(new)
            after = json.dumps({k: v for k, v in page.items() if not k.startswith("_") and k != "updated"},
                               sort_keys=True)
            if old is None or before != after:
                page["updated"] = self.today
                staged.append(page)
        src_slug = f"source-{sid}"
        old_src = self.page(src_slug)
        src_page = {"page": src_slug, "kind": "source", "title": meta["title"], "claims": [],
                    "summary": _clean_line(plan.get("summary") or meta["title"], SUMMARY_MAX),
                    "links": sorted(set((old_src or {}).get("links") or []) | {p["slug"] for p in pages}),
                    "source": {"id": sid, "date": meta["date"], "sha256": meta["sha256"]}}
        if old_src is None or {k: old_src.get(k) for k in src_page} != src_page:
            src_page["updated"] = self.today
            staged.append(src_page)
        if result.opened:
            self._save_open(items)  # before the pages: a crash leaves an item, never a contested claim without one
        for page in staged:
            self._write_page(page)
            result.written.append(page["page"])
        if not staged and not rejected:
            result.repeat = True
            return result
        self.write_index()
        self._append_log("ingest", meta["title"], [
            f"source: {sid} ({meta['sha256'][:12]})",
            f"pages written: {', '.join(result.written) or 'none'}",
            f"claims rejected: {len(rejected)}",
            f"contradictions opened: {len(result.opened)}"])
        return result

    def resolve(self, item_id: str, keep: str, reason: str, by: str) -> dict:
        """Close a contradiction: `keep` stays current, the others become `superseded` with the reason. The item stays."""
        reason, by = _clean_line(reason, SUMMARY_MAX), _clean_line(by, 80)
        with self._locked():
            items = self.open_items()
            item = next((i for i in items if i["id"] == item_id), None)
            if item is None:
                raise WikiError("unknown_item", item_id)
            if item["status"] != "open":
                raise WikiError("item_closed", item_id)
            if keep not in item["claims"]:
                raise WikiError("not_in_item", keep)
            page = self.page(item["page"])
            if page is None:
                raise WikiError("unknown_page", item["page"])
            on_page = {c["id"]: c for c in page["claims"]}
            if any(c not in on_page for c in item["claims"]):
                raise WikiError("item_stale", f"{item_id}: a claim of the item is not on {item['page']}")
            if on_page[keep]["state"] == "withdrawn":
                raise WikiError("claim_withdrawn", keep)
            item.update(status="resolved", decision={"keep": keep, "reason": reason, "by": by, "date": self.today})
            self._save_open(items)  # the decision first: a crash leaves the page to rewrite, never an unexplained state
            for c in page["claims"]:
                if c["id"] == keep:
                    c["state"] = "current"
                elif c["id"] in item["claims"] and c["state"] != "withdrawn":
                    c["state"] = "superseded"
                    c["superseded"] = {"by": keep, "reason": reason, "date": self.today}
            page["updated"] = self.today
            self._write_page(page)
            self.write_index()
            self._append_log("resolve", f"{item['page']} {item['key']}",
                             [f"kept: {keep}", f"by: {by}", f"reason: {reason}"])
            return item

    # -- index and log

    def read_index(self) -> str:
        p = self.dir / "index.md"
        return p.read_text(encoding="utf-8") if p.exists() else "# Index\n"

    def write_index(self) -> str:
        pages = self.pages()
        lines = ["# Index", "", "Generated by code on every write; never edited by hand.", ""]
        for kind, heading in GROUPS:
            rows = [p for p in pages.values() if p["kind"] == kind]
            if not rows:
                continue
            lines += [f"## {heading}", ""]
            for p in sorted(rows, key=lambda r: r["page"]):
                lines.append(f"- [[{p['page']}]] {p['title']}: {p['summary']} ({p.get('confidence', 'none')}, "
                             f"sources {len(p.get('sources') or [])}, updated {p.get('updated', '')})")
            lines.append("")
        text = "\n".join(lines)
        _atomic_write(self.dir / "index.md", text)
        return text

    def append_log(self, kind: str, title: str, lines: Iterable[str] = ()) -> None:
        with self._locked():
            self._append_log(kind, title, lines)

    def _append_log(self, kind: str, title: str, lines: Iterable[str] = ()) -> None:
        if kind not in LOG_KINDS:
            raise WikiError("bad_log_kind", kind)
        path, state_path = self.dir / "log.md", self.dir / ".log.json"
        current = path.read_text(encoding="utf-8") if path.exists() else "# Log\n"
        problem = self._log_problem(current)
        if problem:
            raise WikiError("log_rewritten", problem)
        entry = f"\n## [{self.today}] {kind} | {_one_line(title, TITLE_MAX)}\n" + \
                "".join(f"- {_one_line(x, TEXT_MAX)}\n" for x in lines)
        text = current + entry
        _atomic_write(path, text)
        raw = text.encode("utf-8")
        _atomic_write(state_path, json.dumps({"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}) + "\n")

    def _log_problem(self, current: str) -> str:
        """The log's own check. It catches an edit of log.md alone; an edit of the log and its state together is
        caught only by the wiki's Git history, which is the real defence against tampering."""
        state_path = self.dir / ".log.json"
        if not state_path.exists():
            return ""
        state = json.loads(state_path.read_text(encoding="utf-8"))
        raw = current.encode("utf-8")
        if len(raw) < state["bytes"] or hashlib.sha256(raw[:state["bytes"]]).hexdigest() != state["sha256"]:
            return "log.md no longer starts with what was written; restore it from history"
        return ""

    # -- lint

    def lint(self, *, record: bool = True) -> LintReport:
        """Every finding over the whole wiki; `record` appends one lint entry to the log under the writer's lock."""
        if record and self.dir.is_dir():
            with self._locked():
                return self._lint(True)
        return self._lint(False)

    def _lint(self, record: bool) -> LintReport:
        pages = self.pages()
        findings = [Finding("page_unreadable", slug, why) for slug, why in self.unreadable.items()]
        metas = {m["id"]: m for m in self.sources()}
        findings += [Finding("source_unreadable", f"source-{sid}", "its record cannot be read")
                     for sid in self.unreadable_sources]
        now_hash, texts = {}, {}
        for sid in metas:
            f = self.raw / f"{sid}.txt"
            texts[sid] = f.read_text(encoding="utf-8") if f.exists() else None
            now_hash[sid] = sha256_text(texts[sid]) if texts[sid] is not None else None
        claims_by_id = {c["id"]: (slug, c) for slug, p in pages.items() for c in p.get("claims") or []}
        items = self.open_items()
        in_open = {c for i in items if i["status"] == "open" for c in i["claims"]}
        superseded_ok = {c for i in items if i["status"] == "resolved" for c in i["claims"]
                         if c != (i.get("decision") or {}).get("keep")}
        for item in items:
            if item["status"] != "open":
                continue
            rows = sorted((claims_by_id[c][1] for c in item["claims"] if c in claims_by_id), key=lambda c: c["date"])
            if len(rows) >= 2 and rows[0]["date"] < rows[-1]["date"]:
                findings.append(Finding("stale", item["page"], f"{item['id']}: claim {rows[0]['id']} "
                                        f"({rows[0]['date']}) disagrees with newer {rows[-1]['id']} ({rows[-1]['date']})"))
            else:
                findings.append(Finding("contradiction", item["page"], f"{item['id']}: key {item['key']} open"))
        inbound = {slug: 0 for slug in pages}
        titles = {slug: p["title"] for slug, p in pages.items() if p["kind"] != "source" and len(p["title"]) >= 4}
        for slug, p in pages.items():
            if render_body(p) != p["_body"] or p.get("confidence") != confidence(p):
                findings.append(Finding("hand_edited", slug, "the page differs from what code writes; write through code"))
            for s in p.get("links") or []:
                if s in inbound:
                    if s != slug and p["kind"] != "source":  # a source page links all it touched: not a reader's path
                        inbound[s] += 1
                elif s not in self.unreadable:
                    findings.append(Finding("missing_page", slug, f"links to [[{s}]], which has no page"))
            text = " ".join(c["text"] for c in p.get("claims") or [] if c["state"] in LIVE)
            for other, title in titles.items():
                if other != slug and other not in (p.get("links") or []) and \
                        re.search(r"(?<!\w)" + re.escape(normal(title)) + r"(?!\w)", normal(text)):
                    findings.append(Finding("missing_link", slug, f"mentions {title!r} without [[{other}]]"))
            for c in p.get("claims") or []:
                if c["state"] == "withdrawn":
                    if not (metas.get(c["source"]) or {}).get("retired"):
                        findings.append(Finding("state_unexplained", slug, f"{c['id']} withdrawn, its source is not"))
                    continue
                if (metas.get(c["source"]) or {}).get("retired"):
                    findings.append(Finding("state_unexplained", slug, f"{c['id']} {c['state']}, its source is retired"))
                if c["state"] == "contested" and c["id"] not in in_open:
                    findings.append(Finding("item_missing", slug, f"{c['id']} contested with no open item"))
                if c["state"] == "superseded" and c["id"] not in superseded_ok:
                    findings.append(Finding("state_unexplained", slug, f"{c['id']} superseded with no resolved item"))
                if c["state"] == "current" and c["id"] in superseded_ok:
                    findings.append(Finding("state_unexplained", slug, f"{c['id']} current, but a resolution superseded it"))
                sid = c["source"]
                if sid not in metas or texts.get(sid) is None:
                    findings.append(Finding("source_missing", slug, f"{c['id']} cites {sid}, which is not stored"))
                    continue
                if now_hash[sid] != c["sha256"]:
                    findings.append(Finding("source_changed", slug, f"{c['id']} cites {sid} at {c['sha256'][:12]}, "
                                            f"now {now_hash[sid][:12]}"))
                    continue
                a, b = c["span"]
                if normal(texts[sid][a:b]) != normal(c["quote"]) or numbers(c["text"]) - numbers(c["quote"]):
                    findings.append(Finding("unverified_claim", slug, f"{c['id']}: quote not at its span, or a number "
                                            "the quote lacks"))
        cited = {c["source"] for p in pages.values() for c in p.get("claims") or [] if c["state"] != "withdrawn"}
        for sid, meta in metas.items():  # a stored source no live claim cites is still checked against its bytes
            if sid in cited or meta.get("retired"):
                continue
            if texts.get(sid) is None:
                findings.append(Finding("source_missing", f"source-{sid}", "its raw file is gone"))
            elif now_hash[sid] != meta["sha256"]:
                findings.append(Finding("source_changed", f"source-{sid}", f"recorded {meta['sha256'][:12]}, "
                                        f"now {now_hash[sid][:12]}"))
        for slug, n in inbound.items():
            if n == 0 and pages[slug]["kind"] not in ("source", "overview", "derived"):
                findings.append(Finding("orphan", slug, "no page links here"))
        problem = self._log_problem((self.dir / "log.md").read_text(encoding="utf-8")) \
            if (self.dir / "log.md").exists() else ""
        if problem:
            findings.append(Finding("log_rewritten", "log", problem))
        findings.sort(key=lambda f: (f.kind, f.page, f.detail))
        report = LintReport(findings)
        if record and not problem:
            self._append_log("lint", f"{len(findings)} findings",
                             [f"{k}: {v}" for k, v in report.counts.items()] or ["clean"])
        return report

    # -- query

    def retrieve(self, question: str, *, floor: float = FLOOR, top: int = 5, raw_windows: int = 5,
                 window: int = 400) -> dict:
        """The map first, the raw spans its pages cite always, and raw-source windows when the map falls short.
        `mode`: wiki, wiki+raw, raw, or empty (nothing found: no answer). A source whose bytes changed, a held or
        retired source and an unreadable page are skipped and named in `degraded`. The floor is a share of the
        question's words (6-letter prefixes), uncalibrated: set it from the template's gold set."""
        q = tokens(question)
        if not q:
            raise WikiError("empty_question")
        degraded, texts = [], {}

        def text_of(sid):
            if sid not in texts:
                try:
                    meta = self.source(sid)
                    why = self._usable(meta) if not meta.get("retired") else "source_retired"
                    texts[sid] = None if why else self.source_text(sid)
                    if why:
                        degraded.append(f"{why}: {sid}")
                except WikiError as e:
                    texts[sid] = None
                    degraded.append(f"{e.code}: {sid}")
            return texts[sid]

        scored = []
        for slug, p in self.pages().items():
            if p["kind"] == "source":
                continue
            live = [c for c in p.get("claims") or [] if c["state"] in LIVE]
            words = tokens(" ".join([p["title"], p["summary"]] + [c["text"] for c in live]))
            cov = len(q & words) / len(q)
            if cov > 0:
                scored.append((cov, slug, p, live))
        degraded += [f"page_unreadable: {s}" for s in sorted(self.unreadable)]
        scored.sort(key=lambda r: (-r[0], r[1]))
        scored = scored[:top]
        best = scored[0][0] if scored else 0.0
        items, seen_spans = [], []
        for cov, slug, p, live in scored:
            for c in live:
                text = text_of(c["source"])
                if text is None:
                    continue
                a, b = c["span"]
                lo, hi = max(0, a - window // 2), min(len(text), b + window // 2)
                items.append({"ref": c["id"], "page": slug, "coverage": round(cov, 3), "claim": c["text"],
                              "state": c["state"], "source": c["source"], "span": [a, b], "sha256": c["sha256"],
                              "excerpt_span": [lo, hi], "excerpt": text[lo:hi]})
                seen_spans.append((c["source"], lo, hi))
        mode = "wiki"
        if best < floor:
            mode = "wiki+raw" if scored else "raw"
            cand = []
            metas = self.sources()
            degraded += [f"source_unreadable: {sid}" for sid in self.unreadable_sources]
            for meta in metas:
                text = text_of(meta["id"])
                if text is None:
                    continue
                step = max(1, window // 2)
                for lo in range(0, max(1, len(text) - step), step):
                    hi = min(len(text), lo + window)
                    inside = any(s == meta["id"] and a <= lo and hi <= b for s, a, b in seen_spans)
                    cov = len(q & tokens(text[lo:hi])) / len(q)
                    if cov > 0 and not inside:
                        cand.append((cov, meta["id"], lo, hi, meta["sha256"], text[lo:hi]))
            cand.sort(key=lambda r: (-r[0], r[1], r[2]))
            for cov, sid, lo, hi, digest, excerpt in cand[:raw_windows]:
                items.append({"ref": f"{sid}:{lo}-{hi}", "page": None, "coverage": round(cov, 3), "source": sid,
                              "state": None, "span": [lo, hi], "sha256": digest, "excerpt_span": [lo, hi],
                              "excerpt": excerpt})
        if not items:
            mode = "empty"
        return {"question": question, "mode": mode, "best_page_coverage": round(best, 3), "floor": floor,
                "items": items, "degraded": sorted(set(degraded))}

    def material(self, retrieval: dict) -> str:
        """The retrieval as a model reads it: each item (a page's claim, a model's own earlier words, and the raw
        excerpt) inside its own fence; only the refs and spans are outside."""
        parts = [f"Mode: {retrieval['mode']}", self._fenced(retrieval["question"], "question")]
        for it in retrieval["items"]:
            parts.append(f"[{it['ref']}] source {it['source']} chars {it['excerpt_span'][0]}-{it['excerpt_span'][1]}")
            body = it["excerpt"] if not it.get("claim") else \
                f"page {it['page']} claim ({it['state']}): {it['claim']}\n\n{it['excerpt']}"
            parts.append(self._fenced(body, f"item {it['ref']}"))
        return "\n".join(parts)

    def check_answer(self, answer: dict, retrieval: dict) -> dict:
        """Keep the claims whose quote sits in a cited excerpt and whose numbers are in that quote; drop the rest with a
        reason. No claim left means no answer (`answered: false`), never an answer from memory. A kept claim resting on
        a contested page claim says so (`contested: true`). This is the citation gate only: a template with
        `patterns/answer-checker` passes it as one of the checker's code gates."""
        refs = {it["ref"]: it for it in retrieval["items"]}
        if not isinstance(answer, dict) or not isinstance(answer.get("claims"), list):
            raise WikiError("answer_invalid", "answer must be {claims: [...]}")
        kept, dropped = [], []
        for c in answer["claims"]:
            if not isinstance(c, dict) or set(c) - ANSWER_KEYS or not isinstance(c.get("cites"), list):
                raise WikiError("answer_invalid", f"claim keys must be {sorted(ANSWER_KEYS)}")
            text, quote = _clean_line(c.get("text") or "", TEXT_MAX), c.get("quote") or ""
            cites = [r for r in c["cites"] if isinstance(r, str)]
            unknown = [r for r in cites if r not in refs]
            if not cites or unknown:
                dropped.append({"text": text, "reason": "cite_not_retrieved" if unknown else "no_cite"})
                continue
            hit = None
            for r in cites:
                it = refs[r]
                span = locate(quote, it["excerpt"]) if QUOTE_MIN <= len(normal(quote)) <= QUOTE_MAX else None
                if span:
                    off = it["excerpt_span"][0]
                    hit = {"ref": r, "source": it["source"], "sha256": it["sha256"],
                           "span": [off + span[0], off + span[1]], "page": it.get("page"),
                           "contested": it.get("state") == "contested"}
                    break
            if hit is None:
                dropped.append({"text": text, "reason": "quote_not_in_cited"})
                continue
            if numbers(text) - numbers(quote):
                dropped.append({"text": text, "reason": "number_not_in_quote"})
                continue
            stricter = self.claim_check(text, quote) if self.claim_check else None
            if stricter:
                dropped.append({"text": text, "reason": f"claim_check: {stricter}"[:120]})
                continue
            kept.append(dict(hit, text=text, quote=quote))
        return {"question": retrieval["question"], "mode": retrieval["mode"], "answered": bool(kept),
                "claims": kept, "dropped": dropped, "contested": sum(1 for c in kept if c["contested"])}

    def file_answer(self, checked: dict, *, slug: str, title: str) -> dict:
        """File a checked answer back as a `derived` page: its claims keep their raw source spans."""
        if not checked.get("answered"):
            raise WikiError("not_answered", "an answer with no supported claim is not filed")
        if not isinstance(slug, str) or not slug.startswith("answer-"):
            raise WikiError("bad_slug", "a filed answer's slug starts with answer-")
        with self._locked():
            if self.page_path(slug).exists():
                raise WikiError("page_exists", slug)
            claims = []
            for i, c in enumerate(checked["claims"]):
                meta = self.source(c["source"])
                if meta["sha256"] != c["sha256"]:
                    raise WikiError("source_changed", c["source"])
                text = self.source_text(c["source"])
                a, b = c["span"]
                claims.append({"id": _claim_id(slug, f"a{i}", c["source"], c["text"]), "key": f"a{i}",
                               "text": c["text"], "quote": _quote_line(text[a:b]), "source": c["source"],
                               "sha256": c["sha256"],
                               "span": [a, b], "date": meta["date"], "state": "current"})
            page = {"page": slug, "kind": "derived", "title": _clean_line(title, TITLE_MAX),
                    "summary": _clean_line(checked["question"], SUMMARY_MAX), "question": checked["question"],
                    "claims": claims, "links": sorted({c["page"] for c in checked["claims"] if c.get("page")}),
                    "derived_from": sorted({c["ref"] for c in checked["claims"]}), "updated": self.today}
            self._write_page(page)
            self.write_index()
            self._append_log("query", f"{page['title']} (filed back)",
                             [f"page: {slug}", f"mode: {checked['mode']}", f"claims: {len(claims)}"])
            return self.page(slug)

    # -- leaving the room

    def export_page(self, slug: str, outbound: Callable[[str], str]) -> str:
        """A page as text that may leave, through the caller's outbound guard (patterns/privacy-filter); the guard's
        own length limit applies (pass `lambda t: f.guard_outbound(t, limit=...)` for long pages)."""
        if not callable(outbound):
            raise WikiError("no_outbound_guard", "a page leaves only through an outbound guard")
        page = self.page(slug)
        if page is None:
            raise WikiError("unknown_page", slug)
        return outbound(page["_body"])

    def export_answer(self, checked: dict, outbound: Callable[[str], str]) -> str:
        if not callable(outbound):
            raise WikiError("no_outbound_guard", "an answer leaves only through an outbound guard")
        if not checked.get("answered"):
            return outbound("No answer: the sources read do not support one.")
        lines = [f"- {c['text']}{' (contested)' if c.get('contested') else ''} (quote: \"{c['quote']}\"; {c['source']} "
                 f"chars {c['span'][0]}-{c['span'][1]})" for c in checked["claims"]]
        return outbound("\n".join(lines))
