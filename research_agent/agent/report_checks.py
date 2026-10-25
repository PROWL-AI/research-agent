"""Defects a report's text proves against its ledger, by code alone (B-057).

Moved from the eval judge (`evals/judge.py`, W6-T1): the judge vetoes a pass on
them, and the writer's repair pass now fixes them before a report ships, so a
report is not judged on mistakes a program could already see. No model call.
"""

from __future__ import annotations

import re
from typing import Any

from research_agent.agent.writer import (
    _CITATION_BLOCK_RE, _CITATION_ID_RE, _NUMBER_RE, lint_report, partial_disclosed,
)
from research_agent.evidence.ledger import Ledger


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(\[])")
_QUOTE_RE = re.compile(r"[\"“]([^\"”]{3,})[\"”]")
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_LEADING_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SCALE_WORD_RE = re.compile(r"\s*(thousand|million|billion|bn)\b|([kKMB])\b", re.IGNORECASE)
#: "1.5 million visits": a scale word between the number and its unit, which
#: the writer lint's _NUMBER_RE does not read as one figure.
_SCALED_RE = re.compile(r"(?<![\w\d-])[$€£]?\s?\d[\d,]*(?:\.\d+)?\s*(?:thousand|million|billion|bn)\b", re.IGNORECASE)
_LETTER_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9}
_SCALE = {"k": 1e3, "K": 1e3, "thousand": 1e3, "M": 1e6, "million": 1e6, "B": 1e9, "bn": 1e9, "billion": 1e9}


_ABBREVIATION_RE = re.compile(r"\b(?:vs|e\.g|i\.e|approx|etc|cf|ca|incl|est)\.$", re.IGNORECASE)
#: A quoted search phrase is a keyword, not a quotation of a source.
_KEYWORD_CONTEXT_RE = re.compile(r"\b(?:keywords?|search(?:es)?|quer(?:y|ies)|terms?|phrases?|SERP)\b", re.IGNORECASE)


def _split_line(line: str) -> list[str]:
    parts: list[str] = []
    for chunk in _SENTENCE_RE.split(line):
        if parts and _ABBREVIATION_RE.search(parts[-1]):
            parts[-1] += " " + chunk  # "300 vs. 900": one sentence
        else:
            parts.append(chunk)
    return [p for p in parts if p.strip()]


def _sentences(report_md: str) -> list[str]:
    out: list[str] = []
    for line in report_md.splitlines():
        out.extend(_split_line(line))
    return out


def _cited(sentence: str) -> list[str]:
    """Claim ids a sentence cites. An `[UNVERIFIED: …]` tombstone cites nothing;
    the fidelity pass's composite `[UNVERIFIED, C2]` still cites C2."""
    ids: list[str] = []
    for block in _CITATION_BLOCK_RE.findall(sentence):
        if not block.startswith("[UNVERIFIED:"):
            ids.extend(f"C{n}" for n in _CITATION_ID_RE.findall(block))
    return list(dict.fromkeys(ids))


#: A fenced chart or code line: its JSON strings are data, not quotations (B-062).
_FENCED_RE = re.compile(r"^\s*```")


def _quotations(sentence: str) -> list[str]:
    """Quoted text of three words or more that reads as a quotation of a source:
    not a search phrase ("how to use Notion" search traffic), not a chart's JSON."""
    if _FENCED_RE.match(sentence):
        return []
    found = []
    for match in _QUOTE_RE.finditer(sentence):
        quoted = match.group(1)
        if len(quoted.split()) < 3:
            continue
        if quoted != quoted.strip() or " | " in quoted:
            # a closing quote paired with the next opening one (a sentence split
            # inside a quotation, or across table cells): the gap between two
            # quotations, not one (B-064)
            continue
        around = sentence[max(0, match.start() - 25):match.start()] + " " + sentence[match.end():match.end() + 25]
        if _KEYWORD_CONTEXT_RE.search(around):
            continue
        found.append(quoted)
    return found


#: A scale in a claim's unit: a word ("million USD"), or a letter beside a currency
#: ("USD m", "$M", "M USD") — a bare "m" or "b" is metres or bytes, not a scale.
_UNIT_SCALE_RE = re.compile(r"\b(thousand|million|billion|bn)\b|(?:\b(?:USD|EUR|GBP)\s*|[$€£]\s*)([kmb])\b|\b([kmb])\s*(?:USD|EUR|GBP)\b",
                            re.IGNORECASE)


