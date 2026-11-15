"""The compiled wiki of the agents database (pattern `compiled-wiki` 1.0.0, D-51, B-147), bound to this agent.

`compiled_wiki.py` beside this file is the pattern's code, vendored unedited (its first line names the version). This
module is the adaptation by injection the pattern asks for, and nothing more:

* the fence and the scan are this agent's own `untrusted_fence` (the one every tool result already passes through,
  B-102), so a source's text reaches a model only inside a fresh random fence, and a source read as an injection is
  held from every model, plan and retrieval;
* there is no outbound guard of our own yet (the agent has no `privacy-filter`), so `open_wiki` takes one from the
  caller and refuses to open without it: a page or an answer never leaves unguarded;
* the retrieval floor is not set here: the pattern's 0.6 is uncalibrated, and B-147 sets it from a gold set.

Not wired into the answer path yet (B-147): this agent's runbook and report-orchestrator variants answer from live,
paid tool calls made for each run, and a compiled page of market numbers is dated the day it was read. Where it goes
and how fresh data wins over a page is B-147's design step.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from research_agent.agent import untrusted_fence
from research_agent.agent.compiled_wiki import Wiki, WikiError, __version__

__all__ = ["open_wiki", "ResearchWiki", "Wiki", "WikiError", "PATTERN_VERSION"]

PATTERN_VERSION = __version__


class ResearchWiki(Wiki):
    """The pattern's `Wiki`, opened with this agent's fence and scan and holding the caller's outbound guard."""

    def __init__(self, root: Path | str, *, outbound: Callable[[str], str], today: Optional[str] = None,
                 claim_check: Optional[Callable] = None) -> None:
        if not callable(outbound):
            raise WikiError("no_outbound_guard", "the research wiki opens only with an outbound guard")
        super().__init__(Path(root), fence=untrusted_fence.fence, scan=untrusted_fence.scan,
                         claim_check=claim_check, today=today)
        self.outbound = outbound

    def export_page_guarded(self, slug: str) -> str:
        """A page as text that may leave, through the guard the wiki was opened with."""
        return self.export_page(slug, self.outbound)

    def export_answer_guarded(self, checked: dict) -> str:
        """A checked answer as text that may leave, through the guard the wiki was opened with."""
        return self.export_answer(checked, self.outbound)


def open_wiki(root: Path | str, *, outbound: Callable[[str], str], today: Optional[str] = None,
              claim_check: Optional[Callable] = None) -> ResearchWiki:
    """One wiki under `root`, fenced and scanned by this agent's untrusted fence.

    `outbound` is required: the guard every page or answer passes on its way out. `claim_check` is the optional
    stricter check of a claim against its quote (the pattern checks the quote and the numbers only)."""
    return ResearchWiki(root, outbound=outbound, today=today, claim_check=claim_check)
