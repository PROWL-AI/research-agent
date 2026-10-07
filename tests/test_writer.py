from research_agent.agent.writer import lint_report
from research_agent.evidence.ledger import Ledger

from conftest import load_fixture


def _ledger_with(tmp_path, *subjects):
    ledger = Ledger(tmp_path / "ledger.json")
    for subject in subjects:
        ledger.add(claim=f"fact about {subject}", subject=subject, value=1, source_tool="t")
    return ledger


def test_lint_flags_uncited_estimate(tmp_path):
    fixture = load_fixture("t6_hallucinated_precision.json")
    ledger = _ledger_with(tmp_path, "x")
    result = lint_report(fixture["report_excerpt"], ledger)
    assert not result.ok
    assert "150,000" in result.uncited_numbers


def test_lint_passes_cited_number(tmp_path):
    ledger = _ledger_with(tmp_path, "x")
    report = "The rival attracts an estimated 150,000 monthly visitors [C1] (ASSUMED, ±40%)."
    result = lint_report(report, ledger)
    assert result.ok, result.issues


def test_lint_flags_missing_ledger_ref(tmp_path):
    ledger = _ledger_with(tmp_path, "x")
    report = "Traffic is 150,000 monthly visitors [C99]."
    result = lint_report(report, ledger)
    assert not result.ok
    assert "C99" in result.missing_refs
    assert not result.uncited_numbers


def test_lint_ignores_prose_without_metrics(tmp_path):
    ledger = _ledger_with(tmp_path, "x")
    result = lint_report("The rival positions itself as the fastest option on the market.", ledger)
    assert result.ok


def test_writer_prompt_states_hard_rule_with_example():
    from research_agent.agent.writer import WRITER_SYSTEM_TEMPLATE

    assert "IMMEDIATELY after the figure" in WRITER_SYSTEM_TEMPLATE
    assert "[UNVERIFIED]" in WRITER_SYSTEM_TEMPLATE
    assert "WRONG" in WRITER_SYSTEM_TEMPLATE
    assert "RIGHT" in WRITER_SYSTEM_TEMPLATE
    assert "[CONFLICT]" in WRITER_SYSTEM_TEMPLATE
    assert "Source Log" in WRITER_SYSTEM_TEMPLATE


def test_repair_prompt_forbids_invented_citations():
    from research_agent.agent.writer import REPAIR_SYSTEM_TEMPLATE

    assert "NEVER invent" in REPAIR_SYSTEM_TEMPLATE or "do NOT invent" in REPAIR_SYSTEM_TEMPLATE
    assert "subject" in REPAIR_SYSTEM_TEMPLATE
