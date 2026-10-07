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


def test_verbatim_quote_is_verified(tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    claim = ledger.add(
        claim='"Best tool we ever bought" — G2 review',
        subject="example.com review sentiment",
        source_tool="scrape_review_platforms",
        verbatim=True,
    )
    assert claim.status == ClaimStatus.verified


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
