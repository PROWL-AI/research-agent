"""The cloud instance's state survives a dyno restart (B-099 M4, REQ-7)."""
import sqlite3

import pytest

from research_agent.service.snapshot import Snapshots, pack, unpack
from research_agent.service.store import Store
from tests.test_cloud_clients import SqliteAsPostgres


@pytest.fixture
def snapshots():
    connection = SqliteAsPostgres()
    return Snapshots(lambda: connection)


def seed(root):
    store = Store(root)
    job = store.create({"kind": "tutorial"}, "k")[0]
    (root / "runs" / "r1").mkdir(parents=True)
    (root / "runs" / "r1" / "checkpoint.json").write_text("{}")
    (root / "service.lock").write_text("")
    store.db.close()
    return job


def test_round_trip_restores_jobs_and_runs(tmp_path, snapshots):
    job = seed(tmp_path / "a")
    assert snapshots.save(tmp_path / "a")
    fresh = Snapshots(snapshots.connect)
    assert fresh.restore(tmp_path / "b")
    store = Store(tmp_path / "b")
    assert store.job(job["id"])["id"] == job["id"]
    assert (tmp_path / "b" / "runs" / "r1" / "checkpoint.json").read_text() == "{}"
    assert not (tmp_path / "b" / "service.lock").exists()


def test_unchanged_root_is_not_saved_again(tmp_path, snapshots):
    seed(tmp_path / "a")
    assert snapshots.save(tmp_path / "a")
    assert not snapshots.save(tmp_path / "a")
    (tmp_path / "a" / "runs" / "r1" / "note.txt").write_text("new")
    assert snapshots.save(tmp_path / "a")


def test_only_three_are_kept(tmp_path, snapshots):
    seed(tmp_path / "a")
    for i in range(5):
        (tmp_path / "a" / "runs" / f"n{i}").write_text(str(i))
        snapshots.save(tmp_path / "a")
    with snapshots.connect().cursor() as cur:
        assert cur.execute("SELECT count(*) FROM prowl_research_snapshot").fetchone()[0] == 3


def test_a_damaged_snapshot_is_skipped_for_the_older_one(tmp_path, snapshots):
    seed(tmp_path / "a")
    snapshots.save(tmp_path / "a")
    (tmp_path / "a" / "runs" / "late.txt").write_text("late")
    snapshots.save(tmp_path / "a")
    db = snapshots.connect()
    with db.cursor() as cur:
        newest = cur.execute("SELECT taken_at FROM prowl_research_snapshot ORDER BY taken_at DESC").fetchone()[0]
        cur.execute("UPDATE prowl_research_snapshot SET body=%s WHERE taken_at=%s", (b"broken", newest))
    db.commit()
    assert Snapshots(snapshots.connect).restore(tmp_path / "b")
    assert not (tmp_path / "b" / "runs" / "late.txt").exists()
    assert (tmp_path / "b" / "runs" / "r1" / "checkpoint.json").exists()


def test_nothing_to_restore(tmp_path, snapshots):
    assert snapshots.restore(tmp_path / "b") is None


def test_unpack_refuses_a_path_outside_the_root(tmp_path):
    import gzip
    import io
    import tarfile
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ValueError):
        unpack(gzip.compress(buffer.getvalue()), tmp_path / "root")
    assert not (tmp_path / "escape.txt").exists()


def test_pack_copies_the_database_through_the_backup_api(tmp_path):
    seed(tmp_path / "a")
    live = sqlite3.connect(tmp_path / "a" / "service.sqlite3")
    live.execute("PRAGMA journal_mode=WAL")
    unpack(pack(tmp_path / "a"), tmp_path / "b")
    assert Store(tmp_path / "b").jobs()
    live.close()
