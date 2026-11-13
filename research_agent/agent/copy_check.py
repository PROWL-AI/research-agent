# vendored from patterns/copy-check/code/copy_check.py@1.1.0
"""One source and one engine for the copy rules of every string a person reads (pattern `copy-check`, version 1.1.0).

The rules for text a person reads are one catalogue: the AI-tell markers AT-01 to AT-16 of the copywriting skill of
the super-ux plugin (`skills/copywriting/references/ai-tells.md`), read by name and home with a checked date (R11) and
pinned here by the version and the SHA-256 of its marker table (`CATALOGUE`). The engine that checks them is the
organization's text service (content-brand, variant `text-in-voice-service`): its `check` and `check.batch` tools,
reached through the agent's own door. An agent never keeps a private copy of a copy rule in a prompt or a lint, and a
text defect a person flags is fixed in the catalogue and the engine, then in the producer that skipped the check,
never here alone (operator rule 2026-11-11).

How a producer uses it: every string a person sees (a title, a label, a button, a caption, a slide or on-screen line,
a hook, a reply, a body) goes through `check(text, role=..., locale=..., engine=door)` (or `check_batch`) before it is
delivered, with its role; `ok` false holds it (rewrite, or a person's sign-off).

Guarantees:
- the engine answers first; its findings keep their own rule id and gain the catalogue id they enforce;
- a marker the operator flagged (`HOLD`: AT-06 the dash, AT-07 a full stop in a title, AT-11 "not just X, but Y",
  AT-16 invisible characters) that the engine's coverage does not show is checked here by the offline fallback, and
  named in `degraded` as an engine gap (AT-07 also when the engine takes no role: it cannot know a string is a title);
- a finding of a `HOLD` marker holds delivery whatever severity the engine gave it (but an AT-16 finding the engine
  declines to patch, a joiner that may be meaningful, which the fallback also lets pass, is advice); any other finding
  the engine marks blocking holds it too; the rest is advice;
- no engine (an organization without a text service) runs the fallback alone, named `no-engine` in `degraded`; an
  engine that fails holds the string (`engine-unavailable`) unless the caller allows offline delivery (`offline_ok`);
- the fallback checks only the `HOLD` markers and says which machine-checkable markers it did not check
  (`offline-unchecked:`), so a fallback pass never reads as the engine's pass;
- `pin_check(text)` compares an installed catalogue with the pin: a moved table fails the agent's gate until the
  pattern is re-pinned (`python3 copy_check.py pin <ai-tells.md>`).

The service's wire (1.1.0, feedback fb-20261113-a0e1dd; read at the service's commit f1e9cc2):
- roles: the service takes nine (`ENGINE_ROLES`); a door's `roles = True` means those nine, a tuple names the exact
  set its service takes. A role it does not take goes as the role it documents for the same kind of string
  (`ROLE_FALLBACK`: a hook and a reply are sentences, `body`), named `engine-role:<role>=<sent>` in `degraded`; a
  refusal of a role sent as is is asked once more with that role, so the client is right before and after the
  service takes `hook` and `reply`;
- rule ids: the service's own table of rule ids by catalogue id (`SERVICE_RULES`) maps its findings to markers, so a
  finding without a `catalogue` field still names the marker it enforces;
- coverage: its rows are rule groups (`COVERAGE_ROWS`: `ai-tells`, `no-em-dash`, `humanization`,
  `language-independent`); a row whose status is pass, warn, fail or not_applicable covers its markers, a row that is
  limited (findings cut) or not_run does not, and the phrase marker AT-11 counts only in en* and ru*, where the service
  runs it; the fallback runs for exactly the markers no row covers;
- answers: a refusal (`{error: ...}`) holds like a door that raised; a batch answer may be the service's own
  `{results: [{index, check, error}]}`; `degraded` objects `{source, reason}` read as `engine:<source>:<reason>`.

Replace: nothing in this file (it is vendored); the agent supplies the door (an object with `check(request)` returning
the text service's answer and, optionally, `check_batch(items, shared)` and `roles`: True for the service's nine
roles, or the tuple of roles its service takes).
"""
from __future__ import annotations

import hashlib
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

