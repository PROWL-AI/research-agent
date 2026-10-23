"""Values a later step needs that only an earlier step returns (B-065).

The plan is written once, before any tool runs, so an argument that depends on
a result (an app's numeric store id, a package name found by a search) cannot
be written literally. The planner writes it as a placeholder, ``{{name}}``, and
puts a transform before the step whose instruction says where the value is.
That transform ends its note with a fenced ``bindings`` block; a value is kept
only when it appears verbatim in a raw artifact of the run, so a model cannot
invent an id. Before dispatch the step's arguments are filled; a placeholder
nobody resolved is never sent (the provider would refuse it and bill the call).
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

#: Any ``{{...}}`` the planner wrote, valid name or not: an invalid one is an
#: unresolved placeholder too, never text to send to a provider.
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_BLOCK_RE = re.compile(r"```bindings\s*\n(.*?)\n?```", re.DOTALL)
#: A value shorter than this matches too much text to prove anything.
_MIN_GROUNDED_LEN = 3
#: Template text the planner wrote in another shape than ``{{name}}`` (B-070). The
#: planner is told never to, and live runs show it still does; each shape below was
#: sent to a provider, refused and billed:
_TEMPLATE_RES = (
    # "[substitute landing_page_url of the longest-running ... ad]" (accept-teardown-20261021b): the
    # verb opens an instruction of three words or more, so "how to [insert] a row" or "[Substitute
    # Teacher] movie" is a value; a CSS "[placeholder='Email']" is a value too.
    re.compile(r"\[\s*(?:substitute|insert|replace|fill in)\s+\S+(?:\s+\S+){2,30}\s*\]", re.I),
    re.compile(r"\[\s*placeholder\s[^\]=]{1,200}\]", re.I),
    # "PLACEHOLDER_FROM_STEP_22" (accept-finance-20261020c)
    re.compile(r"\bPLACEHOLDER(?:_[A-Z0-9]+)*\b"),
)
#: Shapes that are template text only when they are the whole argument: inside prose (a prompt
#: to an LLM-backed tool: "Extract {company.name}", "as <plan name from the table>") they are text.
_WHOLE_TEMPLATE_RES = (
    # "<video_id from youtube_search result ...>", "<... report URL from search or IR map>"
    # (accept-finance-20261020). Runs are bounded: an unbounded one is quadratic on a long argument.
    re.compile(r"<[A-Za-z_][^<>]{0,200}?\s(?:from|placeholder)\s[^<>]{0,200}>", re.I),
    # "{youtube_search.latest_official_call_video_id}" (accept-finance-20261021)
    re.compile(r"\{\s*[A-Za-z_]\w{0,63}(?:\.\w{1,64}|\[\d{1,4}\]){1,8}\s*\}"),
)


#: ``{{output:<step>}}`` hands a whole earlier result to a later step (B-074): the
#: stored raw artifact of the last completed step of that name, cut at this many
#: characters. An LLM-analysis tool needs the page, not a description of it.
OUTPUT_CAP = 16_000
_OUTPUT_RE = re.compile(r"^output:([a-z][a-z0-9_]{0,63})$")


def slug(step: str) -> str:
    """A step name as an ``{{output:...}}`` reference writes it: "Scrape page!" -> "scrape_page"."""
    return re.sub(r"[^a-z0-9]+", "_", step.lower()).strip("_")[:64]


def output_refs(value: Any) -> set[str]:
    """The step names a value's ``{{output:<step>}}`` placeholders refer to."""
    return {m.group(1) for name in placeholders(value) if (m := _OUTPUT_RE.match(name))}


def output_text(text: str, cap: int = OUTPUT_CAP) -> str:
    """An earlier step's raw artifact as sent: whole, or cut with the count it left out."""
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n[cut: {len(text) - cap} more characters]"


def placeholders(value: Any) -> set[str]:
    """Every placeholder name inside a JSON-like value (strings only)."""
    found: set[str] = set()
    if isinstance(value, str):
        found.update(m.group(1) for m in _PLACEHOLDER_RE.finditer(value))
    elif isinstance(value, dict):
        for item in value.values():
            found |= placeholders(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            found |= placeholders(item)
    return found


def template_text(value: Any) -> list[str]:
    """Each piece of template text (not a ``{{name}}``) inside a JSON-like value,
    in order; such an argument is never sent (B-070)."""
    found: list[str] = []
    if isinstance(value, str):
        for pattern in _TEMPLATE_RES:
            found.extend(m.group(0) for m in pattern.finditer(value))
        whole = value.strip()
        if len(whole) <= 512 and any(p.fullmatch(whole) for p in _WHOLE_TEMPLATE_RES):
            found.append(whole)
    elif isinstance(value, dict):
        for item in value.values():
            found.extend(template_text(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(template_text(item))
    return found


def substitute(value: Any, bindings: dict[str, str]) -> tuple[Any, set[str]]:
    """(value with every bound placeholder filled, the names still missing).

    A string that is exactly one placeholder becomes the bound value; a
    placeholder inside longer text is replaced in place."""
    missing: set[str] = set()

    def fill(item: Any) -> Any:
        if isinstance(item, str):
            whole = _PLACEHOLDER_RE.fullmatch(item.strip())
            if whole and whole.group(1) in bindings:
                return bindings[whole.group(1)]

            def one(m: re.Match[str]) -> str:
                name = m.group(1)
                if name in bindings:
                    return bindings[name]
                missing.add(name)
                return m.group(0)

            return _PLACEHOLDER_RE.sub(one, item)
        if isinstance(item, dict):
            return {k: fill(v) for k, v in item.items()}
        if isinstance(item, list):
            return [fill(v) for v in item]
        return item

    return fill(value), missing


def wanted(steps: Iterable[Any], bound: dict[str, str]) -> list[str]:
    """Names later data steps use that nothing has resolved yet, in plan order."""
    names: list[str] = []
    for record in steps:
        if getattr(record, "kind", "data") != "data":
            continue
        for name in sorted(placeholders(record.arguments)):
            if name not in bound and name not in names and _NAME_RE.match(name):
                names.append(name)
    return names


def parse(note: str) -> dict[str, str]:
    """The last ``bindings`` block of a transform note, scalars only."""
    blocks = _BLOCK_RE.findall(note or "")
    if not blocks:
        return {}
    try:
        data = json.loads(blocks[-1])
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for name, value in data.items():
        if not isinstance(name, str) or not _NAME_RE.match(name):
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        text = str(value).strip()
        if text:
            out[name] = text
    return out


def strip_block(note: str) -> str:
    """The note without its ``bindings`` blocks (the writer reads the prose)."""
    return _BLOCK_RE.sub("", note or "").rstrip()


def grounded(candidates: dict[str, str], names: Iterable[str], texts: Iterable[str]) -> tuple[dict[str, str], dict[str, str]]:
    """(kept, rejected-with-reason): a value is kept when its name was asked
    for and the value appears verbatim in one of the raw artifact texts."""
    asked = set(names)
    corpus = list(texts)
    kept: dict[str, str] = {}
    rejected: dict[str, str] = {}
    for name, value in candidates.items():
        if name not in asked:
            rejected[name] = "not asked for by any later step"
        elif len(value) < _MIN_GROUNDED_LEN:
            rejected[name] = "value too short to check"
        elif not any(value in text for text in corpus):
            rejected[name] = "value not found in any raw artifact"
        else:
            kept[name] = value
    return kept, rejected
