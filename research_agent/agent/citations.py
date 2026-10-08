"""Citation-fidelity pass: presence is not support.

After the writer (and citation repair) this pass checks that each [C..]
citation actually supports the sentence it hangs on. Bad refs are rewritten
inline as [UNVERIFIED: ...] — never silently deleted, never left in place.
Composite citations (`[C1, C2]`) are first-class: every id in the bracket
block is checked and rewritten individually.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from research_agent.evidence.ledger import Claim, Ledger
from research_agent.llm import LLMClient

log = logging.getLogger(__name__)

#: A bracket block holding at least one claim id: [C1], [C1, C2], [C3][C4].
_CITATION_BLOCK_RE = re.compile(r"\[[^\]]*?\bC\d+[^\]]*?\]")
_CITATION_ID_RE = re.compile(r"C(\d+)")
_ANY_BRACKET_RE = re.compile(r"\[[^\]]*\]")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_MAX_SENTENCES = 40
_BATCH_SIZE = 10
_UNVERIFIED_LABEL_CHARS = 160

_SYSTEM = """\
You are a citation-fidelity checker for a research report (citation-fidelity
pass). For each numbered sentence and each [C..] reference in it, decide
whether the referenced ledger claim SUPPORTS the sentence's statement.

Verdicts:
- supported: the claim is about the same entity and metric as the sentence.
- unsupported: the claim does not back the sentence's statement.
- subject-mismatch: the claim is about a different entity or metric than the
  sentence uses it for.