def _claim_values(claims: list[Any]) -> list[float]:
    """What the cited claims carry: a numeric value (also scaled by its unit:
    value 12, unit "million USD" is 12,000,000), and the numbers in the claim's
    own text (any claim can state a figure in its words)."""
    values: list[float] = []
    for claim in claims:
        value = _numeric(claim)
        if value is not None:
            values.append(value)
            unit = _UNIT_SCALE_RE.search(claim.unit or "")
            if unit:
                word = next(g for g in unit.groups() if g).lower()
                values.append(value * (_SCALE.get(word) or _LETTER_SCALE[word]))
        # The claim's own text carries figures too ("increased by 21% to DKK 100,988
        # million": value 100988, text 21) (B-055).
        values.extend(n for n, _ in _figures(claim.claim) + _numbers(claim.claim))
    return values


def _numeric(claim: Any) -> float | None:
    try:
        return float(str(claim.value).replace(",", "")) if claim.value is not None else None
    except ValueError:
        return None


#: The writer's tag, as it writes it: the upper-case word ("[CONFLICT]", "(CONFLICT)").
_CONFLICT_TAG_RE = re.compile(r"\bCONFLICT\b")
#: A register heading or lead-in: the tag in brackets or parentheses, or the words "conflict register" —
#: not a status legend that merely lists CONFLICT among the statuses.
_CONFLICT_REGISTER_RE = re.compile(r"[\[(]CONFLICT[\])]|(?i:\bconflicts?\s+register\b)")
#: A section named "Source log", numbered or bold as the runbooks write it — not "Source log and findings".
#: A status legend names two or more statuses ("(VERIFIED) checked · (CONFLICT) disagree"): not a register.
_STATUS_WORD_RE = re.compile(r"\b(?:VERIFIED|ASSUMED|CONFLICT|UNVERIFIED)\b")


def _register(text: str) -> bool:
    return _CONFLICT_REGISTER_RE.search(text) is not None and len(set(_STATUS_WORD_RE.findall(text))) < 2


_SOURCE_LOG_HEADING_RE = re.compile(r"^#+\s*(?:\d+[.)]\s*)?(?:\*\*)?source log(?:\*\*)?\s*[:.]?\s*$", re.IGNORECASE)
_DERIVED_RE = re.compile(r"\bderived\b(?!\s+from\b)", re.IGNORECASE)
#: The writer's assumption marker: the figure is a stated assumption, not data (B-060).
_ASSUMPTION_RE = re.compile(r"\(target, assumption")
#: A figure that names a template item ("the 50% deterioration model", "a 30% stress
#: test") is a label, not a datum (B-060).
_LABEL_FIGURE_RE = re.compile(r"\d[\d,.]*\s?%?(?:\s+[a-z][a-z-]*){0,2}\s+(?:model|test|scenario|rule)s?\b", re.IGNORECASE)
#: Claim ids inside a conflict tag ("[CONFLICT w/ C32/C45]") name the rival
#: readings; they do not cite the line's figure (B-060).
_CONFLICT_REF_RE = re.compile(r"\[CONFLICT\b[^\]]*\]")


#: A status tag right after a citation block: "[C17] (VERIFIED)", "[C1, C2] VERIFIED (single source)".
_TAGGED_CITATION_RE = re.compile(r"(\[[^\]]*?\bC\d+[^\]]*?\])\s*\(?\s*VERIFIED\b")


#: A status label naming VERIFIED away from its citation ("**Confidence: VERIFIED (single
#: source)**", "**Confidence:** VERIFIED"). The word in prose ("VERIFIED claims are listed
#: below") is not a label, and UNVERIFIED does not match.
_VERIFIED_LABEL_RE = re.compile(r"(?i:confidence|status)\W{0,6}VERIFIED\b")


def _status_mislabels(report_md: str, claims: dict[str, Any]) -> list[tuple[str, str]]:
    """(claim id, line) for each citation tagged VERIFIED whose claim the ledger
    does not hold as verified (CORE-09: the writer must not call a claim
    VERIFIED that the ledger marks otherwise). A label away from its citation
    (after the sentence, or before the citation) counts when no claim the line
    cites is verified: the label then cannot be about any of them (B-081 run)."""
    found = []
    for line in report_md.splitlines():
        tagged = False
        for match in _TAGGED_CITATION_RE.finditer(line):
            for ref in (f"C{n}" for n in _CITATION_ID_RE.findall(match.group(1))):
                if ref in claims and claims[ref].status.value != "verified":
                    found.append((ref, line))
                    tagged = True
        if tagged or not _VERIFIED_LABEL_RE.search(line):
            continue
        cited = [ref for ref in (f"C{n}" for n in _CITATION_ID_RE.findall(line)) if ref in claims]
        if cited and all(claims[ref].status.value != "verified" for ref in cited):
            found.append((cited[0], line))
    return found


