# vendored from patterns/compact-mcp/code/compact_mcp.py@1.2.0
"""Compact MCP surface: two doors, `search` and `execute`; a direct tool only on a measured case. Pattern
`compact-mcp`, version 1.2.0 (patterns/compact-mcp/PATTERN.md).

The operator's rule of 2026-11-18 (R33 O15), as he settled it the same day: an MCP server has two entries, `search`
(which operations exist, each with a one-line purpose, the input schema, the gate and an example) and `execute` (run
one operation by name with its arguments). A direct tool beside them only where a measured case shows a call must
skip search (`earns_direct`: at least 20 calls and 30 % of the server's calls in the window), at most three, each
recorded with its measurement. The fabric-interop contract's job tools (`fabric.job.get`, `fabric.job.cancel`,
`fabric.job.list`), which a protocol outside the server requires by name, take seats of those three without a
measurement, the contract recorded as the reason, until it lets them fold into `execute`. The canon is agent-stack's
`agent-interop/references/mcp-two-doors.md` (0.33.0). Every
operation stays a capability an agent reaches (R33 O8): only its listing moves behind `search`, never its gate,
idempotency or audit.

    surface = CompactSurface([operation("room.cells.get", "P&L cells for a month", schema, handler), ...],
                             domain="room")
    surface.tools()                                   # room.search, room.execute
    surface.call("room.execute", {"operation": "room.health.get", "arguments": {}})
    surface.call("room.health.get", {})               # an old tool name still answers, for one release

Every call, through `execute`, a measured direct tool or an old name, goes through one path (`dispatch`): the input
schema, the gate (`none` runs; `relayed` needs the operator's decision in `meta["decision"]`, else
`operator-decision-required`; `human` answers `human-step-required` with its link), the idempotency key (the same key
and arguments answer the stored result, other arguments under it are `idempotency-conflict`) and one audit record
naming the route it came by.

`choose_direct` names the operations that earn a direct seat from measured call counts (an incumbent keeps its seat
above 80 % of the bar). `UsageCounter` keeps the counts per operation and UTC day. `count_tools` reads a server's
tools from a `tools/list` answer, a Fabric manifest or a `.well-known/fabric-service` document; `check` answers the
findings against the rule. Stdlib only.

    python3 compact_mcp.py check <tools-list-or-manifest.json> [--measured name,name]   # exit 1 on a blocking finding
"""
from __future__ import annotations

import datetime
import difflib
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile
from typing import Any, Callable, Dict, Iterable, List, Optional

__version__ = "1.2.0"

MAX_DIRECT = 3  # direct tools beside search and execute, each on a measured case
MAX_TOOLS = 2 + MAX_DIRECT
MIN_CALLS = 20  # a measured case: at least this many calls of the operation in the window
MIN_SHARE = 0.30  # and at least this share of all the server's calls
KEEP = 0.8  # an incumbent keeps its seat above this part of the bar (no churn on noise)
#: the fabric-interop contract's job tools: a protocol outside the server requires them by name, so they take seats
#: of the three exceptions without a measurement until the contract folds them into execute; a client may flatten the
#: dot (`fabric_job_get`)
JOB_TOOLS = ("fabric.job.get", "fabric.job.cancel", "fabric.job.list")
#: capability tools the Fabric contract itself defines by name (the estate engine's `estate.survey`, `project.*`,
#: `memory.*`; the hub's `com.*`): they stay separate tools beside the doors, with this reason, and take no seat of
#: the three, until fabric-agent-contract answers request e6e13934; a server's own domain is never one of these
CONTRACT_TOOLS = ("estate.survey", "project.", "memory.", "com.")
CONTRACT_REASON = ("a name the Fabric contract defines; a separate tool until fabric-agent-contract answers "
                   "request e6e13934 (D-72)")
DESCRIPTION_MAX = 200  # a tool's description is one or two short sentences
PURPOSE_MAX = 200  # the contract's CM-3: an operation's purpose is one line of at most 200 characters
#: brackets and quotes a cut purpose never ends inside (`purpose`)
PAIRS = (("«", "»"), ("(", ")"), ("[", "]"), ("“", "”"))
GATES = ("none", "relayed", "human")
HUMAN_STEP = "human-step-required"
SEARCH_LIMIT = 10  # the canon's default page; at most SEARCH_MAX
SEARCH_MAX = 200  # the contract's CM-3 (limit 1 to 200; 1.0.0 held 50)
#: effects whose call needs an idempotency key through execute when the operation declares no idempotency (the canon:
#: write, money, delete, publish); a declared idempotency decides (the contract's CM-4: the key its own tool takes)
KEYED_EFFECTS = ("write", "money", "delete", "publish")
EFFECTS = ("read", "none") + KEYED_EFFECTS
#: a capability's idempotency as the Fabric manifest declares it: `required` (execute refuses a call without a key),
#: `supported` (a key replays, none runs), `none` (a key is ignored: a retry runs again, as by its own name)
IDEMPOTENCY = ("required", "supported", "none")

