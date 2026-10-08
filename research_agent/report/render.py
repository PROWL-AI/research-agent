"""Self-contained HTML export for a finished run."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import markdown as md_lib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from research_agent.charts import substitute_charts
from research_agent.evidence.ledger import Ledger
from research_agent.evidence.store import ArtifactStore

log = logging.getLogger(__name__)

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_MD_EXTENSIONS = ["tables", "fenced_code", "toc"]

_jinja = Environment(
    loader=FileSystemLoader(str(_TEMPLATES)),
    autoescape=select_autoescape(["html", "htm", "xml", "j2"]),
)


class RenderError(Exception):
    pass


def _stats_rows(stats: dict[str, Any]) -> list[tuple[str, str]]:
    rows = []
    for key, label in (
        ("data_calls", "Data tool calls"),
        ("claims", "Ledger claims"),
        ("cost_usd", "Cost (USD)"),
        ("duration_s", "Duration (s)"),
        ("lint_issues_after", "Lint issues (final)"),
    ):
        value = stats.get(key)
        if value is not None:
            rows.append((label, str(value)))
    return rows


def _escape_raw_html(text: str) -> str:
    """Neutralise raw HTML in LLM-produced markdown.

    python-markdown passes raw HTML through untouched, and the report body is
    generated from scraped web content — without this a scraped ``<script>``
    or ``<img onerror>`` would ship inside our "self-contained" HTML export.
    Only ``&`` and ``<`` are escaped: ``>`` must stay for blockquotes, and
    charts inject their trusted SVG after this step.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;")


def render_report_html(
    report_md: str,
    ledger: Ledger,
    *,
    runbook: str,
    brief: dict[str, Any],
    stats: dict[str, Any],
    partial: bool = False,
) -> str:
    with_charts = substitute_charts(_escape_raw_html(report_md), ledger)
    md = md_lib.Markdown(extensions=_MD_EXTENSIONS)
    body = md.convert(with_charts)
    subject_parts: list[str] = []
    for value in brief.values():
        if isinstance(value, list):
            subject_parts.extend(str(item) for item in value)
        elif value:
            subject_parts.append(str(value))
    subject = ", ".join(subject_parts) or "(no subject)"
    template = _jinja.get_template("base.html.j2")
    return template.render(
        title=f"{runbook} — research report",
        runbook=runbook,
        subject=subject,
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        partial=partial,
        stats_rows=_stats_rows(stats),
        toc=md.toc,
        body=body,
    )


def render_run(run_dir: Path) -> Path:
    store = ArtifactStore(run_dir)
    checkpoint = store.load_checkpoint()
    if checkpoint is None:
        raise RenderError(f"run at {run_dir} has no checkpoint.json")
    report_path = run_dir / "report.md"
    if not report_path.is_file():
        raise RenderError(f"run at {run_dir} has no report.md")
    ledger = Ledger.load(run_dir / "ledger.json")
    stats = dict(checkpoint.stats)
    stats.setdefault("data_calls", checkpoint.counters.get("data_calls", 0))
    if checkpoint.counters.get("cost_usd") is not None:
        stats.setdefault("cost_usd", checkpoint.counters["cost_usd"])
    html_text = render_report_html(
        report_path.read_text(encoding="utf-8"),
        ledger,
        runbook=checkpoint.runbook,
        brief=checkpoint.brief,
        stats=stats,
        partial=checkpoint.partial,
    )
    out_path = run_dir / "report.html"
    out_path.write_text(html_text, encoding="utf-8")
    return out_path