def _conflict_scopes(report_md: str) -> list[tuple[str, bool]]:
    """Each line with whether CONFLICT is disclosed for it: on the line itself,
    in its section heading, or in the lead-in of the list it belongs to (the
    `[CONFLICT] register` the runbooks require). Source-log rows are a register
    of provenance, not findings: a conflict is disclosed where it is reported."""
    out: list[tuple[str, bool]] = []
    heading, lead_in = "", ""
    for line in report_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading, lead_in = stripped, ""
            out.append((line, True))
            continue
        # list items and table rows (separator rows included) belong to the lead-in above them
        bullet = bool(re.match(r"^([-*+]|\d+[.)])\s", stripped)) or stripped.startswith("|")
        if stripped and not bullet:
            lead_in = stripped
        elif stripped.startswith("|") and not re.fullmatch(r"[|\s:-]+", stripped) and _register(stripped) \
                and not _cited(stripped):
            # a table header row "| # | [CONFLICT] | Sources |" is the register's lead-in (B-055)
            lead_in = stripped
        disclosed = (_CONFLICT_TAG_RE.search(stripped) is not None or _register(heading)
                     or (bullet and _register(lead_in))
                     or _SOURCE_LOG_HEADING_RE.match(heading) is not None)
        out.append((line, disclosed))  # a blank line keeps the lead-in: "Register:\n\n- C1 …"
    return out


def _figures(sentence: str) -> list[tuple[float, bool]]:
    """Figures a sentence states, as (value, is_percent), by the writer lint's own
    definition of a metric (`_NUMBER_RE`): a bare number in a name ("Fortune
    500"), a citation, a date or an error band (±n%) is not a figure."""
    text = _CITATION_BLOCK_RE.sub(" ", sentence)
    text = _DATE_RE.sub(" ", text)
    text = re.sub(r"±\s*\d+(?:\.\d+)?\s*%?", " ", text)
    figures = []
    matches = {m.start(): m for m in _NUMBER_RE.finditer(text)}
    for m in _SCALED_RE.finditer(text):
        matches.setdefault(m.start(), m)
    for start in sorted(matches):
        match = matches[start]
        token = match.group(0).rstrip()
        number = float(_LEADING_NUMBER_RE.search(token).group(0).replace(",", ""))
        scale = _SCALE.get(token[-1], 1.0)
        # "$4B", "$30K", "$4.2 million": the scale right after the number
        word = _SCALE_WORD_RE.match(text, match.end()) if scale == 1.0 else None
        if word:
            scale = _SCALE[word.group(1).lower()] if word.group(1) else _LETTER_SCALE[word.group(2).lower()]
        if token.lower().endswith(("thousand", "million", "billion", "bn")):
            scale = _SCALE[re.search(r"(thousand|million|billion|bn)$", token.lower()).group(1)]
        figures.append((number * scale, token.endswith("%")))
    return figures


def _numbers(sentence: str) -> list[tuple[float, bool]]:
    """Bare numbers in a sentence — outside citations, dates and metric figures
    (a number inside "$12M" is 12 million, not 12)."""
    text = _DATE_RE.sub(" ", _CITATION_BLOCK_RE.sub(" ", sentence))
    spans = [m.span() for rx in (_NUMBER_RE, _SCALED_RE) for m in rx.finditer(text)]
    return [(float(m.group(0).replace(",", "")), False) for m in _LEADING_NUMBER_RE.finditer(text)
            if not any(a <= m.start() < b for a, b in spans)]


def _matches(figure: tuple[float, bool], value: float) -> bool:
    """1 % tolerance. The sign is not compared: the number patterns drop a leading
    minus ("-1.06%", "DKK -14.7 bn") and prose states a fall as "declined 1.06%"
    (B-055). A bare figure of 1,000 or more may be in its table column's unit:
    12,000 in a "DKK m" column is the claim's 12 billion."""
    number, percent = abs(figure[0]), figure[1]
    value = abs(value)
    candidates = [value, value * 100] if percent else [value]
    if not percent and number >= 1000:
        # only a figure in the thousands or more: "$4" for a $4B claim is a lost
        # scale letter, the defect value_mismatch exists for
        candidates += [value / scale for scale in (1e3, 1e6, 1e9)]
    return any(abs(number - v) <= max(abs(v) * 0.01, 1e-9) for v in candidates)


