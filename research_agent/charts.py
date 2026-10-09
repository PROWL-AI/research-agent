"""Charts from ledger data only.

The writer may embed chart directives as fenced blocks:
```chart {"type": "bar"|"line", "title": "...", "labels": [...], "values": [...], "claim_refs": ["C1", ...]}```
Every value must appear in the referenced claims (exact match on the rounded
value); anything else is rejected with a note, never rendered.
"""

from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from research_agent.evidence.ledger import Claim, Ledger

log = logging.getLogger(__name__)

#: Accepts both writer forms: ```chart\n{json}\n``` and ```chart {json}\n``` —
#: the writer prompt's own example uses the same-line form, so requiring a
#: newline silently skipped validation AND rendering for exactly what we teach.
CHART_FENCE_RE = re.compile(r"```chart[ \t]*\n?(.*?)\n\s*```", re.DOTALL)

MAX_CHARTS_PER_REPORT = 3
_CHART_TYPES = ("bar", "line")


@dataclass
class ChartSpec:
    type: str
    title: str
    labels: list[str]
    values: list[float]
    claim_refs: list[str]


_SUFFIX_MULT = {"k": 1e3, "m": 1e6, "b": 1e9}
_NUMBERISH_RE = re.compile(r"^(-?\d+(?:\.\d+)?)([kKmMbB])?\+?$")


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Ledger values are str|float|int and arrive as written: "113K",
        # "$4.2M", "42 000", "12%". Mirror the writer's _NUMBER_RE forms, or a
        # correct chart is rejected as "values not in ledger".
        text = value.strip().replace(",", "").replace(" ", "")
        text = text.lstrip("$€£").rstrip("%")
        match = _NUMBERISH_RE.match(text)
        if match:
            number = float(match.group(1))
            suffix = match.group(2)
            if suffix:
                number *= _SUFFIX_MULT[suffix.lower()]
            return number
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _parse_spec(raw: str) -> ChartSpec | str:
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
        return "invalid spec JSON"
    if not isinstance(spec, dict):
        return "invalid spec JSON"
    chart_type = str(spec.get("type", ""))
    if chart_type not in _CHART_TYPES:
        return f"unknown chart type {chart_type!r}"
    labels = spec.get("labels")
    values = spec.get("values")
    refs = spec.get("claim_refs")
    if not isinstance(labels, list) or not isinstance(values, list) or not labels:
        return "labels/values must be non-empty lists"
    if len(labels) != len(values):
        return "labels/values length mismatch"
    if not isinstance(refs, list) or not refs:
        return "claim_refs must be a non-empty list"
    floats = [_to_float(v) for v in values]
    if any(v is None for v in floats):
        return "values must be numeric"
    return ChartSpec(
        type=chart_type,
        title=str(spec.get("title", "")),
        labels=[str(label) for label in labels],
        values=[v for v in floats if v is not None],
        claim_refs=[str(r) for r in refs],
    )


def _unit_kind(claim: Claim) -> str | None:
    """Coarse unit category when one is unambiguous from the claim's own
    fields: percent, currency, or plain count. None when nothing pins a
    category — an unknown must not veto a chart."""
    text = " ".join(
        str(part) for part in (claim.unit, claim.value) if part is not None
    )
    if not text:
        return None
    if "%" in text or "percent" in text.lower():
        return "percent"
    if any(symbol in text for symbol in ("$", "€", "£")):
        return "currency"
    if claim.unit:
        return "count"
    return None


def validate_against_ledger(spec: ChartSpec, ledger: Ledger) -> str | None:
    claims_by_id = {c.id: c for c in ledger.claims}
    claims: list[Claim] = []
    for ref in spec.claim_refs:
        claim = claims_by_id.get(ref)
        if claim is None:
            return f"unknown claim ref {ref}"
        claims.append(claim)
    claim_values = [
        rounded for claim in claims
        if (rounded := _to_float(claim.value)) is not None
    ]
    claim_values = [round(v, 2) for v in claim_values]
    for value in spec.values:
        if round(value, 2) not in claim_values:
            return "values not in ledger"
    kinds = {kind for kind in (_unit_kind(c) for c in claims) if kind}
    if len(kinds) > 1 and kinds & {"percent", "currency"}:
        return f"values mix incompatible units ({', '.join(sorted(kinds))})"
    # Soft check only: labels matching no referenced subject hint at a
    # label↔value misalignment, but never justify rejecting a valid chart.
    subjects = [(c.subject or c.claim or "").lower() for c in claims]
    subjects = [s for s in subjects if s]
    if subjects and not any(
        label.lower() in s or (len(s) >= 3 and s in label.lower())
        for label in spec.labels
        for s in subjects
    ):
        log.warning(
            "chart %r: no label matches any referenced claim subject",
            spec.title,
        )
    return None


def render_svg(spec: ChartSpec) -> str:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.2, 3.0))
    if spec.type == "bar":
        ax.bar(spec.labels, spec.values, color="#2f6fed")
    else:
        ax.plot(spec.labels, spec.values, marker="o", color="#2f6fed")
    if spec.title:
        ax.set_title(spec.title, fontsize=11)
    ax.tick_params(axis="x", labelsize=8, rotation=20)
    ax.tick_params(axis="y", labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buf = io.StringIO()
    fig.savefig(buf, format="svg")
    plt.close(fig)
    svg = buf.getvalue()
    lines = [
        line for line in svg.splitlines()
        if not line.startswith(("<?xml", "<!DOCTYPE", "<!--"))
    ]
    return "\n".join(lines)


def substitute_charts(report_md: str, ledger: Ledger) -> str:
    rendered = 0

    def _replace(match: re.Match) -> str:
        nonlocal rendered
        spec_or_error = _parse_spec(match.group(1))
        if isinstance(spec_or_error, str):
            return f"\n\n[chart rejected: {spec_or_error}]\n\n"
        if rendered >= MAX_CHARTS_PER_REPORT:
            return f"\n\n[chart rejected: max {MAX_CHARTS_PER_REPORT} charts per report]\n\n"
        error = validate_against_ledger(spec_or_error, ledger)
        if error is not None:
            log.info("chart rejected: %s (%s)", error, spec_or_error.title)
            return f"\n\n[chart rejected: {error}]\n\n"
        rendered += 1
        svg = render_svg(spec_or_error)
        return f'\n\n<div class="chart" data-claims="{" ".join(spec_or_error.claim_refs)}">\n{svg}\n</div>\n\n'

    return CHART_FENCE_RE.sub(_replace, report_md)
