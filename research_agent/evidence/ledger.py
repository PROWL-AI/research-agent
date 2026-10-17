"""Evidence ledger: every fact in a report traces to a claim here.

Schema 2 (wave 3, KA-07/08/09, B-007). A claim's status is a pure function of
its subject group, recomputed over the whole group on every add and on load —
never set incrementally from the claim that happened to arrive last:

* **conflict** — the group's valued claims carry two or more distinct
  normalized (value, unit) pairs. Every valued claim in the group is in
  conflict, whatever arrives later; a valueless claim neither corroborates nor
  resolves one.
* **verified** — either the claim's quote was found in its stored raw and its
  value occurs inside that quote (``verification.method == "span"``), or two
  or more agreeing valued claims carry distinct *known* independence keys
  (``"corroboration"``: a publisher's registrable domain, or a data provider;
  see :mod:`research_agent.evidence.source`).
* **assumed** — everything else, with the reason in ``verification.detail``.

An LLM's word is never verification: the extractor's old ``verbatim`` flag is
gone from the model; a v1 claim that carried it without a quote loads as
``assumed`` with the detail ``"v1 verbatim without quote"``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from research_agent.evidence import source as _source
from research_agent.events import emit

log = logging.getLogger(__name__)

#: Written into every ledger.json; load() refuses dicts without a claims key,
#: so this is a forward-compat marker rather than a migration machinery.
SCHEMA_VERSION = 2


class LedgerError(Exception):
    pass


class ClaimStatus(str, Enum):
    verified = "verified"
    assumed = "assumed"
    conflict = "conflict"


#: Extraction-time quote checks a claim can carry (``Claim.quote_check``).
QUOTE_NOT_FOUND = "quote not found in stored raw"
QUOTE_V1_VERBATIM = "v1 verbatim without quote"
QUOTE_TRANSFORM = "transform output is an LLM note, not a source"
QUOTE_RAW_MISMATCH = "stored raw does not match its recorded sha256"


class SourceIdentity(BaseModel):
    """Where the data came from — derived, never trusted from the extractor."""

    delivery_tool: str
    origin_url: str | None = None
    publisher: str | None = None
    document_sha256: str | None = None
    #: None = unknown: never counts toward corroboration.
    independence_key: str | None = None


def _identity(tool: str, url: str | None, document_sha256: str | None) -> SourceIdentity:
    return SourceIdentity(
        delivery_tool=tool,
        origin_url=_source.normalize_url(url),
        publisher=_source.publisher(url),
        document_sha256=document_sha256,
        independence_key=_source.independence_key(tool, url),
    )


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
    step_id: str | None = None
    #: The exact text the extractor says it read, and where it was found in the
    #: stored raw text (offsets into source.flatten_text of that raw).
    quote: str | None = None
    quote_span: tuple[int, int] | None = None
    #: Why a quote did not verify, recorded at extraction (QUOTE_* constants).
    quote_check: str | None = None
    source: SourceIdentity | None = None
    #: Derived by Ledger.recompute: {"method": span|corroboration|none, "detail": str}.
    verification: dict[str, str] = Field(default_factory=lambda: {"method": "none", "detail": "not yet computed"})
    status: ClaimStatus = ClaimStatus.assumed

    @model_validator(mode="before")
    @classmethod
    def _from_v1(cls, data: Any) -> Any:
        # Schema 1 carried `verbatim: bool` straight from the extractor LLM and
        # turned it into `verified` (KA-08). It is read once, here, and never
        # persisted again: without a quote nothing backs it.
        if isinstance(data, dict) and "verbatim" in data:
            data = dict(data)
            verbatim = bool(data.pop("verbatim"))
            if verbatim and not data.get("quote") and not data.get("quote_check"):
                data["quote_check"] = QUOTE_V1_VERBATIM
        return data

    @model_validator(mode="after")
    def _derive_source(self) -> "Claim":
        if self.source is None:
            self.source = _identity(self.source_tool, self.source_url, None)
        return self

    @field_validator("value")
    @classmethod
    def _value_must_be_finite(cls, value: Any) -> Any:
        # json.loads accepts NaN/Infinity literals from the extractor LLM, and
        # pydantic would take them: a NaN normalises to 'nan' in _norm_value,
        # so two NaN claims would falsely "corroborate" each other.
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("claim value must be a finite number")
        return value

    @property
    def span_verified(self) -> bool:
        """The quote is in the stored raw and the value is inside the quote."""
        return (
            self.quote_span is not None
            and bool(self.quote)
            and _source.value_in_quote(self.value, self.quote or "")
        )


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
        self.recompute_all(announce=False)

    @classmethod
    def load(cls, path: Path) -> "Ledger":
        if not path.is_file():
            return cls(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "claims" not in data:
            # A dict without claims is not an empty ledger — it is a foreign or
            # truncated file. Silently loading it as empty lets a resume append
            # a report with zero evidence over a full raw/ directory.
            log.warning("ledger at %s has no 'claims' key — refusing to load it as empty", path)
            raise LedgerError(f"ledger at {path} is not a ledger file (no 'claims' key)")
        claims = [Claim.model_validate(item) for item in data.get("claims", [])]
        # Statuses on disk are never trusted: a v1 ledger was computed by the
        # incremental rules, so every load recomputes with the current ones.
        return cls(path, claims)

    def save(self) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "claims": [c.model_dump(mode="json") for c in self.claims],
        }
        _atomic_write_text(
            self.path, json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
        )

    def remove_ids(self, claim_ids: list[str]) -> int:
        """Drop the claims a step's earlier extraction produced (their ids are
        recorded on the step), so extracting it again replaces, never duplicates.
        The groups they belonged to are recomputed: a removed claim must not
        leave its peers verified or in conflict on its account."""
        drop = set(claim_ids)
        gone = [c for c in self.claims if c.id in drop]
        self.claims = [c for c in self.claims if c.id not in drop]
        for key in {_norm_subject(c.subject) for c in gone} - {None}:
            self.recompute(key)
        return len(gone)

    def _next_id(self) -> str:
        highest = 0
        for claim in self.claims:
            if claim.id.startswith("C") and claim.id[1:].isdigit():
                highest = max(highest, int(claim.id[1:]))
        return f"C{highest + 1}"

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
        step_id: str | None = None,
        quote: str | None = None,
        quote_span: tuple[int, int] | None = None,
        quote_check: str | None = None,
        document_sha256: str | None = None,
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
            step_id=step_id,
            quote=quote,
            quote_span=quote_span,
            quote_check=quote_check,
            source=_identity(source_tool, source_url, document_sha256),
        )
        self.claims.append(entry)
        self.recompute(_norm_subject(subject), only=None if subject else entry)
        return entry

    # ── status: one pure function of the group ───────────────────────────────

    def recompute_all(self, *, announce: bool = False) -> None:
        keys = {_norm_subject(c.subject) for c in self.claims}
        for key in keys:
            self.recompute(key, announce=announce)

    def recompute(self, subject_key: str | None, *, only: Claim | None = None,
                  announce: bool = True) -> None:
        """Recompute every claim of one subject group from the group alone.

        Claims without a subject form no group — each stands on its own quote.
        Order-independent by construction: nothing here reads a previous
        status except to announce a change."""
        if subject_key is None:
            group = [only] if only is not None else [c for c in self.claims if _norm_subject(c.subject) is None]
            for claim in group:
                self._set(claim, *_alone(claim), announce=announce)
            return
        group = [c for c in self.claims if _norm_subject(c.subject) == subject_key]
        if not group:
            return
        valued = [c for c in group if c.value is not None]
        pairs = {_norm_pair(c.value, c.unit) for c in valued}
        if len(pairs) >= 2:
            values = sorted({f"{v}{(' ' + u) if u else ''}" for v, u in pairs})
            # Announced when the disagreement itself changes, not per arrival:
            # a third claim repeating one side adds no news.
            before = {_norm_pair(c.value, c.unit) for c in valued if c.status == ClaimStatus.conflict}
            newly = before != pairs
            for claim in valued:
                method = "span" if claim.span_verified else "none"
                self._set(claim, ClaimStatus.conflict, method,
                          f"group disagrees: {' vs '.join(values)}", announce=False)
            for claim in group:
                if claim.value is None:
                    self._set(claim, *_alone(claim), announce=announce)
            if newly and announce:
                emit(log, "claim.conflict", logging.INFO, subject=subject_key, values=values)
            return
        keys = sorted({c.source.independence_key for c in valued
                       if c.source is not None and c.source.independence_key})
        for claim in group:
            if claim.span_verified:
                self._set(claim, ClaimStatus.verified, "span",
                          f"quote found in stored raw at {list(claim.quote_span or ())}", announce=announce)
            elif claim.value is not None and len(keys) >= 2:
                self._set(claim, ClaimStatus.verified, "corroboration",
                          f"{len(keys)} independent sources agree: {', '.join(keys)}", announce=announce)
            else:
                self._set(claim, *_alone(claim), announce=announce)

    @staticmethod
    def _set(claim: Claim, status: ClaimStatus, method: str, detail: str, *, announce: bool) -> None:
        became_verified = status == ClaimStatus.verified and claim.status != ClaimStatus.verified
        claim.status = status
        claim.verification = {"method": method, "detail": detail}
        if became_verified and announce:
            emit(log, "claim.verified", logging.INFO, claim_id=claim.id, method=method)

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
                "subject": c.subject,
                "status": c.status.value,
                "source_tool": c.source_tool,
                "verification": c.verification["method"],
            }
            for c in self.claims
        ]
        return json.dumps(rows, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _alone(claim: Claim) -> tuple[ClaimStatus, str, str]:
    """The status a claim earns on its own: its quote, or nothing."""
    if claim.span_verified:
        return ClaimStatus.verified, "span", f"quote found in stored raw at {list(claim.quote_span or ())}"
    if claim.quote_check:
        return ClaimStatus.assumed, "none", claim.quote_check
    if claim.quote and claim.quote_span is not None:
        return ClaimStatus.assumed, "none", "value is not inside the quote"
    if claim.quote:
        return ClaimStatus.assumed, "none", "quote not checked against a stored raw"
    return ClaimStatus.assumed, "none", "single source, no quote"
