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

CHART_FENCE_RE = re.compile(r"```chart\s*\n(.*?)\n\s*```", re.DOTALL)

MAX_CHARTS_PER_REPORT = 3
_CHART_TYPES = ("bar", "line")


@dataclass
class ChartSpec:
    type: str
    title: str
    labels: list[str]
    values: list[float]
    claim_refs: list[str]


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace(" ", ""))
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
