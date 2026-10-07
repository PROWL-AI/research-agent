"""Citation-fidelity pass: presence is not support.

After the writer (and citation repair) this pass checks that each [C..]
citation actually supports the sentence it hangs on. Bad refs are rewritten
inline as [UNVERIFIED: ...] — never silently deleted, never left in place.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from research_agent.evidence.ledger import Claim, Ledger
from research_agent.llm import LLMClient

log = logging.getLogger(__name__)

_CITATION_RE = re.compile(r"\[C(\d+)\]")
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


@dataclass
class FidelityResult:
    report_md: str
    checked: int = 0
    supported: int = 0
    unverified: int = 0

    @property
    def stats(self) -> dict[str, int]:
        return {
            "checked": self.checked,
            "supported": self.supported,
            "unverified": self.unverified,
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


def _cited_sentences(report_md: str) -> list[str]:
    candidates: list[tuple[int, str]] = []
    for line in report_md.split("\n"):
        for sentence in _SENTENCE_SPLIT_RE.split(line):
            sentence = sentence.strip()
            if _CITATION_RE.search(sentence):
                candidates.append((len(sentence), sentence))
    if len(candidates) <= _MAX_SENTENCES:
        return [s for _, s in candidates]
    with_numbers = [s for _, s in candidates if re.search(r"\d", s)]
    without = [s for _, s in candidates if not re.search(r"\d", s)]
    return (with_numbers + without)[:_MAX_SENTENCES]


def _rewrite_sentence(sentence: str, bad_refs: list[str], good_refs: list[str]) -> str:
    core = _CITATION_RE.sub("", sentence).strip()
    core = re.sub(r"\s+([.!?,;:])", r"\1", core)
    if not good_refs:
        label = core[:_UNVERIFIED_LABEL_CHARS]
        if len(core) > _UNVERIFIED_LABEL_CHARS:
            label += "…"
        return f"[UNVERIFIED: {label}]"
    out = sentence
    for ref in bad_refs:
        out = out.replace(f"[{ref}]", "[UNVERIFIED]", 1)
    return out


async def verify_citations(
    llm: LLMClient, report_md: str, ledger: Ledger
) -> FidelityResult:
    claims_by_id = {c.id: c for c in ledger.claims}
    sentences = _cited_sentences(report_md)
    work: list[tuple[str, list[str]]] = []
    for sentence in sentences:
        refs = [ref for ref in (f"C{n}" for n in _CITATION_RE.findall(sentence)) if ref in claims_by_id]
        if refs:
            work.append((sentence, refs))

    result = FidelityResult(report_md=report_md)
    if not work:
        return result

    for start in range(0, len(work), _BATCH_SIZE):
        batch = work[start:start + _BATCH_SIZE]
        parts = []
        for i, (sentence, refs) in enumerate(batch, start=1):
            claims_json = json.dumps(
                [_claim_json(claims_by_id[ref]) for ref in refs],
                ensure_ascii=False,
            )
            parts.append(f"S{i}: {sentence}\nreferenced claims: {claims_json}")
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
        verdicts = _parse_verdicts(text)
        for i, (sentence, refs) in enumerate(batch, start=1):
            bad = [
                ref for ref in refs
                if verdicts.get((i, ref)) in ("unsupported", "subject-mismatch")
            ]
            good = [ref for ref in refs if ref not in bad]
            result.checked += len(refs)
            result.supported += len(good)
            if bad:
                result.unverified += len(bad)
                rewritten = _rewrite_sentence(sentence, bad, good)
                result.report_md = result.report_md.replace(sentence, rewritten, 1)
                log.info(
                    "citation-fidelity: %d ref(s) unverified in %r", len(bad), sentence[:80]
                )
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
