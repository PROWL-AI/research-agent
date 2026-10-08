import json
from pathlib import Path

import pytest

from research_agent.evidence.ledger import Ledger
from research_agent.evidence.store import ArtifactStore, Checkpoint
from research_agent.report.render import render_run

CHART_OK = '```chart\n{"type": "bar", "title": "Visits", "labels": ["a.com", "b.com"], "values": [42000, 118000], "claim_refs": ["C1", "C2"]}\n```'
CHART_BAD_VALUES = '```chart\n{"type": "bar", "title": "Visits", "labels": ["a.com"], "values": [999999], "claim_refs": ["C1"]}\n```'
CHART_BAD_LEN = '```chart\n{"type": "line", "title": "Visits", "labels": ["a.com", "b.com"], "values": [42000], "claim_refs": ["C1", "C2"]}\n```'

REPORT_TEMPLATE = """\
# Teardown

## Traffic by domain

| domain | visits/month |
|---|---|
| a.com | 42000 |
| b.com | 118000 |

a.com gets 42,000 monthly visitors [C1].

{chart}
"""


def _make_run(tmp_path: Path, run_id: str, chart_block: str) -> Path:
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.md").write_text(
        REPORT_TEMPLATE.format(chart=chart_block), encoding="utf-8"
    )
    ledger = Ledger(run_dir / "ledger.json")
    ledger.add(claim="a.com traffic", subject="a.com traffic", value=42000,
               unit="visits/month", source_tool="spyfu_get_domain_stats")
    ledger.add(claim="b.com traffic", subject="b.com traffic", value=118000,
               unit="visits/month", source_tool="dataforseo_labs_bulk_traffic_estimation")
    ledger.save()
    checkpoint = Checkpoint(
        run_id=run_id, runbook="mini-teardown", brief={"competitors": ["a.com", "b.com"]},
    )
    checkpoint.counters["data_calls"] = 7
    checkpoint.stats = {"data_calls": 7, "claims": 2, "duration_s": 12.5}
    ArtifactStore(run_dir).save_checkpoint(checkpoint)
    return run_dir


def test_html_export_self_contained_with_chart(tmp_path):
    run_dir = _make_run(tmp_path, "x1", CHART_OK)
    out_path = render_run(run_dir)
    html = out_path.read_text()

    assert out_path.name == "report.html"
    assert 'class="toc"' in html
    assert "mini-teardown" in html
    assert "a.com, b.com" in html
    assert "Data tool calls" in html
    assert "<svg" in html
    assert "<script" not in html
    assert "<link" not in html
    assert 'src="http' not in html and "src='http" not in html
    assert 'href="http' not in html


def test_chart_with_values_outside_ledger_rejected(tmp_path):
    run_dir = _make_run(tmp_path, "x2", CHART_BAD_VALUES)
    html = render_run(run_dir).read_text()
    assert "[chart rejected: values not in ledger]" in html
    assert "<svg" not in html


def test_chart_label_value_length_mismatch_rejected(tmp_path):
    run_dir = _make_run(tmp_path, "x3", CHART_BAD_LEN)
    html = render_run(run_dir).read_text()
    assert "[chart rejected: labels/values length mismatch]" in html
    assert "<svg" not in html


def test_export_cli_round_trip(tmp_path, monkeypatch, capsys):
    from research_agent.__main__ import main

    _make_run(tmp_path, "x4", CHART_OK)
    monkeypatch.chdir(tmp_path)

    assert main(["export", "x4"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.endswith("report.html")
    assert Path(out).is_file()

    assert main(["export", "x4", "--format", "md"]) == 0
    assert capsys.readouterr().out.strip().endswith("report.md")

    assert main(["export", "nope"]) == 1


async def test_orchestrator_writes_html_next_to_report(
    patched_runbooks, tmp_path: Path, fake_llm, fake_prowl
):
    from research_agent.agent.orchestrator import Orchestrator

    fake_llm.plan_payload = {
        "plan": [
            {"step": "baseline", "tool": "spyfu_get_domain_stats", "arguments": {"domain": "a.com"}}
        ]
    }
    orchestrator = Orchestrator(fake_prowl, fake_llm, runs_root=tmp_path / "runs")
    result = await orchestrator.run("mini-teardown", {"competitors": ["a.com"]}, run_id="r-html")
    html_path = Path(result.report_path).with_suffix(".html")
    assert html_path.is_file()
    assert "mini-teardown" in html_path.read_text()


class TestRawHtmlIsNeutralised:
    def test_scraped_script_does_not_reach_the_export(self, tmp_path):
        from research_agent.report.render import render_report_html
        from research_agent.evidence.ledger import Ledger

        ledger = Ledger(tmp_path / "ledger.json")
        html = render_report_html(
            'Safe text.\n\n<script>alert(1)</script>\n\n<img src=x onerror="alert(2)">',
            ledger, runbook="t", brief={}, stats={},
        )
        assert "<script>" not in html
        assert "<img src=x" not in html
        assert "&lt;script&gt;" in html
        assert "&lt;img src=x" in html

    def test_blockquotes_and_markdown_survive(self, tmp_path):
        from research_agent.report.render import render_report_html
        from research_agent.evidence.ledger import Ledger

        ledger = Ledger(tmp_path / "ledger.json")
        html = render_report_html(
            "> a quoted finding\n\n**bold** and [a link](https://x.com?a=1&b=2)",
            ledger, runbook="t", brief={}, stats={},
        )
        assert "<blockquote>" in html
        assert "<strong>bold</strong>" in html


class TestChartFenceForms:
    def test_same_line_fence_is_rendered(self, tmp_path):
        from research_agent.charts import substitute_charts
        from research_agent.evidence.ledger import Ledger

        ledger = Ledger(tmp_path / "ledger.json")
        ledger.add(claim="a.com has 100 visitors", value=100, unit="visitors", source_tool="t")
        ledger.add(claim="b.com has 200 visitors", value=200, unit="visitors", source_tool="t")
        md = ('```chart {"type": "bar", "title": "traffic", "labels": ["a", "b"], '
              '"values": [100, 200], "claim_refs": ["C1", "C2"]}\n```')
        out = substitute_charts(md, ledger)
        assert "<svg" in out
        assert "```chart" not in out