_TYPOGRAPHY = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'", "“": '"', "”": '"'})


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_TYPOGRAPHY)).strip().lower()


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s", "e", "ly"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


_WORD_RE = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")


def _backed(quoted: str, claim: Any) -> bool:
    """A quotation is backed by its claim when it is in the claim's quote or text,
    or when at least 70 % of its word stems are (a headline or a phrase restated
    in the claim's words). A sentence may also quote a source's title beside the backed quote:
    the check asks that the citation back at least one quotation."""
    haystack = _norm(" ".join(filter(None, [claim.quote, claim.claim])))
    if _norm(quoted) in haystack:
        return True
    words = [_stem(w) for w in _WORD_RE.findall(_norm(quoted))]
    known = {_stem(w) for w in _WORD_RE.findall(haystack)}
    return bool(words) and sum(w in known for w in words) / len(words) >= 0.7


def code_defects(report_md: str, ledger: Ledger, checkpoint: Any = None) -> list[dict[str, str]]:
    """Defects the code proves from the report, the ledger and the checkpoint —
    never a judgement call. Each one vetoes the judge's pass (W6-T1):

    - missing_ref — a citation names no ledger claim;
    - quote_not_in_ledger — a sentence quotes a source (three words or more, not
      a search phrase) and none of its quotations is backed by any claim it
      cites (`_backed`);
    - value_mismatch — a sentence citing only numeric claims states a metric
      figure, and no number in it is any cited claim's value (1 % tolerance);
      a figure marked "derived" (the writer's rule; "derived from" is not the
      mark) is exempt; a non-numeric claim carries the numbers in its text;
    - conflict_hidden — a claim in status conflict is cited on a line that does
      not carry the writer's upper-case CONFLICT tag, under a heading or list
      lead-in that is not a conflict register (`_conflict_scopes`; rows under a
      "Source log" heading excepted);
    - status_mislabel — a citation tagged VERIFIED whose claim the ledger does
      not hold as verified (CORE-09);
    - partial_undisclosed — a partial run that does not say "partial" before its
      first section (`writer.partial_disclosed`, the rule the orchestrator
      enforces on report.md).
    """
    claims = {c.id: c for c in ledger.claims}
    defects: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, claim: str, text: str) -> None:
        if (kind, claim) not in seen:
            seen.add((kind, claim))
            defects.append({"kind": kind, "claim": claim, "text": text.strip()[:200]})

    for ref in lint_report(report_md, ledger).missing_refs:
        add("missing_ref", ref, f"[{ref}] is not in the ledger")
    for ref, line in _status_mislabels(report_md, claims):
        add("status_mislabel", ref, line)
    for line, disclosed in _conflict_scopes(report_md):
        if disclosed:
            continue
        for ref in _cited(line):
            if ref in claims and claims[ref].status.value == "conflict":
                add("conflict_hidden", ref, line)
    for sentence in _sentences(report_md):
        cited = [claims[ref] for ref in _cited(sentence) if ref in claims]
        if not cited or len(cited) != len(_cited(sentence)):
            continue  # an unknown citation is missing_ref's
        quotations = _quotations(sentence)
        if quotations and not any(_backed(q, c) for q in quotations for c in cited):
            add("quote_not_in_ledger", cited[0].id, sentence)
        value_cited = [claims[ref] for ref in _cited(_CONFLICT_REF_RE.sub(" ", sentence)) if ref in claims]
        values = _claim_values(value_cited)
        figures = _figures(_LABEL_FIGURE_RE.sub(" ", sentence))
        # A metric figure (the writer lint's definition) none of the cited values
        # matches — a bare number may carry the value ("interest 36 [C18]"), and a
        # figure marked "derived" (not "derived from") is the writer's computed one.
        if (figures and values and not _DERIVED_RE.search(sentence) and not _ASSUMPTION_RE.search(sentence)
                and not any(_matches(f, v) for f in figures + _numbers(sentence) for v in values)):
            add("value_mismatch", value_cited[0].id, sentence)
    if checkpoint is not None and checkpoint.partial and not partial_disclosed(report_md):
        add("partial_undisclosed", "", next((line for line in report_md.splitlines() if line.strip()),
                                            "(empty report head)"))
    return defects
