"""Transactional local jobs, decisions, call receipts and host event feed."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

TERMINAL = {"completed", "failed", "cancelled"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class Conflict(ValueError):
    pass


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    cheap_model: str = Field(default="google/gemini-2.5-flash", min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9/_.:-]+$")
    strong_model: str = Field(default="anthropic/claude-sonnet-4.5", min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9/_.:-]+$")
    parallel_jobs: int = Field(default=1, ge=1, le=4)
    timeout_minutes: int = Field(default=15, ge=1, le=60)
    max_workers: int = Field(default=1, ge=1, le=5)


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(root / "service.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError("store is newer than this service")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
          request_hash TEXT NOT NULL, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, job TEXT NOT NULL, body TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS calls_job ON calls(job);
        CREATE TABLE IF NOT EXISTS config(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER, body TEXT);
        CREATE TABLE IF NOT EXISTS auth(kind TEXT, hash TEXT PRIMARY KEY, expires TEXT);
        PRAGMA user_version=1;
        """)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO config VALUES(1,1,?)", (json.dumps(Settings().model_dump()),))
        (root / "service.sqlite3").chmod(0o600)

    def config(self):
        row = self.db.execute("SELECT * FROM config").fetchone()
        return {"revision": row["revision"], **json.loads(row["body"])}

    def configure(self, revision: int, values: dict):
        valid = Settings.model_validate(values).model_dump()
        with self.db:
            if self.config()["revision"] != revision:
                raise Conflict("Настройки уже изменились. Обновите страницу и сравните изменения.")
            self.db.execute("UPDATE config SET revision=revision+1,body=? WHERE id=1", (json.dumps(valid),))
            self.event("config.changed", "Настройки сохранены для новых запросов.")
        return self.config()

    def _save(self, job):
        self.db.execute("UPDATE jobs SET body=? WHERE id=?", (json.dumps(job, ensure_ascii=False), job["id"]))

    def job(self, job_id):
        row = self.db.execute("SELECT body FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError("unknown-job")
        return json.loads(row[0])

    def jobs(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT body FROM jobs ORDER BY rowid DESC LIMIT 5000")]

    def create(self, request: dict, request_key: str, trace: str | None = None):
        request_hash = digest(request)
        with self.db:
            row = self.db.execute("SELECT request_hash,body FROM jobs WHERE request_key=?", (request_key,)).fetchone()
            if row:
                if row[0] != request_hash:
                    raise Conflict("idempotencyKey уже использован с другим запросом")
                return json.loads(row[1]), False
            if self.db.execute("SELECT count(*) FROM jobs").fetchone()[0] >= 5000:
                raise Conflict("Хранилище содержит 5000 запросов. Архивируйте данные перед новым запуском.")
            job_id = "pr-" + secrets.token_hex(10)
            job = dict(id=job_id, status="input_required", phase="approval", createdAt=now(), updatedAt=now(),
                       request=request, config=self.config(), traceparent=trace, result=None, error=None)
            job["proposal"] = {"digest": digest({"id": job_id, "request": request, "config": job["config"]}),
                               "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")}
            self.db.execute("INSERT INTO jobs VALUES(?,?,?,?)", (job_id, request_key, request_hash, json.dumps(job)))
            self.event("job.awaiting_choice", "Запрос ожидает проверки входных данных и разрешения запуска.", job, "notice", True)
            return job, True

    def decide(self, job_id, proposal_digest, approve: bool):
        with self.db:
            job = self.job(job_id)
            if job["status"] != "input_required":
                raise Conflict("Решение уже принято; повторный запуск запрещён.")
            if proposal_digest != job["proposal"]["digest"] or now() > job["proposal"]["expiresAt"]:
                raise Conflict("Решение устарело или не соответствует запросу. Создайте новый запрос.")
            job.update(status="working" if approve else "cancelled", phase="queued" if approve else "rejected", updatedAt=now())
            self._save(job)
            self.event("job.approved" if approve else "job.cancelled", "Запуск разрешён." if approve else "Запрос отклонён до выполнения.", job)
            return job

    def transition(self, job_id, status, phase, **fields):
        with self.db:
            job = self.job(job_id)
            if job["status"] in TERMINAL:
                return job
            job.update(status=status, phase=phase, updatedAt=now(), **fields)
            self._save(job)
            self.event("job." + phase, {"completed": "Результат сохранён.", "failed": "Запрос завершился с ошибкой. Проверьте шаги.",
                       "cancelled": "Запрос отменён. Уже выполненные списания сохраняются.", "interrupted": "Выполнение прервано перезапуском; автоматического повтора не будет."}.get(phase, "Состояние запроса изменено: " + phase), job,
                       "error" if status == "failed" else "info", status == "failed")
            return job

    def recover(self):
        for job in self.jobs():
            if job["status"] == "working":
                self.transition(job["id"], "failed", "interrupted", error={"code": "interrupted", "message": "Service restarted. Inspect receipts; do not blindly retry."})
        with self.db:
            for row in self.db.execute("SELECT id,body FROM calls").fetchall():
                call = json.loads(row["body"])
                if call["status"] == "working":
                    call.update(status="unknown", endedAt=now())
                    self.db.execute("UPDATE calls SET body=? WHERE id=?", (json.dumps(call), row["id"]))
            self.db.execute("DELETE FROM auth WHERE expires < ?", (now(),))

    def event(self, kind, text, job=None, level="info", notify=False):
        value = {"at": now(), "kind": kind, "text": text[:500], "level": level, "notify": notify}
        if job:
            value.update(subject={"type": "job", "id": job["id"]}, link="/dashboard#/requests/" + job["id"])
            if job.get("traceparent"):
                parts = job["traceparent"].split("-")
                value.update(traceId=parts[1], spanId=parts[2])
        self.db.execute("INSERT INTO events(body) VALUES(?)", (json.dumps(value),))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat().replace("+00:00", "Z")
        self.db.execute("DELETE FROM events WHERE id < (SELECT COALESCE(MAX(id),0)-999 FROM events) AND json_extract(body,'$.at') < ?", (cutoff,))

    def events(self, after=None, limit=50):
        if after is None:
            latest = self.db.execute("SELECT id FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            after = max(0, min([r[0] for r in latest], default=1) - 1)
        rows = self.db.execute("SELECT id,body FROM events WHERE id>? ORDER BY id LIMIT ?", (after, limit)).fetchall()
        events = [dict(json.loads(r["body"]), id=str(r["id"])) for r in rows]
        return {"events": events, "cursor": events[-1]["id"] if events else str(after) if after else None}

    def start_call(self, job_id, kind, name, arguments):
        if sum(p.stat().st_size for p in self.root.glob("service.sqlite3*")) > 256_000_000:
            raise Conflict("Local journal storage limit reached; archive before more calls")
        call = dict(id="call-" + secrets.token_hex(10), job=job_id, kind=kind, name=name, startedAt=now(),
                    status="working", arguments=arguments, costUsd=None, costBasis="unknown", inputTokens=0, outputTokens=0)
        with self.db:
            self.db.execute("INSERT INTO calls VALUES(?,?,?)", (call["id"], job_id, json.dumps(call)))
        return call

    def finish_call(self, call, **fields):
        call.update(endedAt=now(), **fields)
        with self.db:
            self.db.execute("UPDATE calls SET body=? WHERE id=?", (json.dumps(call, ensure_ascii=False), call["id"]))
        return call

    def calls(self, job_id=None):
        rows = self.db.execute("SELECT body FROM calls" + (" WHERE job=?" if job_id else ""), (job_id,) if job_id else ())
        return [json.loads(r[0]) for r in rows]

    def auth_create(self, kind, seconds):
        value = secrets.token_urlsafe(32)
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
        with self.db:
            self.db.execute("DELETE FROM auth WHERE expires < ?", (now(),))
            self.db.execute("INSERT INTO auth VALUES(?,?,?)", (kind, hashlib.sha256(value.encode()).hexdigest(), expiry))
        return value

    def auth_valid(self, kind, value, consume=False):
        hashed = hashlib.sha256(value.encode()).hexdigest()
        with self.db:
            row = self.db.execute("SELECT expires FROM auth WHERE hash=? AND kind=?", (hashed, kind)).fetchone()
            if consume:
                self.db.execute("DELETE FROM auth WHERE hash=?", (hashed,))
            return bool(row and row[0] > now())

    def usage(self):
        jobs = {j["id"]: j for j in self.jobs()}
        days = {}
        since = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
        for call in self.calls():
            if jobs[call["job"]]["request"]["kind"] == "tutorial" or call["startedAt"][:10] < since:
                continue
            day = days.setdefault(call["startedAt"][:10], {})
            key = ("prowl" if call["kind"] == "tool" else "llm", call["name"][:128])
            row = day.setdefault(key, {"provider": key[0], "model": key[1], "calls": 0, "unpricedCalls": 0,
                                      "inputTokens": 0, "outputTokens": 0, "costUsd": None, "costBasis": "unknown"})
            row["calls"] += 1
            row["unpricedCalls"] += call["costUsd"] is None
            row["inputTokens"] += call["inputTokens"]
            row["outputTokens"] += call["outputTokens"]
            if call["costUsd"] is not None:
                row["costUsd"] = (row["costUsd"] or 0) + call["costUsd"]
                row["costBasis"] = "provider"
        result = []
        for date, models in sorted(days.items()):
            by_model = list(models.values())
            totals = {key: sum(r[key] for r in by_model) for key in ("calls", "unpricedCalls", "inputTokens", "outputTokens")}
            costs = [r["costUsd"] for r in by_model if r["costUsd"] is not None]
            result.append(dict(date=date, byModel=by_model, costUsd=sum(costs) if costs else None, **totals))
        return {"protocol": "fabric-service/0.1", "service": {"id": "prowl-research", "instance": "default"},
                "generatedAt": now(), "currency": "USD", "days": result}
