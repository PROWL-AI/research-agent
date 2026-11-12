"""A request that its caller approves at once never reaches the operator's phone.

2026-11-12: four research requests each pushed "ждёт вашего решения" to Telegram and each
was approved 0.1 s later by the agent that created it. The operator was asked four times
about decisions already made. The awaiting notice is now pushed only for a request still
undecided after a grace period, and once per request.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from research_agent.service import store as store_mod
from research_agent.service.store import Store


def _pushed(store: Store) -> list[dict]:
    return [e for e in store.events(after=0, limit=200)["events"] if e.get("notify")]


def _request(n: int) -> dict:
    return {"runbook": "tutorial", "inputs": {"n": n}}


def test_creating_a_request_pushes_nothing(tmp_path) -> None:
    s = Store(tmp_path)
    s.create(_request(1), "k1")
    assert _pushed(s) == []


def test_a_request_approved_within_the_grace_is_never_pushed(tmp_path, monkeypatch) -> None:
    s = Store(tmp_path)
    job, _ = s.create(_request(1), "k1")
    s.decide(job["id"], job["proposal"]["digest"], True)
    later = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(store_mod, "now", lambda: later)
    assert _pushed(s) == []


def test_a_request_still_waiting_after_the_grace_is_pushed_once(tmp_path, monkeypatch) -> None:
    s = Store(tmp_path)
    job, _ = s.create(_request(1), "k1")
    later = (datetime.now(timezone.utc) + timedelta(seconds=store_mod.AWAITING_NOTICE_GRACE_SECONDS + 1)).isoformat().replace("+00:00", "Z")
    monkeypatch.setattr(store_mod, "now", lambda: later)
    first = _pushed(s)
    assert len(first) == 1
    assert first[0]["kind"] == "job.awaiting_choice"
    assert first[0]["subject"] == {"type": "job", "id": job["id"]}
    assert len(_pushed(s)) == 1, "the notice is pushed once, not on every read"
