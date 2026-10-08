"""Runbook loading: SKILL.md files with strict YAML frontmatter."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

RUNBOOKS_DIR = Path(__file__).resolve().parent / "runbooks"

INPUT_TYPES = ("domain", "list[domain]", "string")
EFFORT_CLASSES = ("lookup", "comparison", "deep")

_RUNBOOK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class RunbookError(Exception):
    pass


class RunbookInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: str
    required: bool = False
    max: int | None = None
    doc: str | None = None


class Budget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tool_calls: int
    max_usd: float
    max_minutes: int


class Outputs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_template: str
    formats: list[str]


class RunbookMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    version: str
    inputs: list[RunbookInput] = []
    tools: list[str]
    budget: Budget
    outputs: Outputs
    #: Optional effort class for sub-agent fan-out (lookup | comparison | deep);
    #: derived from the tool-call budget when omitted — see agent.subagent.effort_for.
    effort: str | None = None


@dataclass(frozen=True)
class Runbook:
    meta: RunbookMeta
    body: str
    path: Path

    @property
    def name(self) -> str:
        return self.meta.name

    def section(self, heading: str) -> str | None:
        pattern = re.compile(
            rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(self.body)
        return match.group(1).strip() if match else None

    @property
    def output_instructions(self) -> str:
        return self.section("Output instructions") or ""


def _parse_frontmatter(raw: str, path: Path) -> RunbookMeta:
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        raise RunbookError(f"{path}: no YAML frontmatter block found")
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise RunbookError(f"{path}: frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise RunbookError(f"{path}: frontmatter must be a YAML mapping")
    try:
        meta = RunbookMeta.model_validate(data)
    except ValidationError as exc:
        raise RunbookError(f"{path}: invalid frontmatter:\n{exc}") from exc
    for input_ in meta.inputs:
        if input_.type not in INPUT_TYPES:
            raise RunbookError(
                f"{path}: input '{input_.name}' has unknown type '{input_.type}'"
                f" (allowed: {', '.join(INPUT_TYPES)})"
            )
    if meta.effort is not None and meta.effort not in EFFORT_CLASSES:
        raise RunbookError(
            f"{path}: unknown effort '{meta.effort}' (allowed: {', '.join(EFFORT_CLASSES)})"
        )
    return meta


def load_runbook(path: Path) -> Runbook:
    raw = path.read_text(encoding="utf-8")
    meta = _parse_frontmatter(raw, path)
    body = _FRONTMATTER_RE.sub("", raw, count=1).strip()
    return Runbook(meta=meta, body=body, path=path)


def list_runbooks(runbooks_dir: Path | None = None) -> list[Runbook]:
    directory = runbooks_dir or RUNBOOKS_DIR
    runbooks = []
    for skill_md in sorted(directory.glob("*/SKILL.md")):
        runbooks.append(load_runbook(skill_md))
    return runbooks


def get_runbook(name: str, runbooks_dir: Path | None = None) -> Runbook:
    if not _RUNBOOK_NAME_RE.match(name):
        raise RunbookError(f"invalid runbook name '{name}'")
    directory = runbooks_dir or RUNBOOKS_DIR
    path = directory / name / "SKILL.md"
    if not path.is_file():
        available = ", ".join(rb.name for rb in list_runbooks(directory)) or "(none)"
        raise RunbookError(f"unknown runbook '{name}'; available: {available}")
    return load_runbook(path)


InputType = Literal["domain", "list[domain]", "string"]