__version__ = "1.1.0"
__all__ = ["CATALOGUE", "COVERAGE_ROWS", "ENGINE_ROLES", "EngineUnavailable", "HOLD", "MACHINE", "ROLES",
           "ROLE_FALLBACK", "RULE_MARKERS", "SERVICE_RULES", "TITLE_ROLES", "check", "check_batch", "fallback",
           "pin_check", "table_digest", "table_rows", "writer_brief"]

CATALOGUE = {
    "name": "copywriting skill of the super-ux plugin, AI-tell markers",
    "file": "skills/copywriting/references/ai-tells.md",
    "version": "0.67.1",
    "checked": "2026-11-11",
    "markers": 16,
    "table_sha256": "9b3f5ab992d96b6112b29ac91f1b8b9364f3cf01f4261d182e65261bf3094d36",
}
MACHINE = ("AT-01", "AT-02", "AT-05", "AT-06", "AT-07", "AT-16")  # the pinned table's markers not left to judgement
HOLD = ("AT-06", "AT-07", "AT-11", "AT-16")  # flagged by the operator: they hold delivery and have an offline rule
ROLES = ("title", "heading", "label", "button", "caption", "slide", "on-screen", "hook", "voice-over", "reply", "body")
TITLE_ROLES = ("title", "heading", "label", "button", "slide", "on-screen")
# The roles the text service takes (its check and check.batch input, ai-tells-v1) and the role it documents for the
# same kind of string, for a role it does not take: a hook and a reply are sentences, as body text is.
ENGINE_ROLES = ("title", "heading", "label", "button", "caption", "slide", "on-screen", "voice-over", "body")
ROLE_FALLBACK = {"hook": "body", "reply": "body"}
# The service's own rule ids by the catalogue id each enforces (its table `aiTellRules`, ai-tells-v1). Its staccato
# rule ("No X. No Y.") is named by its own id, not a marker, and stays unmapped here.
SERVICE_RULES = {
    "AT-01": ("en-cliche", "ru-stamp"), "AT-02": ("at-02-hedging-chain",), "AT-05": ("vague-quantifier",),
    "AT-06": ("em-dash", "em-dash-substitute"), "AT-07": ("at-07-title-full-stop",),
    "AT-11": ("at-11-not-just-but",), "AT-13": ("at-13-colon-hook",), "AT-16": ("invisible-unicode",),
}
# Every rule id the client reads and the catalogue id it enforces (a finding that names its `catalogue` wins): the
# service's table, and the per-rule ids of an engine that reports one coverage row per rule.
RULE_MARKERS = {
    **{rule: marker for marker, rules in SERVICE_RULES.items() for rule in rules},
    "no-em-dash": "AT-06", "title-full-stop": "AT-07", "not-just-but": "AT-11", "invisible": "AT-16",
    "invisible-character": "AT-16",
}
# The service's coverage rows (one per rule group) and the HOLD markers each speaks for. `ai-tells` runs AT-07 in every
# locale and the phrase marker AT-11 in en* and ru* only (`PHRASE_LANGS`); invisible characters are in `humanization`
# for en* and ru* and in `language-independent` for the other locales.
COVERAGE_ROWS = {"no-em-dash": ("AT-06",), "ai-tells": ("AT-07", "AT-11"), "humanization": ("AT-16",),
                 "language-independent": ("AT-16",)}
PHRASE_LANGS = ("en", "ru")
PHRASE_MARKERS = ("AT-11",)
# A row covers its markers when it ran over every finding it had: pass, warn (findings shown), fail, or nothing to
# check. `limited` (its findings were cut by the service's cap) and `not_run` leave a gap.
COVERED = ("pass", "warn", "fail", "not_applicable")
BRIEF = {
    "AT-06": "no em dash, and no hyphen or two used as a dash: use a full stop, a comma, a colon or parentheses",
    "AT-07": "a title, heading, label, button, slide or on-screen line is a name: no full stop at its end or between "
             "its fragments",
    "AT-11": "no \"not just X, but Y\" construction: say what it is",
    "AT-16": "no invisible characters",
}

