"""B-132: a transform reads the artifacts of the steps its instruction names, in compact JSON."""
import json

from research_agent.agent import orchestrator as O
from research_agent.evidence.store import StepRecord


def _done(step: str, i: int, tool: str = "t") -> StepRecord:
    return StepRecord(step_id=f"s-{i}", raw_index=i, tool=tool, step=step, state="completed", raw_ref=f"raw/{i}.json")


def test_an_instruction_naming_no_step_reads_the_last_three_as_before():
    steps = [_done(f"step_{i}", i) for i in range(6)]
    chosen, chars = O._transform_sources("summarise what we have", steps)
    assert [s.step for s in chosen] == ["step_3", "step_4", "step_5"]
    assert chars == O._TRANSFORM_CONTEXT_CHARS


def test_named_steps_are_read_even_when_they_are_not_the_latest():
    """pr-8ca06955600a3e5fd3be: select_competitors named four steps and saw only the last three artifacts."""
    names = ["scrape_homepage", "spyfu_competitors", "dfs_competitors", "exa_similar", "moz_metrics", "bl_summary"]
    steps = [_done(n, i) for i, n in enumerate(names)]
    chosen, chars = O._transform_sources(
        "From spyfu_competitors, dfs_competitors, exa_similar and scrape_homepage positioning: select the top-3", steps)
    assert [s.step for s in chosen] == ["scrape_homepage", "spyfu_competitors", "dfs_competitors", "exa_similar"]
    assert chars == O._TRANSFORM_NAMED_TOTAL_CHARS // 4 > O._TRANSFORM_CONTEXT_CHARS


def test_a_name_inside_a_longer_name_is_not_a_match():
    steps = [_done("competitors", 0), _done("dfs_competitors", 1), _done("x", 2), _done("y", 3)]
    chosen, _ = O._transform_sources("read dfs_competitors", steps)
    assert "competitors" not in [s.step for s in chosen]
    assert chosen[0].step == "dfs_competitors"


def test_one_named_step_is_topped_up_with_the_most_recent_others():
    steps = [_done(n, i) for i, n in enumerate(["a_step", "b_step", "c_step", "d_step"])]
    chosen, chars = O._transform_sources("from a_step", steps)
    assert [s.step for s in chosen] == ["a_step", "c_step", "d_step"]
    assert chars == O._TRANSFORM_NAMED_TOTAL_CHARS // 3


def test_at_most_the_cap_of_named_steps_the_latest_kept():
    steps = [_done(f"fan_{i}", i) for i in range(12)]
    chosen, chars = O._transform_sources(" ".join(f"fan_{i}" for i in range(12)), steps)
    assert len(chosen) == O._TRANSFORM_NAMED_ARTIFACTS and chosen[-1].step == "fan_11"
    assert chars >= O._TRANSFORM_CONTEXT_CHARS


def test_steps_that_returned_nothing_are_not_read():
    steps = [_done("a_step", 0), StepRecord(step_id="s-1", raw_index=1, tool="t", step="b_step", state="skipped_on_error")]
    chosen, _ = O._transform_sources("from a_step and b_step", steps)
    assert [s.step for s in chosen] == ["a_step"]


def test_compact_json_halves_indented_json_and_leaves_text_alone():
    body = {"items": [{"domain": f"d{i}.com", "metrics": {"etv": i}} for i in range(50)]}
    pretty = json.dumps(body, indent=2)
    compact = O._compact_json(pretty)
    assert json.loads(compact) == body and len(compact) < len(pretty) / 2
    assert O._compact_json("# a markdown note") == "# a markdown note"