#: what `search` answers (`compact-mcp-search/1`), the contract's schema (fabric-agent-contract
#: `schemas/compact-mcp-search.schema.json` at 14df402c, DEC-0180 CM-3 and DEC-0182): closed, `nextCursor` absent on
#: the last page; what the base adds per operation (effect, idempotency) travels in `hints()`, beside it in `_meta`
_OPERATION_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["name", "purpose", "inputSchema", "gate", "direct"],
    "properties": {"name": {"type": "string"}, "purpose": {"type": "string", "minLength": 1, "maxLength": 200},
                   "inputSchema": {"type": "object"}, "outputSchema": {"type": "object"},
                   "gate": {"enum": list(GATES)}, "example": {"type": "object"}, "direct": {"type": "boolean"},
                   "calls": {"type": "integer", "minimum": 0}}}
SEARCH_ANSWER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["schema", "total", "matched", "operations"],
    "properties": {
        "schema": {"const": "compact-mcp-search/1"},
        "query": {"type": ["string", "null"], "maxLength": 200},
        "total": {"type": "integer", "minimum": 0}, "matched": {"type": "integer", "minimum": 0},
        "nextCursor": {"type": "string", "minLength": 1, "maxLength": 512},
        "operations": {"type": "array", "maxItems": 256, "items": _OPERATION_SCHEMA}}}

SEARCH_INPUT_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {
    "query": {"type": "string", "maxLength": 200},
    "names": {"type": "array", "maxItems": 50, "items": {"type": "string", "minLength": 1, "maxLength": 128}},
    "limit": {"type": "integer", "minimum": 1, "maximum": SEARCH_MAX},
    "cursor": {"type": "string", "pattern": "^[0-9]{1,6}$"}}}

EXECUTE_INPUT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["operation"], "properties": {
    "operation": {"type": "string", "minLength": 1, "maxLength": 128},
    "arguments": {"type": "object"},
    "idempotencyKey": {"type": "string", "minLength": 1, "maxLength": 128}}}


class Refusal(Exception):
    """A typed refusal: `body()` is `{"error": {"code", "message", "data"}}`, answered as an MCP error result."""

    def __init__(self, code: str, message: str, data: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code, self.message, self.data = code, message, data or {}

    def body(self) -> Dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "data": self.data}}


def operation(name: str, purpose: str, input_schema: Dict[str, Any], handler: Callable[[Dict[str, Any], Dict[str, Any]], Any],
              *, gate: str = "none", example: Optional[Dict[str, Any]] = None, human_step_url: Optional[str] = None,
              effect: str = "none", idempotency: Optional[str] = None,
              output_schema: Optional[Dict[str, Any]] = None, words: Optional[str] = None) -> Dict[str, Any]:
    """One operation: its capability name, a one-line purpose of at most 200 characters (the contract's CM-3; write
    it, or fit a long text with `purpose(text)`), its input schema, its handler(arguments, meta), its gate (`none`,
    `relayed`, `human`), an example of arguments, the link of a human step, its effect class, the idempotency its own
    tool declares (`required`, `supported`, `none`; None: the effect decides), the output schema its own tool serves
    (search answers it) and `words`, more text search matches beside the name and the purpose and never shows (the
    operation's whole description, the deployment's own search words; the documented extension of 1.2.0)."""
    if gate not in GATES:
        raise ValueError("gate is one of %s" % ", ".join(GATES))
    if effect not in EFFECTS:
        raise ValueError("effect is one of %s" % ", ".join(EFFECTS))
    if idempotency is not None and idempotency not in IDEMPOTENCY:
        raise ValueError("idempotency is one of %s" % ", ".join(IDEMPOTENCY))
    if gate == "human" and not (isinstance(human_step_url, str) and re.match(r"https://|/", human_step_url)):
        raise ValueError("%s: a human step needs its link, an https URL or a path" % name)
    if not isinstance(purpose, str) or not purpose.strip() or "\n" in purpose:
        raise ValueError("%s: the purpose is one line" % name)
    if len(purpose.strip()) > PURPOSE_MAX:
        raise ValueError("%s: the purpose is at most %d characters; write one, or fit the text with purpose()"
                         % (name, PURPOSE_MAX))
    if words is not None and not isinstance(words, str):
        raise ValueError("%s: words is text" % name)
    return {"name": name, "purpose": purpose.strip(), "inputSchema": input_schema, "handler": handler, "gate": gate,
            "example": example if example is not None else {}, "url": human_step_url, "effect": effect,
            "idempotency": idempotency, "outputSchema": output_schema, "words": words or ""}