EM = chr(0x2014)
EN = chr(0x2013)
_TECH = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|`[^`\n]{1,200}`")
_DASH_SUB = re.compile(rf"(?<=\w)(?: -- |--)(?=\w)|(?<=[\w)\"'])\s[-{EN}]\s(?=[^\W\d])")
_NOT_JUST = {
    "en": re.compile(r"(?<!\w)not (?:just|only|merely|simply)\b[^.!?\n]{1,80}?\bbut\b", re.I),
    "ru": re.compile(r"(?<!\w)не (?:просто|только)\b[^.!?\n]{1,80}?,\s*(?:а|но)\b", re.I),
}
_INVISIBLE = re.compile("[­​⁠]|(?<!^)﻿")  # a zero-width joiner and direction marks are legitimate
_ABBREVIATION = re.compile(r"(?:(?<!\w)(?:etc|inc|ltd|co|corp|vs|approx|no|vol|fig|e\.g|i\.e|т\.\s?д|т\.\s?п|др|пр|"
                           r"млн|млрд|тыс|г|гг)|(?<!\w)[^\W\d_])\.$", re.I)
_TRAILING = " \t*_`)]\"'»”’"


class EngineUnavailable(Exception):
    """The text service did not answer (down, refused, timed out): the string waits unless offline delivery is
    allowed."""


def table_rows(text: str) -> list[str]:
    """The marker table's rows (`| AT-NN | ... |`) of an installed catalogue, stripped."""
    return [line.strip() for line in text.splitlines() if re.match(r"^\| AT-\d\d \|", line)]


def table_digest(text: str) -> str:
    return hashlib.sha256("\n".join(table_rows(text)).encode("utf-8")).hexdigest()


def pin_check(text: str) -> list[str]:
    """Problems of an installed catalogue against the pin: an empty list means the agent was built on this table."""
    rows = table_rows(text)
    if not rows:
        return ["no marker table: not the catalogue, or its format changed"]
    out = []
    if len(rows) != CATALOGUE["markers"]:
        out.append(f"{len(rows)} markers, the pin has {CATALOGUE['markers']}")
    if table_digest(text) != CATALOGUE["table_sha256"]:
        out.append("the marker table moved since the pin: re-read the catalogue, re-pin the pattern, re-vendor it")
    machine = tuple(r.split("|")[1].strip() for r in rows if "judgement" not in r.split("|")[-2])
    if machine != MACHINE:
        out.append(f"machine-checkable markers are {', '.join(machine)}, the pin has {', '.join(MACHINE)}")
    return out


def writer_brief(markers: Sequence[str] = HOLD) -> str:
    """The one line a writer prompt carries instead of a hand-copied rule: what the engine will hold the text for."""
    rules = "; ".join(f"{BRIEF[m]} ({m})" for m in markers if m in BRIEF)
    return (f"Copy rules: the organization's copy-rule catalogue (copywriting, AI-tell markers AT-01 to AT-16, "
            f"{CATALOGUE['version']}), checked by the text service before this text is delivered. It holds: {rules}.")


def _lang(locale: str | None, text: str) -> str:
    if locale:
        return locale.split("-")[0].lower()
    return "ru" if len(re.findall(r"[Ѐ-ӿ]", text)) > len(re.findall(r"[A-Za-z]", text)) else "en"


def _mask(text: str) -> str:
    return _TECH.sub(lambda m: "" * len(m.group(0)), text)


def _finding(marker: str, rule: str, start: int, end: int, text: str, message: str, level: str = "error") -> dict:
    return {"rule": rule, "catalogue": marker, "level": level, "message": message, "source": "fallback",
            "span": {"start": start, "end": end, "quote": text[start:end]}}


def _title_stops(prose: str, text: str, start: int, end: int) -> list[dict]:
    trimmed = prose[start:end].rstrip(_TRAILING)
    if not trimmed.endswith(".") or trimmed.endswith("..") or _ABBREVIATION.search(trimmed):
        return []
    msg = "a title is a name, not a sentence: no full stop at its end or between its fragments"
    out = [_finding("AT-07", "title-full-stop", start + m.start(), start + m.start() + 1, text, msg)
           for m in re.finditer(r"\.(?=\s+[^\W\d_])", trimmed)
           if trimmed[m.start() + 1:].lstrip()[:1].isupper() and not _ABBREVIATION.search(trimmed[:m.start() + 1])]
    last = start + len(trimmed) - 1
    return out + [_finding("AT-07", "title-full-stop", last, last + 1, text, msg)]


