"""Evidence ledger: every fact in a report traces to a claim here."""

from __future__ import annotations

import json
import logging
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


def _norm_subject(subject: str | None) -> str | None:
    if subject is None:
        return None
    normalized = " ".join(subject.strip().lower().split())
    return normalized or None


def _norm_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip().lower().replace(",", "").replace(" ", "")


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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"claims": [c.model_dump(mode="json") for c in self.claims]}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

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
        entry_value = _norm_value(entry.value)

        contradictory = [p for p in peers if _norm_value(p.value) != entry_value]
        if contradictory:
            entry.status = ClaimStatus.conflict
            for peer in peers:
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
        rows = [
            {
                "id": c.id,
                "claim": c.claim,
                "value": c.value,
                "unit": c.unit,
                "status": c.status.value,
                "source_tool": c.source_tool,
                "source_url": c.source_url,
                "verbatim": c.verbatim,
            }
            for c in self.claims
        ]
        return json.dumps(rows, indent=2, ensure_ascii=False)