def idempotency_of(declared: Optional[str], effect: Optional[str]) -> str:
    """The key rule execute applies, one rule for the pattern and every door built on it (the contract's CM-4: the
    key its own tool takes): a declared `required`, `supported` or `none` decides; anything else (absent, or a value
    outside those three) falls back to the effect rule, `required` for a write, money, delete or publish effect and
    `supported` otherwise."""
    if declared in IDEMPOTENCY:
        return declared
    return "required" if effect in KEYED_EFFECTS else "supported"


def keyed(op: Dict[str, Any]) -> bool:
    """Whether execute needs a key for this operation (`idempotency_of` answers `required`)."""
    return idempotency_of(op.get("idempotency"), op.get("effect")) == "required"


def _first_open(text: str) -> Optional[int]:
    """The index of the first bracket or quote of `PAIRS` still open at the end of `text`, else None."""
    opened: Dict[str, List[int]] = {o: [] for o, _ in PAIRS}
    closers = {c: o for o, c in PAIRS}
    for i, ch in enumerate(text):
        if ch in opened:
            opened[ch].append(i)
        elif ch in closers and opened[closers[ch]]:
            opened[closers[ch]].pop()
    left = [i for stack in opened.values() for i in stack]
    return min(left) if left else None


def purpose(text: Any, limit: int = PURPOSE_MAX) -> str:
    """A one-line purpose of at most `limit` characters (20 at least) from a longer text, for an operation no written
    purpose names: the first non-empty line, whitespace folded; when it is longer, cut after the last sentence that fits
    and keeps at least a third of `limit` (it ends on its full stop), else at the last whole word with an ellipsis;
    never inside an open bracket or quote of `PAIRS` (the cut moves before the one left open; when the line opens with
    it, the unclosed mark is dropped). A single word longer than `limit` is cut at `limit - 1`. Empty text, or text of
    nothing but opening marks, answers '' (the caller shows the name instead).
    Search still finds the operation by a word past the cut when the operation carries the text in `words`."""
    limit = max(20, int(limit))
    lines = [" ".join(raw.split()) for raw in str(text or "").splitlines() if raw.strip()]
    if not lines:
        return ""
    line = lines[0]
    if len(line) <= limit:
        return line
    best = None
    for m in re.finditer(r"[.!?](?=\s|$)", line[:limit + 1]):
        if m.end() <= limit and _first_open(line[:m.end()]) is None:
            best = m.end()
    if best is not None and best >= limit // 3:
        return line[:best]
    room = limit - 1  # one character for the ellipsis
    space = line.rfind(" ", 0, room + 1)
    cut = line[:space] if space > 0 else line[:room]
    at = _first_open(cut)
    while at is not None and cut[:at].strip():
        cut = cut[:at].rstrip()
        at = _first_open(cut)
    if at is not None:  # the line opens with an unclosed mark: drop the marks left open, keep the words
        while at is not None:
            cut = cut[:at] + cut[at + 1:]
            at = _first_open(cut)
    cut = cut.rstrip(" ,;:-–")
    if not cut:  # nothing but marks: what is left with no opening mark, else nothing
        openers = {o for o, _ in PAIRS}
        cut = "".join(ch for ch in line[:room] if ch not in openers).strip()
    return cut + "…" if cut else ""


def words_of(query: Optional[str]) -> List[str]:
    """The words of a search query: lower case, split on anything but letters, digits, `_` and `.`."""
    return [w for w in re.split(r"[^\w.]+", (query or "").lower()) if w]


def matches(words: Iterable[str], *texts: Optional[str]) -> bool:
    """Whether every word is in the texts joined, case-insensitively: the name and the purpose (the contract's CM-3)
    and, past it, the operation's `words` (the documented extension of 1.2.0)."""
    hay = " ".join(t for t in texts if t).lower()
    return all(w in hay for w in words)


# --- the input schema: the subset tools use ------------------------------------------------------------------------
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _type_ok(value: Any, kind: str) -> bool:
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES.get(kind, object))