def fallback(text: str, *, role: str | None = None, locale: str | None = None,
             markers: Iterable[str] = HOLD) -> list[dict]:
    """The offline rules: only the `HOLD` markers asked for, on prose (links, addresses and code are masked)."""
    if role is not None and role not in ROLES:
        raise ValueError(f"unknown role {role!r}: one of {', '.join(ROLES)}")
    want = set(markers)
    prose = _mask(text)
    out: list[dict] = []
    if "AT-06" in want:
        out += [_finding("AT-06", "em-dash", m.start(), m.end(), text, "an em dash: use a full stop, comma, colon or "
                         "parentheses") for m in re.finditer(EM, prose)]
        out += [_finding("AT-06", "em-dash-substitute", m.start(), m.end(), text, "a hyphen or two used as a dash")
                for m in _DASH_SUB.finditer(prose)]
    if "AT-07" in want and role in TITLE_ROLES:
        at = 0
        for line in prose.split("\n"):
            if line.strip():
                out += _title_stops(prose, text, at, at + len(line))
            at += len(line) + 1
    if "AT-11" in want:
        rx = _NOT_JUST.get(_lang(locale, text), _NOT_JUST["en"])
        out += [_finding("AT-11", "not-just-but", m.start(), m.end(), text, "a 'not just X, but Y' construction: say "
                         "what it is") for m in rx.finditer(prose)]
    if "AT-16" in want:
        out += [_finding("AT-16", "invisible", m.start(), m.end(), text, "an invisible character")
                for m in _INVISIBLE.finditer(text)]
    return sorted(out, key=lambda f: (f["span"]["start"], f["rule"]))


def _accepted(engine: Any) -> tuple[str, ...]:
    """The roles the door's service takes: none, the service's nine (`roles = True`), or the tuple the door names."""
    roles = getattr(engine, "roles", False)
    if roles is True:
        return ENGINE_ROLES
    if isinstance(roles, (str, bytes)) or not roles:
        return ()
    return tuple(r for r in roles if r in ROLES)


def _sent_role(role: str | None, accepted: Sequence[str]) -> str | None:
    """The role the engine is asked with: the string's own, or the role the service documents for its kind."""
    if role is None or not accepted:
        return None
    if role in accepted:
        return role
    alt = ROLE_FALLBACK.get(role)
    return alt if alt in accepted else None


def _request(text, role, locale, extra) -> dict:
    req = {"text": text, "locale": locale}
    if role is not None:
        req["role"] = role
    req.update({k: v for k, v in extra.items() if v is not None})
    return req


def _refused(answer: Any) -> bool:
    """A refusal or a missing answer: the service's `{error: ...}`, or anything that is not an answer."""
    return not isinstance(answer, Mapping) or "error" in answer and answer.get("error") is not None


def _lang_of(report: Mapping[str, Any], locale: str | None) -> str | None:
    loc = report.get("locale") if isinstance(report.get("locale"), str) else locale
    return loc.split("-")[0].lower() if loc else None


def _covered(report: Mapping[str, Any], locale: str | None = None) -> set[str]:
    """The catalogue markers the engine's answer shows it checked whole: its catalogue list, its coverage rows (the
    service's rule-group rows, or one row per rule) and, for a marker no row speaks for, its findings. A finding does
    not cover a marker whose row was limited: the service cut some of that row's findings."""
    out = set(report.get("catalogue") or ())
    lang = _lang_of(report, locale)
    rowed: set[str] = set()
    for row in report.get("coverage") or ():
        if not isinstance(row, Mapping):
            continue
        rid = row.get("ruleId")
        if rid in COVERAGE_ROWS:
            markers = {m for m in COVERAGE_ROWS[rid] if m not in PHRASE_MARKERS or lang in PHRASE_LANGS}
        else:
            markers = {RULE_MARKERS[rid]} if RULE_MARKERS.get(rid) else set()
        rowed |= markers
        if row.get("status") in COVERED:
            out |= markers
    for f in report.get("findings") or ():
        m = f.get("catalogue") or RULE_MARKERS.get(f.get("ruleId") or f.get("rule"))
        if m and m not in rowed:
            out.add(m)
    return out


