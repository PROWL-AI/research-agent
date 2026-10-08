"""Evidence ledger: every fact in a report traces to a claim here."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


class ClaimStatus(str, Enum):
    verified = "verified"
    assumed = "assumed"
    conflict = "conflict"


class Claim(BaseModel):
    id: str
    claim: str
    value: str | float | int | None = None
    unit: str | None = None
    subject: str | None = None
    source_tool: str
    source_url: str | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_ref: str | None = None
    verbatim: bool = False
    status: ClaimStatus = ClaimStatus.assumed


_SUBJECT_STOPWORDS = frozenset({"the", "a", "an", "of", "per"})
_SUBJECT_NONALNUM_RE = re.compile(r"[^a-z0-9.\s]+")


def _norm_subject(subject: str | None) -> str | None:
    """Canonical subject key for corroboration.

    The extractor LLM invents the subject per step, so byte-equality almost
    never fires ("example.com monthly organic traffic" vs "example.com organic
    traffic monthly"). Token-sorted, punctuation-free, stopword-stripped keys
    make the same metric from two calls land on one key — while keeping
    temporal/quantitative tokens, because "monthly traffic" and "yearly
    traffic" are different metrics.
    """
    if subject is None:
        return None
    tokens = _SUBJECT_NONALNUM_RE.sub(" ", subject.lower()).split()
    tokens = sorted(t for t in tokens if t not in _SUBJECT_STOPWORDS)
    return " ".join(tokens) or None


def _norm_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip().lower().replace(",", "").replace(" ", "").lstrip("$€£")


def _norm_pair(value: Any, unit: str | None) -> tuple[str, str]:
    """Value comparisons must include the unit: "5" (%) vs "5" (M) is a
    conflict, not a corroboration."""
    return (_norm_value(value), (unit or "").strip().lower())


def _atomic_write_text(path: Path, text: str) -> None:
    """Crash-safe write: a truncated ledger/checkpoint is an unrecoverable run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class Ledger:
    def __init__(self, path: Path, claims: list[Claim] | None = None) -> None:
        self.path = path
        self.claims: list[Claim] = list(claims) if claims else []

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        if not path.is_file():
            return cls(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        claims = [Claim.model_validate(item) for item in data.get("claims", [])]
        return cls(path, claims)

    def save(self) -> None:
        payload = {"claims": [c.model_dump(mode="json") for c in self.claims]}
        _atomic_write_text(self.path, json.dumps(payload, indent=2, ensure_ascii=False))

    def _next_id(self) -> str:
        highest = 0
        for claim in self.claims:
            if claim.id.startswith("C") and claim.id[1:].isdigit():
                highest = max(highest, int(claim.id[1:]))
        return f"C{highest + 1}"

    def _peers(self, subject: str | None) -> list[Claim]:
        normalized = _norm_subject(subject)
        if normalized is None:
            return []
        return [c for c in self.claims if _norm_subject(c.subject) == normalized]

    def add(
        self,
        *,
        claim: str,
        value: str | float | int | None = None,
        unit: str | None = None,
        subject: str | None = None,
        source_tool: str,
        source_url: str | None = None,
        raw_ref: str | None = None,
        verbatim: bool = False,
    ) -> Claim:
        entry = Claim(
            id=self._next_id(),
            claim=claim,
            value=value,
            unit=unit,
            subject=subject,
            source_tool=source_tool,
            source_url=source_url,
            raw_ref=raw_ref,
            verbatim=verbatim,
        )
        self._apply_status(entry)
        self.claims.append(entry)
        return entry

    def _apply_status(self, entry: Claim) -> None:
        peers = self._peers(entry.subject)
        entry_pair = _norm_pair(entry.value, entry.unit)

        contradictory = [p for p in peers if _norm_pair(p.value, p.unit) != entry_pair]
        if contradictory:
            entry.status = ClaimStatus.conflict
            for peer in peers:
                # A verbatim quote keeps its verified status — it is what the
                # source literally said; the conflict is recorded on the rest.
                if not peer.verbatim:
                    peer.status = ClaimStatus.conflict
            log.info(
                "ledger conflict on subject %r: %s=%r vs %s=%r",
                entry.subject, contradictory[0].id, contradictory[0].value,
                entry.id, entry.value,
            )
            return

        if entry.verbatim:
            entry.status = ClaimStatus.verified
            return

        supporting = {p.source_tool for p in peers}
        supporting.add(entry.source_tool)
        if len(supporting) >= 2:
            entry.status = ClaimStatus.verified
            for peer in peers:
                if not peer.verbatim:
                    peer.status = ClaimStatus.verified
        else:
            entry.status = ClaimStatus.assumed

    def as_prompt_json(self) -> str:
        # Compact: this lands in the writer's system prompt and in EVERY repair
        # pass — indent and source_url cost hundreds of KB at a few hundred
        # claims and buy the writer nothing it cites.
        rows = [
            {
                "id": c.id,
                "claim": c.claim,
                "value": c.value,
                "unit": c.unit,
                "status": c.status.value,
                "source_tool": c.source_tool,
                "verbatim": c.verbatim,
            }
            for c in self.claims
        ]
        return json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