Output JSON: {"verdicts": [{"s": <sentence number>, "ref": "C<n>",
"verdict": "supported|unsupported|subject-mismatch"}]} covering EVERY reference
in every sentence."""


def citation_ids(text: str) -> list[str]:
    """Every claim id cited in the text, composite blocks included."""
    out: list[str] = []
    for block in _CITATION_BLOCK_RE.findall(text):
        out.extend(f"C{n}" for n in _CITATION_ID_RE.findall(block))
    return out


@dataclass
class FidelityResult:
    report_md: str
    checked: int = 0
    supported: int = 0
    unverified: int = 0
    unchecked: int = 0

    @property
    def stats(self) -> dict[str, int]:
        return {
            "checked": self.checked,
            "supported": self.supported,
            "unverified": self.unverified,
            "unchecked": self.unchecked,
        }


def _claim_json(claim: Claim) -> dict[str, Any]:
    return {
        "id": claim.id,
        "claim": claim.claim,
        "value": claim.value,
        "unit": claim.unit,
        "subject": claim.subject,
        "status": claim.status.value,
        "source_tool": claim.source_tool,
    }


def _cited_sentences(report_md: str) -> list[tuple[int, int, str]]:
    """Cited sentences as (start, end, text) spans — replacements must happen
    by position, not by text: the same sentence can legitimately appear twice
    (summary + body), and a text replace always lands on the first one.

    Splitting is by paragraph first: a line break inside a sentence is prose,
    not a boundary, and a fragment judged without its other half reads as
    unsupported.
    """
    candidates: list[tuple[int, int, str]] = []
    offset = 0
    for paragraph in _PARAGRAPH_SPLIT_RE.split(report_md):
        para_start = report_md.find(paragraph, offset)
        if para_start < 0:
            continue
        offset = para_start + len(paragraph)
        cursor = para_start
        for sentence in _SENTENCE_SPLIT_RE.split(paragraph):
            idx = report_md.find(sentence, cursor, offset)
            if idx < 0:
                continue
            cursor = idx + len(sentence)
            stripped = sentence.strip()
            if _CITATION_BLOCK_RE.search(stripped):
                candidates.append((idx, idx + len(sentence), stripped))
    if len(candidates) <= _MAX_SENTENCES:
        return candidates
    dropped = len(candidates) - _MAX_SENTENCES
    # Prefer digit-carrying sentences — but strip bracket blocks first, or the
    # citation's own id makes every sentence "numeric" and the priority is a
    # no-op.
    def _has_real_number(s: str) -> bool:
        return bool(re.search(r"\d", _ANY_BRACKET_RE.sub("", s)))

    with_numbers = [c for c in candidates if _has_real_number(c[2])]
    without = [c for c in candidates if not _has_real_number(c[2])]
    log.warning(
        "citation-fidelity: %d cited sentences exceed the %d-sentence budget; "
        "%d tail sentences unchecked",
        len(candidates), _MAX_SENTENCES, dropped,
    )
    return (with_numbers + without)[:_MAX_SENTENCES]


def _rewrite_sentence(sentence: str, bad_refs: list[str], good_refs: list[str]) -> str:
    if not good_refs:
        core = _CITATION_BLOCK_RE.sub("", sentence).strip()
        core = re.sub(r"\s+([.!?,;:])", r"\1", core)
        label = core[:_UNVERIFIED_LABEL_CHARS]
        if len(core) > _UNVERIFIED_LABEL_CHARS:
            label += "…"
        return f"[UNVERIFIED: {label}]"
    out = sentence
    for ref in bad_refs:
        # EVERY occurrence of a bad ref goes — replacing only the first leaves
        # a ref we know is unsupported standing later in the same sentence.
        out = out.replace(f"[{ref}]", "[UNVERIFIED]")
        # The composite form: swap the bare token inside the bracket block.
        out = re.sub(rf"\b{re.escape(ref)}\b", "UNVERIFIED", out)
    return out


async def verify_citations(
    llm: LLMClient, report_md: str, ledger: Ledger
) -> FidelityResult:
    claims_by_id = {c.id: c for c in ledger.claims}
    spans = _cited_sentences(report_md)
    work: list[tuple[int, int, str, list[str]]] = []
    for start, end, sentence in spans:
        refs = [ref for ref in dict.fromkeys(citation_ids(sentence)) if ref in claims_by_id]
        if refs:
            work.append((start, end, sentence, refs))

    result = FidelityResult(report_md=report_md)
    if not work:
        return result

    rewrites: list[tuple[int, int, str]] = []
    for batch_start in range(0, len(work), _BATCH_SIZE):
        batch = work[batch_start:batch_start + _BATCH_SIZE]
        parts = []
        for i, (_, _, sentence, refs) in enumerate(batch, start=1):
            claims_json = json.dumps(
                [_claim_json(claims_by_id[ref]) for ref in refs],
                ensure_ascii=False,
            )
            parts.append(f"S{i}: {sentence}\nreferenced claims: {claims_json}")
        try:
            text = await llm.complete(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": "\n\n".join(parts)},
                ],
                tier="cheap",
                json_mode=True,
                max_tokens=2000,
                temperature=0.0,
            )
        except Exception as exc:
            # A failed batch is unchecked, never "supported": silence must not
            # report as a clean pass.
            result.unchecked += sum(len(refs) for _, _, _, refs in batch)
            log.warning("citation-fidelity: batch skipped after LLM failure: %s", exc)
            continue
        verdicts = _parse_verdicts(text)
        for i, (start, end, sentence, refs) in enumerate(batch, start=1):
            bad = [
                ref for ref in refs
                if verdicts.get((i, ref)) in ("unsupported", "subject-mismatch")
            ]
            returned = [ref for ref in refs if (i, ref) in verdicts]
            good = [ref for ref in returned if ref not in bad]
            result.checked += len(returned)
            result.supported += len(good)
            result.unchecked += len(refs) - len(returned)
            if bad:
                result.unverified += len(bad)
                rewrites.append((start, end, _rewrite_sentence(sentence, bad, good)))
                log.info(
                    "citation-fidelity: %d ref(s) unverified in %r", len(bad), sentence[:80]
                )
    # Apply rewrites back-to-front so earlier spans stay valid.
    for start, end, rewritten in sorted(rewrites, reverse=True):
        result.report_md = result.report_md[:start] + rewritten + result.report_md[end:]
    return result


def _parse_verdicts(text: str) -> dict[tuple[int, str], str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            payload = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            return {}
    out: dict[tuple[int, str], str] = {}
    for item in payload.get("verdicts", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        try:
            key = (int(item.get("s")), str(item.get("ref")))
        except (TypeError, ValueError):
            continue
        verdict = str(item.get("verdict", "")).strip().lower()
        if verdict in ("supported", "unsupported", "subject-mismatch"):
            out[key] = verdict
    return out