def _engine_findings(report: Mapping[str, Any]) -> list[dict]:
    blocking = set(report.get("blocking") or ()) | set((report.get("humanization") or {}).get("blocking") or ())
    out = []
    for f in report.get("findings") or ():
        rule = f.get("ruleId") or f.get("rule") or "unknown"
        marker = f.get("catalogue") or RULE_MARKERS.get(rule)
        severity = str(f.get("severity") or f.get("level") or "")
        if rule in blocking or severity in ("blocking", "block"):
            level = "block"
        elif marker == "AT-16" and "patch" in f and f.get("patch") is None:
            level = "advice"  # the service will not patch it: a joiner that may be meaningful, or inside code or a link
        elif marker in HOLD or severity == "error":
            level = "error"
        else:
            level = "advice"
        out.append({"rule": rule, "catalogue": marker, "level": level, "source": "engine",
                    "message": f.get("explanation") or f.get("message") or rule, "span": f.get("span")})
    return out


def _names(items: Iterable[Any]) -> list[str]:
    """The engine's `degraded`: names, or the service's `{source, reason}` objects, read as
    `engine:<source>:<reason>`."""
    out = []
    for d in items or ():
        if isinstance(d, Mapping):
            out.append(f"engine:{d.get('source') or 'unknown'}:{d.get('reason') or ''}".rstrip(":"))
        else:
            out.append(str(d))
    return out


def _verdict(text, role, locale, answer, sent_role, offline_ok, no_engine) -> dict:
    degraded: list[str] = []
    findings: list[dict] = []
    report_id = None
    if answer is not None and _refused(answer):
        answer = None
    if answer is None:
        degraded.append("no-engine" if no_engine else "engine-unavailable")
        gap = set(HOLD)
    else:
        report = answer.get("report", answer)
        report = report if isinstance(report, Mapping) else {}
        report_id = answer.get("reportId")
        degraded += _names(answer.get("degraded"))
        if role is not None and sent_role is not None and sent_role != role:
            degraded.append(f"engine-role:{role}={sent_role}")
        findings = _engine_findings(report)
        gap = set(HOLD) - _covered(report, locale)
        if role in TITLE_ROLES and sent_role not in TITLE_ROLES:
            gap.add("AT-07")
        degraded += [f"engine-gap:{m}" for m in sorted(gap)]
    seen = {(f["catalogue"], (f.get("span") or {}).get("start")) for f in findings}
    findings += [f for f in fallback(text, role=role, locale=locale, markers=gap)
                 if (f["catalogue"], f["span"]["start"]) not in seen]
    if answer is None:
        unchecked = [m for m in MACHINE if m not in HOLD]
        degraded.append("offline-unchecked:" + ",".join(unchecked))
    held = [f for f in findings if f["level"] in ("block", "error")]
    blocking = sorted({f["catalogue"] or f["rule"] for f in held})
    if answer is None and not no_engine and not offline_ok:
        blocking.append("engine-unavailable")
    source = "fallback" if answer is None else ("engine+fallback" if gap else "engine")
    return {"ok": not blocking, "blocking": blocking, "findings": findings, "source": source, "role": role,
            "report_id": report_id, "degraded": degraded,
            "catalogue": {"version": CATALOGUE["version"], "table_sha256": CATALOGUE["table_sha256"]}}


def check(text: str, *, role: str | None, locale: str | None = None, engine: Any = None, offline_ok: bool = False,
          register: str | None = None, format: str | None = None, voice_ref: Mapping | None = None,
          project_id: str | None = None, facts: str | None = None) -> dict:
    """Check one string a person will read, with its role. `ok` false holds delivery: `blocking` names why."""
    if role is not None and role not in ROLES:
        raise ValueError(f"unknown role {role!r}: one of {', '.join(ROLES)}")
    sent = _sent_role(role, _accepted(engine))
    answer = None
    if engine is not None:
        extra = {"register": register, "format": format, "voiceRef": voice_ref, "projectId": project_id,
                 "facts": facts}
        answer = _ask(engine.check, _request(text, sent, locale, extra))
        if answer is None and sent == role and ROLE_FALLBACK.get(role):  # a service that refuses the role as is
            sent = ROLE_FALLBACK[role]
            answer = _ask(engine.check, _request(text, sent, locale, extra))
    return _verdict(text, role, locale, answer, sent, offline_ok, engine is None)


