from research_agent.evidence.ledger import ClaimStatus, Ledger

from conftest import load_fixture


def test_single_source_non_verbatim_is_assumed(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    claim = ledger.add(
        claim="traffic is 42k",
        subject="example.com traffic",
        value=42000,
        unit="visits/month",
        source_tool="spyfu_get_domain_stats",
    )
    assert claim.status == ClaimStatus.assumed


def test_quote_found_in_stored_raw_is_verified(tmp_path):
    # Was test_verbatim_quote_is_verified: `verbatim=True` from the extractor
    # verified by itself (KA-08). Now only a quote located in the stored raw does.
    ledger = Ledger(tmp_path / "ledger.json")
    claim = ledger.add(
        claim='"Best tool we ever bought" — G2 review',
        subject="example.com review sentiment",
        source_tool="scrape_review_platforms",
        quote="Best tool we ever bought",
        quote_span=(10, 34),
    )
    assert claim.status == ClaimStatus.verified
    assert claim.verification["method"] == "span"


def test_quote_without_a_located_span_is_assumed(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    claim = ledger.add(claim="x", subject="s", source_tool="scrape_review_platforms",
                       quote="Best tool we ever bought")
    assert claim.status == ClaimStatus.assumed


def test_two_independent_tools_verify(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    first = ledger.add(
        claim="traffic is 42k",
        subject="example.com traffic",
        value=42000,
        source_tool="spyfu_get_domain_stats",
    )
    second = ledger.add(
        claim="traffic is 42k",
        subject="example.com traffic",
        value=42000,
        source_tool="dataforseo_labs_bulk_traffic_estimation",
    )
    assert first.status == ClaimStatus.verified
    assert second.status == ClaimStatus.verified


def test_conflict_keeps_both_sides(tmp_path):
    fixture = load_fixture("t7_conflict_protocol.json")
    ledger = Ledger(tmp_path / "ledger.json")
    added = [ledger.add(**raw) for raw in fixture["claims"]]

    assert len(ledger.claims) == fixture["expect"]["kept"]
    assert all(c.status == ClaimStatus.conflict for c in added)
    values = {c.value for c in ledger.claims}
    assert values == {42000, 118000}


def test_ledger_persists_and_reloads(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = Ledger(path)
    ledger.add(claim="x", subject="s", value=1, source_tool="t")
    ledger.save()
    reloaded = Ledger.load(path)
    assert len(reloaded.claims) == 1
    assert reloaded.claims[0].id == "C1"
    third = reloaded.add(claim="y", subject="s2", value=2, source_tool="t")
    assert third.id == "C2"


# ── B-127: points of a series are not a conflict ─────────────────────────────────────────────────────────────────────
# The acceptance run of 2026-11-13 (pr-9a55099f6972307f0a5b) put 90 of 192 claims in conflict: every week of a Google
# Trends series shared one subject, so its values disagreed.

SUBJECT = "Google Trends interest for 'AI market research'"


def _point(ledger, week, value, quote=True):
    text = f"Google Trends interest for 'AI market research' was {value} in the week of {week}."
    return ledger.add(claim=text, subject=SUBJECT, value=value, unit="index", source_tool="google_trends",
                      quote=f"{value}" + " interest" if quote else None, quote_span=(0, 5) if quote else None)


def test_the_weeks_of_a_series_are_points_not_a_conflict(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    points = [_point(ledger, "Nov 7–13, 2021", 0), _point(ledger, "Jun 7–13, 2026", 100), _point(ledger, "Mar 1–7, 2026", 65)]
    assert {c.status for c in points} == {ClaimStatus.verified}


def test_two_values_for_the_same_week_still_conflict(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    points = [_point(ledger, "Jun 7–13, 2026", 100), _point(ledger, "Jun 7–13, 2026", 80), _point(ledger, "Mar 1–7, 2026", 65)]
    assert [c.status for c in points] == [ClaimStatus.conflict, ClaimStatus.conflict, ClaimStatus.verified]


def test_a_claim_that_names_no_period_keeps_the_old_rule(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    dated = _point(ledger, "Jun 7–13, 2026", 100)
    undated = ledger.add(claim="interest is 40", subject=SUBJECT, value=40, unit="index", source_tool="google_trends")
    assert dated.status == undated.status == ClaimStatus.conflict


def test_the_period_survives_a_reload(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = Ledger(path)
    _point(ledger, "Nov 7–13, 2021", 0)
    _point(ledger, "Jun 7–13, 2026", 100)
    ledger.save()
    assert {c.status for c in Ledger.load(path).claims} == {ClaimStatus.verified}