def validate(value: Any, schema: Dict[str, Any], path: str = "arguments") -> List[str]:
    """The problems of `value` against the schema subset tools use (type, enum, const, required, properties,
    additionalProperties false, items, string and number bounds, pattern); an empty list is valid."""
    out: List[str] = []
    if not isinstance(schema, dict):
        return out
    kinds = schema.get("type")
    if kinds is not None:
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if not any(_type_ok(value, k) for k in kinds):
            return ["%s is not %s" % (path, " or ".join(kinds))]
    if "enum" in schema and value not in schema["enum"]:
        out.append("%s is not one of %s" % (path, schema["enum"]))
    if "const" in schema and value != schema["const"]:
        out.append("%s is not %r" % (path, schema["const"]))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            out.append("%s is shorter than %d" % (path, schema["minLength"]))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append("%s is longer than %d" % (path, schema["maxLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append("%s does not match %s" % (path, schema["pattern"]))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append("%s is below %s" % (path, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            out.append("%s is above %s" % (path, schema["maximum"]))
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                out.append("%s.%s is required" % (path, key))
        if schema.get("additionalProperties") is False:
            out.extend("%s.%s is not a known argument" % (path, k) for k in value if k not in props)
        for key, sub in props.items():
            if key in value:
                out.extend(validate(value[key], sub, "%s.%s" % (path, key)))
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append("%s has more than %d items" % (path, schema["maxItems"]))
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                out.extend(validate(item, schema["items"], "%s[%d]" % (path, i)))
    return out


# --- the surface ---------------------------------------------------------------------------------------------------
def earns_direct(calls: int, total: int, *, min_calls: int = MIN_CALLS, min_share: float = MIN_SHARE) -> bool:
    """A measured case for a direct tool: enough calls, and enough of the server's calls, that a search before each
    one costs more than a listed tool."""
    return total > 0 and calls >= min_calls and calls / total >= min_share


class CompactSurface:
    """A server's operations behind two doors, `<domain>.search` and `<domain>.execute` (else `search` and
    `execute`). `direct`: up to three operation names listed as their own tools, each only with its measured case in
    `measured` ({name: {"calls", "total", "window"}}, `earns_direct`); `job_tools`: the protocol tools the server also
    lists (the kit's `fabric.job.get`, `fabric.job.cancel`), which take seats of the three without a measurement until
    the contract folds them into execute; `legacy`: an operation's own old tool name, off the listing, keeps answering
    (R28: a name that shipped is never broken), its result marked `retired` with the date in `retired` when given
    (`legacy=False` only for operations that never shipped under their own names); `audit(record)` receives one
    record per call;
    `usage` a `UsageCounter`."""

    def __init__(self, operations: Iterable[Dict[str, Any]], *, direct: Iterable[str] = (), domain: Optional[str] = None,
                 measured: Optional[Dict[str, Dict[str, Any]]] = None, legacy: bool = True,
                 job_tools: Iterable[str] = (), retired: Optional[str] = None,
                 audit: Optional[Callable[[Dict[str, Any]], None]] = None, usage: Optional["UsageCounter"] = None):
        self.operations: Dict[str, Dict[str, Any]] = {}
        for op in operations:
            if op["name"] in self.operations:
                raise ValueError("operation %s is declared twice" % op["name"])
            self.operations[op["name"]] = op
        self.search_name = "%s.search" % domain if domain else "search"
        self.execute_name = "%s.execute" % domain if domain else "execute"
        for reserved in (self.search_name, self.execute_name):
            if reserved in self.operations:
                raise ValueError("%s names the surface's own tool" % reserved)
        direct = list(dict.fromkeys(direct))
        unknown = [d for d in direct if d not in self.operations]
        if unknown:
            raise ValueError("direct names unknown operations: %s" % ", ".join(unknown))
        job_tools = list(dict.fromkeys(job_tools))
        if any(not is_job_tool(j) for j in job_tools):
            raise ValueError("job_tools names only the contract's job tools (%s)" % ", ".join(JOB_TOOLS))
        if len(direct) + len(job_tools) > MAX_DIRECT:
            raise ValueError("at most %d exceptions beside the doors, the protocol's job tools counted" % MAX_DIRECT)
        measured = measured or {}
        for d in direct:
            m = measured.get(d) or {}
            if not earns_direct(int(m.get("calls") or 0), int(m.get("total") or 0)) or not m.get("window"):
                raise ValueError("%s: a direct tool needs its measured case (calls, total, window; at least %d calls "
                                 "and %d %% of the server's)" % (d, MIN_CALLS, round(MIN_SHARE * 100)))
        self.direct = direct
        self.measured = {d: dict(measured[d]) for d in direct}
        self.job_tools = job_tools
        self.legacy = legacy
        self.retired = retired
        self.audit = audit
        self.usage = usage
        self._done: Dict[str, Dict[str, Any]] = {}  # idempotency key: {digest, result}

    # tools/list ---------------------------------------------------------------------------------------------------
    def tools(self) -> List[Dict[str, Any]]:
        """The tools/list answer: the measured direct tools, then search and execute (the job tools the server lists
        are the kit's own and follow them; with them, never more than five)."""
        out = [{"name": n, "description": self.operations[n]["purpose"],
                "inputSchema": self.operations[n]["inputSchema"]} for n in self.direct]
        out.append({"name": self.search_name, "inputSchema": SEARCH_INPUT_SCHEMA, "annotations": {"readOnlyHint": True},
                    "description": "Every operation of this server: name, purpose, input schema, gate, example. "
                                   "Filter by words."})
        out.append({"name": self.execute_name, "inputSchema": EXECUTE_INPUT_SCHEMA,
                    "description": "Run an operation that search returned. Never guess a name; call search first."})
        return out

    def reachable(self) -> List[str]:
        """Every operation an agent reaches: listed directly or answered by search, page by page (R33 O8 parity)."""
        seen, cursor = set(self.direct), None
        while True:
            page = self.search(limit=SEARCH_MAX, cursor=cursor)
            seen |= {o["name"] for o in page["operations"]}
            cursor = page.get("nextCursor")
            if cursor is None:
                return sorted(seen)

    # search -------------------------------------------------------------------------------------------------------
    def search(self, query: Optional[str] = None, limit: int = SEARCH_LIMIT, *, names: Optional[Iterable[str]] = None,
               cursor: Optional[str] = None) -> Dict[str, Any]:
        """Operations whose name, purpose or `words` hold every word of `query` (none: all; the contract's CM-3 reads
        the name and the purpose, `words` is the documented extension of 1.2.0), or exactly `names`, in declared order, a page of `limit` (at most 200) from `cursor`; `nextCursor` names the next page and is absent on the
        last (the contract's `compact-mcp-search/1`, closed)."""
        words = words_of(query)
        wanted = set(names) if names else None
        found = []
        for op in self.operations.values():
            if (wanted is None or op["name"] in wanted) and matches(words, op["name"], op["purpose"], op.get("words")):
                entry = {"name": op["name"], "purpose": op["purpose"], "inputSchema": op["inputSchema"],
                         "gate": op["gate"], "example": op["example"], "direct": op["name"] in self.direct}
                if op.get("outputSchema"):
                    entry["outputSchema"] = op["outputSchema"]
                if self.usage is not None:
                    entry["calls"] = self.usage.total(op["name"])
                found.append(entry)
        start = int(cursor) if cursor else 0
        size = max(1, min(int(limit), SEARCH_MAX))
        page = found[start:start + size]
        answer = {"schema": "compact-mcp-search/1", "query": query, "total": len(self.operations),
                  "matched": len(found), "operations": page}
        if start + size < len(found):
            answer["nextCursor"] = str(start + size)
        return answer

    def hints(self, answer: Dict[str, Any]) -> Dict[str, Any]:
        """What the base tells a caller beside a search answer, for the tool result's `_meta` (never inside the closed
        answer): per operation listed, its effect and the idempotency execute applies (`required`, `supported` or
        `none`; undeclared, the effect decides)."""
        out = {}
        for o in answer.get("operations") or []:
            op = self.operations.get(o.get("name"))
            if op is not None:
                out[op["name"]] = {"effect": "read" if op["effect"] == "none" else op["effect"],
                                   "idempotency": idempotency_of(op.get("idempotency"), op["effect"])}
        return {"operations": out}

    # calls --------------------------------------------------------------------------------------------------------
    def call(self, tool: str, arguments: Optional[Dict[str, Any]] = None,
             meta: Optional[Dict[str, Any]] = None) -> Any:
        """One tools/call. Raises Refusal for every refusal (unknown tool or operation, invalid arguments, a gate)."""
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments, dict):
            raise Refusal("invalid-arguments", "Arguments are a JSON object.")
        if tool == self.search_name:
            problems = validate(arguments, SEARCH_INPUT_SCHEMA)
            if problems:
                raise Refusal("invalid-arguments", "; ".join(problems))
            return self.search(arguments.get("query"), arguments.get("limit", SEARCH_LIMIT),
                               names=arguments.get("names"), cursor=arguments.get("cursor"))
        if tool == self.execute_name:
            problems = validate(arguments, EXECUTE_INPUT_SCHEMA)
            if problems:
                raise Refusal("invalid-arguments", "; ".join(problems))
            return self.dispatch(arguments["operation"], arguments.get("arguments") or {}, meta,
                                 key=arguments.get("idempotencyKey"), via="execute")
        if tool in self.direct or (self.legacy and tool in self.operations):  # direct, or an old name (retired)
            via = "direct" if tool in self.direct else "name"
            out = self.dispatch(tool, arguments, meta, key=(meta or {}).get("idempotencyKey"), via=via)
            if via == "name" and self.retired and isinstance(out, dict):
                out = dict(out, retired={"since": self.retired, "replacedBy": self.execute_name})
            return out
        raise Refusal("unknown-tool", "No tool %s here; call %s to list the operations." % (tool, self.search_name),
                      {"near": difflib.get_close_matches(tool, list(self.operations), 3, 0.5)})

    def dispatch(self, name: str, arguments: Dict[str, Any], meta: Optional[Dict[str, Any]] = None, *,
                 key: Optional[str] = None, via: str = "direct") -> Any:
        """The one path of every call: schema, gate, idempotency, handler, audit."""
        meta = meta or {}
        op = self.operations.get(name)
        if op is None:
            self._audit(name, via, "unknown-operation", key)
            raise Refusal("unknown-operation", "No operation %s; %s lists them." % (name, self.search_name),
                          {"near": difflib.get_close_matches(name, list(self.operations), 3, 0.5)})
        problems = validate(arguments, op["inputSchema"]) if isinstance(op["inputSchema"], dict) else []
        if problems:
            self._audit(name, via, "invalid-arguments", key)
            raise Refusal("invalid-arguments", "; ".join(problems), {"inputSchema": op["inputSchema"]})
        if via == "execute" and keyed(op) and key is None:
            self._audit(name, via, "idempotency-required", key)
            raise Refusal("idempotency-required", "%s takes an idempotencyKey." % name)
        if idempotency_of(op.get("idempotency"), op.get("effect")) == "none":
            key = None  # its own tool takes no key: a retry runs again, as by its own name (CM-4), nothing stored
        if op["gate"] == "human":
            self._audit(name, via, HUMAN_STEP, key)
            raise Refusal(HUMAN_STEP, "This step is a person's: open the link.", {"url": op["url"]})
        if op["gate"] == "relayed" and not _decision_ok(meta.get("decision")):
            self._audit(name, via, "operator-decision-required", key)
            raise Refusal("operator-decision-required", "Relay the operator's own words in _meta.decision "
                          "(by, via, action, target, instruction, at).")
        digest = hashlib.sha256(json.dumps([name, arguments], sort_keys=True, default=str).encode()).hexdigest()
        if key is not None and key in self._done:
            if self._done[key]["digest"] != digest:
                self._audit(name, via, "idempotency-conflict", key)
                raise Refusal("idempotency-conflict", "This idempotency key was used with other arguments.")
            self._audit(name, via, "replayed", key)
            return self._done[key]["result"]
        result = op["handler"](arguments, meta)
        if key is not None:
            self._done[key] = {"digest": digest, "result": result}
        if self.usage is not None:
            self.usage.count(name)
        self._audit(name, via, "ok", key)
        return result

    def _audit(self, name: str, via: str, outcome: str, key: Optional[str]) -> None:
        if self.audit is not None:
            op = self.operations.get(name)
            self.audit({"operation": name, "via": via, "gate": op["gate"] if op else None, "outcome": outcome,
                        "idempotencyKey": key})


def _decision_ok(decision: Any) -> bool:
    """The operator's relayed words (DEC-0121): by, via, action, target, instruction and at, all present."""
    return isinstance(decision, dict) and all(isinstance(decision.get(k), str) and decision[k].strip()
                                              for k in ("by", "via", "action", "target", "instruction", "at"))


# --- choosing and revising the direct three ------------------------------------------------------------------------
def choose_direct(names: Iterable[str], usage: Optional[Dict[str, int]] = None, *, current: Iterable[str] = (),
                  k: int = MAX_DIRECT, min_calls: int = MIN_CALLS, min_share: float = MIN_SHARE,
                  window: Optional[str] = None) -> Dict[str, Any]:
    """The operations that earn a direct seat by measured calls (`earns_direct`), most calls first, at most `k`; an
    incumbent of `current` keeps its seat while it stays above `KEEP` of the bar. No measurement, no direct tool: the
    server is search and execute. Answers {direct, measured: {name: {calls, total, window}}, changed}."""
    names = list(dict.fromkeys(names))
    usage = {n: int((usage or {}).get(n, 0)) for n in names}
    total = sum(usage.values())
    order = {n: i for i, n in enumerate(names)}
    k = max(0, min(k, MAX_DIRECT))
    current = [c for c in dict.fromkeys(current) if c in names]
    kept = [c for c in current if earns_direct(usage[c], total, min_calls=int(min_calls * KEEP),
                                               min_share=min_share * KEEP)]
    fresh = [n for n in names if n not in kept and earns_direct(usage[n], total, min_calls=min_calls,
                                                                 min_share=min_share)]
    picked = sorted(kept + fresh, key=lambda n: (-usage[n], order[n]))[:k]
    measured = {n: {"calls": usage[n], "total": total, "window": window or "measured"} for n in picked}
    return {"direct": picked, "measured": measured, "changed": set(current) != set(picked)}


class UsageCounter:
    """Calls per operation per UTC day, kept in one JSON file written atomically (no call text, no caller)."""

    def __init__(self, path: Optional[os.PathLike] = None, *, today: Callable[[], str] = None, keep_days: int = 90):
        self.path = pathlib.Path(path) if path else None
        self._today = today or (lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"))
        self.keep_days = keep_days
        self.days: Dict[str, Dict[str, int]] = {}
        if self.path is not None and self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.days = {d: {n: int(c) for n, c in v.items()} for d, v in (data.get("days") or {}).items()}
            except (OSError, ValueError, AttributeError, TypeError):
                self.days = {}

    def count(self, name: str) -> None:
        day = self._today()
        self.days.setdefault(day, {})
        self.days[day][name] = self.days[day].get(name, 0) + 1
        for old in sorted(self.days)[:-self.keep_days]:
            del self.days[old]
        self._save()

    def total(self, name: str) -> int:
        return sum(v.get(name, 0) for v in self.days.values())

    def totals(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for v in self.days.values():
            for n, c in v.items():
                out[n] = out.get(n, 0) + c
        return out

    def window(self) -> Dict[str, Optional[str]]:
        days = sorted(self.days)
        return {"from": days[0] if days else None, "to": days[-1] if days else None}

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".usage-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"schema": "compact-mcp-usage/1", "days": self.days}, f, sort_keys=True)
        os.replace(tmp, self.path)


# --- counting and checking a server --------------------------------------------------------------------------------
def count_tools(doc: Any) -> Dict[str, Any]:
    """A server's tool names from a `tools/list` answer (JSON-RPC or its result), a list of tools, a Fabric manifest
    (`capabilities`), a `.well-known/fabric-service` document (`surfaces.mcp.capabilities`) or a template manifest's
    doors ({variant: [{tool}]}); `source` names which."""
    def names(items):
        return [i.get("name") or i.get("tool") if isinstance(i, dict) else i for i in items
                if isinstance(i, (dict, str))]
    if isinstance(doc, list):
        found, source = names(doc), "tools"
    elif isinstance(doc, dict) and isinstance((doc.get("result") or {}).get("tools"), list):
        found, source = names(doc["result"]["tools"]), "tools/list"
    elif isinstance(doc, dict) and isinstance(doc.get("tools"), list):
        found, source = names(doc["tools"]), "tools/list"
    elif isinstance(doc, dict) and isinstance(doc.get("capabilities"), list):
        found, source = names(doc["capabilities"]), "manifest"
    elif isinstance(doc, dict) and isinstance(((doc.get("surfaces") or {}).get("mcp") or {}).get("capabilities"), list):
        found, source = names(doc["surfaces"]["mcp"]["capabilities"]), "well-known"
    else:
        found, source = [], "unknown"
    found = [n for n in found if isinstance(n, str)]
    return {"source": source, "names": found, "count": len(found)}


def _door(name: str, kind: str) -> bool:
    return name == kind or name.endswith("." + kind) or name.endswith("_" + kind)


def is_job_tool(name: str) -> bool:
    """A fabric-interop job tool (`fabric.job.get`, `.cancel`, `.list`, or flattened): an exception without a
    measurement, the contract its reason."""
    return name in JOB_TOOLS or name.replace("_", ".") in JOB_TOOLS


def is_contract_tool(name: str) -> bool:
    """A capability tool the Fabric contract defines by name (the estate engine's `estate.survey`, `project.*`,
    `memory.*`; the hub's `com.*`; dotted or flattened): a separate tool with its reason, no seat of the three."""
    dotted = name.replace("_", ".")
    return any(dotted == c or (c.endswith(".") and dotted.startswith(c)) for c in CONTRACT_TOOLS)


def check(doc: Any, *, measured: Optional[Iterable[str]] = None, descriptions: bool = True) -> Dict[str, Any]:
    """The verdict of one server against the rule: `count`, `shape` (`two-doors`: search and execute alone;
    `two-doors+direct`: with up to three exceptions; `over`: more than three; `no-doors`: search and execute missing),
    `direct` (every exception, the protocol's job tools included), `jobs` (those of them, which need no measurement),
    `contract` (the names the contract defines, separate tools outside the count, `CONTRACT_REASON`),
    `within` and the findings, each `{code, blocking, message}`. `measured`: the direct tools that have a
    recorded measured case; a direct tool outside it is blocking, and when it is not given the case is unverified."""
    tools = doc if isinstance(doc, list) else ((doc.get("result") or {}).get("tools") if isinstance(doc, dict) and
                                               isinstance(doc.get("result"), dict) else
                                               doc.get("tools") if isinstance(doc, dict) else None)
    counted = count_tools(doc)
    contract = [n for n in counted["names"] if is_contract_tool(n)]
    names = [n for n in counted["names"] if not is_contract_tool(n)]
    findings = []
    has_search = any(_door(n, "search") for n in names)
    has_execute = any(_door(n, "execute") for n in names)
    jobs = [n for n in names if is_job_tool(n)]
    direct = [n for n in names if not _door(n, "search") and not _door(n, "execute")]  # job tools count here too
    measurable = [n for n in direct if not is_job_tool(n)]
    if counted["source"] == "unknown":
        findings.append({"code": "unreadable", "blocking": True, "message": "no tools, capabilities or MCP surface "
                         "found in the document"})
    if not (has_search and has_execute):
        findings.append({"code": "no-search-execute", "blocking": True, "message": "the two doors are search and "
                         "execute; this server lists %s" % ("neither" if not (has_search or has_execute) else
                                                            "only " + ("search" if has_search else "execute"))})
    if len(direct) > MAX_DIRECT:
        findings.append({"code": "too-many-tools", "blocking": True, "message": "%d tools besides search and execute; "
                         "at most %d exceptions, each measured or a protocol's job tool" % (len(direct), MAX_DIRECT)})
    if measurable and len(direct) <= MAX_DIRECT:
        if measured is None:
            findings.append({"code": "direct-unverified", "blocking": False, "message": "direct tools %s: their "
                             "measured case is not given (--measured)" % ", ".join(measurable)})
        else:
            missing = [d for d in measurable if d not in set(measured)]
            if missing:
                findings.append({"code": "direct-without-measurement", "blocking": True, "message": "direct tools "
                                 "without a measured case: %s" % ", ".join(missing)})
    if contract:
        findings.append({"code": "contract-tools", "blocking": False, "message": "%s: %s" % (", ".join(contract),
                         CONTRACT_REASON)})
    if len(set(counted["names"])) != len(counted["names"]):
        findings.append({"code": "duplicate-tool", "blocking": True, "message": "a tool is listed twice"})
    if descriptions and isinstance(tools, list):
        for t in tools:
            if not isinstance(t, dict):
                continue
            text = t.get("description") or ""
            if len(text) > DESCRIPTION_MAX:
                findings.append({"code": "description-too-long", "blocking": False, "message": "%s: %d characters, "
                                 "keep it under %d" % (t.get("name"), len(text), DESCRIPTION_MAX)})
    shape = ("over" if len(direct) > MAX_DIRECT else "no-doors" if not (has_search and has_execute)
             else "two-doors+direct" if direct else "two-doors")
    return {"count": counted["count"], "source": counted["source"], "shape": shape, "direct": direct, "jobs": jobs,
            "contract": contract,
            "within": not any(f["blocking"] for f in findings), "findings": findings}


def main(argv: List[str]) -> int:
    measured = None
    if "--measured" in argv:
        i = argv.index("--measured")
        measured = [m for m in (argv[i + 1] if i + 1 < len(argv) else "").split(",") if m]
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 2 or argv[0] != "check":
        print("usage: compact_mcp.py check <tools-list-or-manifest.json> [--measured name,name]", file=sys.stderr)
        return 2
    try:
        doc = json.loads(pathlib.Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("cannot read %s: %s" % (argv[1], exc), file=sys.stderr)
        return 2
    verdict = check(doc, measured=measured)
    print(json.dumps(verdict, indent=1))
    return 0 if verdict["within"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