def _ask(call, *args) -> Any:
    """One call to the door: its answer, or None for a refusal or a door that raised (hold, never pass)."""
    try:
        answer = call(*args)
    except Exception:  # EngineUnavailable, or any door error: an engine that did not answer
        return None
    return None if _refused(answer) else answer


def _batch_answers(answer: Any, n: int) -> list[Any]:
    """A batch door's answer as one answer per item: a list in order, or the service's `{results: [{index, check,
    error}]}` read by index. Anything else, or another number of results, is an engine that did not answer."""
    if isinstance(answer, Mapping) and "results" in answer:
        rows = answer.get("results") or []
        out: list[Any] = [None] * n
        for row in rows:
            i = row.get("index") if isinstance(row, Mapping) else None
            if not isinstance(i, int) or not 0 <= i < n:
                raise EngineUnavailable("a batch result without a valid index")
            out[i] = None if row.get("error") is not None else row.get("check")
        if len(rows) != n:
            raise EngineUnavailable("the batch answered another number of results")
        return out
    if _refused(answer) and isinstance(answer, Mapping):
        raise EngineUnavailable("the batch was refused")
    out = list(answer)
    if len(out) != n:
        raise EngineUnavailable("the batch answered another number of results")
    return [None if a is None or _refused(a) else a for a in out]


def check_batch(items: Sequence[Mapping[str, Any]], *, locale: str | None = None, engine: Any = None,
                offline_ok: bool = False, **shared) -> list[dict]:
    """Up to 50 strings per engine call (`check.batch`), each `{text, role, locale?}`; results in the items' order.
    An engine without a batch door is asked one string at a time."""
    for it in items:
        if it.get("role") is not None and it["role"] not in ROLES:
            raise ValueError(f"unknown role {it['role']!r}: one of {', '.join(ROLES)}")
    batch = getattr(engine, "check_batch", None)
    if engine is None or batch is None:
        return [check(it["text"], role=it.get("role"), locale=it.get("locale") or locale, engine=engine,
                      offline_ok=offline_ok, **shared) for it in items]
    accepted = _accepted(engine)
    extra = {"register": shared.get("register"), "format": shared.get("format"), "voiceRef": shared.get("voice_ref"),
             "projectId": shared.get("project_id"), "facts": shared.get("facts")}
    extra = {k: v for k, v in extra.items() if v is not None}
    out: list[dict] = []
    for i in range(0, len(items), 50):
        chunk = items[i:i + 50]
        sent = [_sent_role(it.get("role"), accepted) for it in chunk]

        def ask(roles):
            reqs = [_request(it["text"], r, it.get("locale") or locale, {}) for it, r in zip(chunk, roles)]
            try:
                return _batch_answers(batch(reqs, extra), len(chunk))
            except Exception:
                return None
        answers = ask(sent)
        mapped = [ROLE_FALLBACK.get(r, r) if r == it.get("role") else r for it, r in zip(chunk, sent)]
        if answers is None and mapped != sent:  # a service that refuses a role sent as is: once more, mapped
            sent, answers = mapped, ask(mapped)
        answers = answers or [None] * len(chunk)
        for n, (it, a) in enumerate(zip(chunk, answers)):
            if a is None and sent[n] != mapped[n]:  # that one item was refused for its role: ask it alone, mapped
                sent[n] = mapped[n]
                a = _ask(engine.check, _request(it["text"], sent[n], it.get("locale") or locale, extra))
            out.append(_verdict(it["text"], it.get("role"), it.get("locale") or locale, a, sent[n], offline_ok,
                                False))
    return out


if __name__ == "__main__":  # python3 copy_check.py pin <installed ai-tells.md>
    if len(sys.argv) == 3 and sys.argv[1] == "pin":
        problems = pin_check(open(sys.argv[2], encoding="utf-8").read())
        print("\n".join(problems) or f"pin holds: catalogue {CATALOGUE['version']}")
        sys.exit(1 if problems else 0)
    print(__doc__.split("\n", 1)[0])
    sys.exit(2)
