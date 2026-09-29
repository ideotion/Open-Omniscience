"""The Activity Ledger -- one append-only entry for every action the app takes on its own.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (0.5 slice S05-09 S5, Q1120 = a; the design is Graft 2 of
``docs/design/UI_COMPLEXITY_AND_AUTOMATION_PLAN_2026-09-08.md`` §6). The app does a
great deal without being asked: the collection pass, the housekeeping lane's nine kinds,
the pass-tail ride-alongs, the Home briefing refresh, the idle-time maintenance. Each of
those already reports a tally somewhere (the run log, the scheduler's activity, the task
manager's live rows), but nowhere did the operator get ONE chronological record of what
the app did on its own, why, what it changed, and what that result does not mean. This is
that record: a record of decisions, i.e. DATA (invariant #8), shown as a lens inside the
existing task-manager window, so invariants #4 and #20 are untouched.

THE SHAPE, fixed (the plan's seven fields). Every entry carries

- ``what_happened`` -- one sentence, with its counts;
- ``why``           -- why the app did this without being asked;
- ``touched``       -- what it changed, stated plainly, deletions included;
- ``caveat``        -- what the result does NOT mean;
- ``budget``        -- the bound it ran under;
- ``reversible``    -- whether the app offers a one-click undo;
- ``undo``          -- how, when it does (and nothing when it does not).

Each text field travels twice, like the task manager's job labels (click-through B17,
T11): the English sentence, and a keyed FRAME plus its values, which the window writes in
the UI language. The frames are fixed in :data:`ACTIONS` below, so every one is a key in
all twelve locales (``tests/test_activity_ledger.py`` checks it).

THE GRAMMAR (the plan's §5 item 6), enforced here the way ``CardSchemaError`` enforces a
card: :class:`LedgerEntry` refuses to exist in the wrong shape. For the three categories
the plan reserves for human judgment -- ``source-admission``, ``keyword-pruning`` and
``coordination`` -- the ``what_happened`` sentence must END in a measurement verb
(:data:`MEASUREMENT_VERBS`) and may not contain a decision verb (:data:`DECISION_VERBS`)
anywhere. The app measures, stages and proposes in those areas; it does not decide. What
the sentence may not do is claim a decision; what it must not do either is hide a change,
which is why ``touched`` is exempt from the verb rule: it is the inventory of what the
action really changed, and if an automated step in a reserved category deletes something,
``touched`` says so in so many words. (One does, today: the offline discovery pass deletes
still-PENDING candidates its noise filters reject. The entry says so; whether that prune
should become a flag is recorded in ``docs/ledger/OPEN_QUEUE.md`` for the maintainer.)

WHAT IS NOT A RESERVED CATEGORY, and why. The idle-time maintenance deletes ORPHAN keyword
rows -- rows no article references any more. That is storage housekeeping with no judgment
in it (the row describes nothing that exists), not keyword pruning in the plan's sense
(deciding that a term is not worth keeping). If a step ever prunes live keywords, it
belongs in ``keyword-pruning`` and the grammar applies.

WHAT IS NOT RECORDED. Counts only: never a URL, a domain, a title or a query -- the file is
plaintext in the data folder, like the session ledger beside it. A step that is switched
off writes nothing (it did not act); a step that ran and skipped says so, with its reason.

Best-effort by construction: :func:`record` never raises into the caller -- the ledger
explains the loop, it must never be able to stop it. A MIS-SHAPED entry is different: it is
a programming error, caught by the test suite on every commit (the registry is validated at
import, and :class:`LedgerEntry` raises), not at run time on an operator's machine.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.paths import data_dir

_LOG = logging.getLogger(__name__)

LEDGER_FILE = "activity_ledger.jsonl"
LEDGER_SCHEMA = "oo-activity-ledger-1"
#: Newest lines kept. A pass writes a handful of entries; this is weeks of a busy install.
MAX_LINES = 5000

#: The categories the plan (§5 item 6) reserves for human judgment.
RESERVED_CATEGORIES = frozenset({"source-admission", "keyword-pruning", "coordination"})
#: Every category an entry may carry. Order is the order the window lists them in.
CATEGORIES = (
    "collection", "source-admission", "keyword-pruning", "coordination",
    "enrichment", "surfacing", "maintenance",
)
#: The only verbs a reserved-category sentence may end in (the plan's list, verbatim).
MEASUREMENT_VERBS = frozenset({"staged", "surfaced", "proposed", "flagged", "measured"})
#: Verbs that claim a judgment. Barred anywhere in a reserved-category sentence. The plan
#: names the first four; the rest are the same claim in other words, listed so a rewording
#: cannot walk around the rule.
DECISION_VERBS = frozenset({
    "enabled", "removed", "deprioritized", "decided",
    "disabled", "deleted", "admitted", "rejected", "approved", "accepted", "promoted",
    "demoted", "banned", "blocked", "pruned", "dropped", "dismissed", "excluded",
    "prioritized", "chosen", "selected",
})

_FIELDS = ("what_happened", "why", "touched", "caveat", "budget")
_WORD = re.compile(r"[A-Za-z]+")
_VAR = re.compile(r"\{([a-z_]+)\}")

#: The frame every step that ran but did nothing this time uses. Ends in a measurement verb
#: so it is valid in every category.
SKIPPED_FRAME = "Skipped this time, so nothing was measured"
#: The frame a step that raised uses. The count of what it did before failing is not known.
FAILED_FRAME = "Stopped by an error before its result could be measured"


class LedgerGrammarError(ValueError):
    """An entry in the wrong shape: a missing field, an unknown category, an ``undo`` that
    does not match ``reversible``, or a reserved-category sentence that claims a decision."""


def _last_word(text: str) -> str:
    words = _WORD.findall(text or "")
    return words[-1].lower() if words else ""


def check_grammar(category: str, what_happened: str) -> None:
    """Raise :class:`LedgerGrammarError` when ``what_happened`` breaks the vocabulary rule
    for ``category``. Public so the test suite can run every frame through it."""
    if category not in CATEGORIES:
        raise LedgerGrammarError(f"unknown ledger category {category!r}")
    if category not in RESERVED_CATEGORIES:
        return
    words = {w.lower() for w in _WORD.findall(what_happened or "")}
    claimed = sorted(words & DECISION_VERBS)
    if claimed:
        raise LedgerGrammarError(
            f"a {category} entry may not claim a decision ({', '.join(claimed)}): "
            f"{what_happened!r}"
        )
    last = _last_word(what_happened)
    if last not in MEASUREMENT_VERBS:
        raise LedgerGrammarError(
            f"a {category} entry must end in a measurement verb "
            f"({', '.join(sorted(MEASUREMENT_VERBS))}), not {last!r}: {what_happened!r}"
        )


def _render(frame: str, values: dict[str, Any]) -> str:
    return _VAR.sub(lambda m: str(values.get(m.group(1), m.group(0))), frame)


@dataclass(frozen=True)
class LedgerEntry:
    """One entry. Constructing it IS the check: a mis-shaped entry cannot exist."""

    action: str
    category: str
    what_happened: str
    why: str
    touched: str
    caveat: str
    budget: str
    reversible: bool
    undo: str | None = None
    #: The keyed frames and their values, for the window to write in the UI language.
    frames: dict[str, str] = field(default_factory=dict)
    vars: dict[str, Any] = field(default_factory=dict)
    #: A reason given by the step itself (a skip reason), carried as data.
    note: str | None = None
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))

    def __post_init__(self) -> None:
        if not self.action:
            raise LedgerGrammarError("an entry needs the action that wrote it")
        for name in _FIELDS:
            val = getattr(self, name)
            if not isinstance(val, str) or not val.strip():
                raise LedgerGrammarError(f"{self.action}: the {name!r} field is empty")
        if not isinstance(self.reversible, bool):
            raise LedgerGrammarError(f"{self.action}: 'reversible' must be true or false")
        if self.reversible and not (self.undo or "").strip():
            raise LedgerGrammarError(f"{self.action}: a reversible entry must say how to undo it")
        if not self.reversible and self.undo:
            raise LedgerGrammarError(f"{self.action}: an irreversible entry cannot offer an undo")
        check_grammar(self.category, self.what_happened)

    def as_record(self) -> dict[str, Any]:
        rec = {
            "schema": LEDGER_SCHEMA, "at": self.at, "action": self.action,
            "category": self.category, "reserved": self.category in RESERVED_CATEGORIES,
            "what_happened": self.what_happened, "why": self.why, "touched": self.touched,
            "caveat": self.caveat, "budget": self.budget, "reversible": self.reversible,
            "undo": self.undo, "frames": dict(self.frames), "vars": dict(self.vars),
        }
        if self.note:
            rec["note"] = self.note
        return rec


# --------------------------------------------------------------------------- #
#  The registry: every automated action, with its fixed sentences
# --------------------------------------------------------------------------- #


def _n(d: Any, *keys: str) -> int:
    """The sum of the integer counts under ``keys`` (a missing or odd one counts 0)."""
    total = 0
    for k in keys:
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, bool):
            continue
        if isinstance(v, int | float):
            total += int(v)
    return total


def _len(d: Any, key: str) -> int:
    v = d.get(key) if isinstance(d, dict) else None
    return len(v) if isinstance(v, list | tuple | dict) else _n(d, key)


def _setting(settings: Any, name: str, default: int = 0) -> int:
    try:
        return int(getattr(settings, name, default) or 0)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Action:
    """One automated action's fixed sentences. ``what``, ``touched`` and ``budget`` are
    frames (``{name}`` values filled from the step's own result); ``why`` and ``caveat``
    are fixed. ``values`` reads the counts out of the step's result dict."""

    category: str
    what: str
    touched: str
    why: str
    caveat: str
    budget: str
    values: Callable[[dict, Any], dict[str, int]] = lambda r, s: {}
    reversible: bool = False
    undo: str | None = None


_CAVEAT = {
    "collection": "A count of what was stored. It says nothing about what the articles claim.",
    "source-admission": (
        "A measurement against published criteria, not a judgment of the source. "
        "Nothing here enables a source: that stays your choice."
    ),
    "enrichment": "Derived on this machine from your own corpus. A reading aid, never a verdict.",
    "surfacing": "Each card is a pattern in your corpus with its own caveat, not a finding.",
    "maintenance": "The app's own bookkeeping. No article's content is changed.",
}

#: Every action the app takes on its own. The scheduler's nine housekeeping kinds are
#: ``lane:<kind>`` (``tests/test_activity_ledger.py`` pins that every kind in
#: ``src.scheduler.runner._LANE_STEPS`` has an entry here, and that the lane writes one).
ACTIONS: dict[str, Action] = {
    "collection-pass": Action(
        category="collection",
        what="Collection pass: {stored} article(s) stored from {sources} source(s) read",
        touched="Corpus articles: {stored} added",
        why="Collection runs on its own while the app is online.",
        caveat=_CAVEAT["collection"],
        budget="Every enabled source that is due, one pass at a time",
        values=lambda r, s: {"stored": _n(r, "articles_stored"), "sources": _n(r, "sources_processed")},
    ),
    "lane:markets": Action(
        category="collection",
        what="Market and statistics feeds read: {values} value(s) stored",
        touched="Market prices and statistics: {values} value(s) added",
        why="Due market feeds refresh on every online pass.",
        caveat=_CAVEAT["collection"],
        budget="Only the feeds that are due",
        values=lambda r, s: {"values": _n(r, "feed_points", "prices_stored", "stat_vintages")},
    ),
    "lane:calendar": Action(
        category="collection",
        what="Calendar feeds: {imported} imported, {verified} checked for reachability",
        touched="Agenda events from {imported} feed(s)",
        why="Due calendar feeds import on every online pass, and a few are re-checked.",
        caveat=_CAVEAT["collection"],
        budget="The feeds that are due, plus a few checks per pass",
        values=lambda r, s: {"imported": _n(r, "imported"), "verified": _n(r, "verified")},
    ),
    "lane:law": Action(
        category="collection",
        what="Tracked laws: {documents} document(s) read, {changed} change(s) found",
        touched="Law versions: {changed} new version(s) stored",
        why="The laws you track are re-read when they are due.",
        caveat="A change is a difference in the text. It says nothing about what the change means.",
        budget="Only the tracked laws that are due",
        values=lambda r, s: {"documents": _n(r, "documents"), "changed": _n(r, "changed")},
    ),
    "lane:hazards": Action(
        category="collection",
        what="Hazard feeds: {snapshots} snapshot(s) stored",
        touched="Hazard snapshots and weather signals",
        why="Hazard and weather feeds refresh on every online pass.",
        caveat=_CAVEAT["collection"],
        budget="Only the feeds that are due",
        values=lambda r, s: {"snapshots": _n(r, "hazards_snapshotted")},
    ),
    "lane:world_discovery": Action(
        category="source-admission",
        what="World source discovery: {added} candidate source(s) staged",
        touched="Source list: {added} source(s) added, each switched off for your review",
        why="The app looks for news sources country by country, a few countries per pass.",
        caveat=_CAVEAT["source-admission"],
        budget="Up to {per_pass} country(ies) per pass",
        values=lambda r, s: {"added": _n(r, "added_this_run"),
                             "per_pass": _setting(s, "world_discovery_per_pass")},
    ),
    "lane:qualification": Action(
        category="source-admission",
        what="Qualification criteria: {evaluated} candidate source(s) measured",
        touched="Qualification stamps: {qualified} met the criteria, {disqualified} did not",
        why="Candidate sources are measured against the qualification criteria a few at a time.",
        caveat=_CAVEAT["source-admission"],
        budget="Up to {per_pass} candidate(s) and {rechecks} re-check(s) per pass",
        values=lambda r, s: {"evaluated": _n(r, "evaluated"), "qualified": _n(r, "qualified"),
                             "disqualified": _n(r, "disqualified"),
                             "per_pass": _setting(s, "qualification_per_pass"),
                             "rechecks": _setting(s, "qualification_recheck_per_pass")},
    ),
    "lane:country_data": Action(
        category="collection",
        what="Country statistics: {stored} value(s) stored",
        touched="Country statistics: {stored} value(s) added",
        why="The country statistics catalogue loads a little on every online pass.",
        caveat=_CAVEAT["collection"],
        budget="Up to {per_pass} indicator(s) per pass",
        values=lambda r, s: {"stored": _n(r, "stored"),
                             "per_pass": _setting(s, "country_data_per_pass")},
    ),
    "lane:crawl": Action(
        category="collection",
        what="Crawl supplement: {sources} source(s) crawled, {pages} page(s) read",
        touched="Corpus articles from {sources} qualified source(s)",
        why="Qualified sources are crawled a few at a time, least recently crawled first.",
        caveat=_CAVEAT["collection"],
        budget="Up to {per_pass} source(s) per pass",
        values=lambda r, s: {"sources": _n(r, "sources_crawled"),
                             "pages": _n(r, "pages_fetched", "sitemap_urls_ingested"),
                             "per_pass": _setting(s, "crawl_per_pass")},
    ),
    "lane:backfill": Action(
        category="collection",
        what="Archive backfill: {pages} page(s) of a newly qualified source read",
        touched="Corpus articles from one source's archive",
        why="A newly qualified source's older articles are read a few pages at a time.",
        caveat=_CAVEAT["collection"],
        budget="Up to {per_pass} page(s) per pass",
        values=lambda r, s: {"pages": _n(r, "attempted"),
                             "per_pass": _setting(s, "archive_backfill_per_pass")},
    ),
    "discovery": Action(
        category="source-admission",
        what="Offline source discovery: {created} candidate source(s) staged",
        touched=(
            "Source candidates: {created} added for your review; {pruned} pending "
            "candidate(s) that the noise filters reject deleted"
        ),
        why="Sources your corpus cites are listed as candidates, with no network call.",
        caveat=_CAVEAT["source-admission"],
        budget="Up to {per_run} candidate(s) per pass",
        values=lambda r, s: {"created": _n(r, "created"), "pruned": _n(r, "pruned_noise"),
                             "per_run": _setting(s, "discovery_per_run")},
    ),
    "ai-auto": Action(
        category="enrichment",
        what="Custom AI extractors: {stored} result(s) stored from the local model",
        touched="AI keywords on new articles (a separate lens, never the index)",
        why="You set a custom extractor to run on new articles.",
        caveat=_CAVEAT["enrichment"],
        budget="New articles only, on the local model",
        values=lambda r, s: {"stored": _n(r, "stored")},
    ),
    "langdetect-auto": Action(
        category="enrichment",
        what="Language detection: the local job was started",
        touched="Article language labels, as the job runs",
        why="Articles whose language is unknown are waiting, and the local model is available.",
        caveat=_CAVEAT["enrichment"],
        budget="One job at a time, on the local model",
    ),
    "source-enrichment": Action(
        category="enrichment",
        what="Source topic tags: {sources} source(s) updated from their own keywords",
        touched="Source tags: {sources} source(s)",
        why="Each source's topics are read from what it publishes, about once a day.",
        caveat=_CAVEAT["enrichment"],
        budget="About once a day, with no network call",
        values=lambda r, s: {"sources": _n(r, "sources_updated")},
    ),
    "briefing": Action(
        category="surfacing",
        what="Home briefing: {cards} card(s) surfaced",
        touched="The Home briefing",
        why="The briefing is recomputed after a pass so Home opens instantly.",
        caveat=_CAVEAT["surfacing"],
        budget="One refresh at a time; a busy one skips this pass",
        values=lambda r, s: {"cards": _len(r, "cards")},
    ),
    "idle-maintenance": Action(
        category="maintenance",
        what="Idle-time maintenance: counters reconciled and storage tidied",
        touched="Counters, summaries, orphan keyword rows, free pages",
        why="Bookkeeping runs while collection is idle, so it never slows a pass.",
        caveat=_CAVEAT["maintenance"],
        budget="Only while collection is idle, at most once per interval",
    ),
    "first-run-preflight": Action(
        category="collection",
        what="First-run check of source reachability and robots rules: started",
        touched="Per-source reachability and robots settings",
        why="The first collection pass checks the sources once, ever.",
        caveat="A reachability check is one attempt at one moment. It says nothing about the source.",
        budget="Once ever, on the first pass",
    ),
}


def validate_registry() -> None:
    """Every action, rendered with placeholder values, must make a valid entry. Called at
    import, so a mis-worded sentence is a failing import in the test suite."""
    for aid, a in ACTIONS.items():
        vals = {m: 0 for f in (a.what, a.touched, a.budget) for m in _VAR.findall(f)}
        LedgerEntry(
            action=aid, category=a.category, what_happened=_render(a.what, vals),
            why=a.why, touched=_render(a.touched, vals), caveat=a.caveat,
            budget=_render(a.budget, vals), reversible=a.reversible, undo=a.undo,
        )
        check_grammar(a.category, a.what)
    check_grammar("source-admission", SKIPPED_FRAME)
    check_grammar("source-admission", FAILED_FRAME)


validate_registry()


def build_entry(action: str, result: Any = None, settings: Any = None) -> LedgerEntry:
    """The entry for one run of ``action``. A result carrying ``skipped`` or ``error``
    reads as such; anything else is the action's own sentence with its counts."""
    a = ACTIONS[action]
    res = result if isinstance(result, dict) else {}
    try:
        vals = dict(a.values(res, settings))
    except Exception:  # noqa: BLE001 - a result of an unexpected shape reads as zeros
        vals = {}
    for f in (a.what, a.touched, a.budget):
        for m in _VAR.findall(f):
            vals.setdefault(m, 0)
    what_frame, note = a.what, None
    if res.get("error"):
        what_frame = FAILED_FRAME
    elif res.get("skipped") and not isinstance(res.get("skipped"), int | float):
        what_frame = SKIPPED_FRAME
        note = str(res["skipped"])[:200]
    return LedgerEntry(
        action=action, category=a.category, what_happened=_render(what_frame, vals),
        why=a.why, touched=_render(a.touched, vals), caveat=a.caveat,
        budget=_render(a.budget, vals), reversible=a.reversible, undo=a.undo,
        frames={"what_happened": what_frame, "touched": a.touched, "budget": a.budget},
        vars=vals, note=note,
    )


# --------------------------------------------------------------------------- #
#  The file
# --------------------------------------------------------------------------- #

_LOCK = threading.Lock()
_WRITES = 0
#: Compact every this many writes, so the file stays bounded without a boot hook.
_COMPACT_EVERY = 200


def ledger_path() -> Path:
    return data_dir() / LEDGER_FILE


def _append(rec: dict[str, Any]) -> None:
    with _LOCK:
        p = ledger_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")


def record(action: str, result: Any = None, settings: Any = None) -> dict[str, Any] | None:
    """Write one entry for a run of ``action``. Never raises: returns the record, or None
    when it could not be written (the reason is in the debug log)."""
    try:
        global _WRITES
        rec = build_entry(action, result, settings).as_record()
        _append(rec)
        _WRITES += 1
        if _WRITES % _COMPACT_EVERY == 0:
            compact_if_needed()
        return rec
    except Exception:  # noqa: BLE001 - an instrument never breaks the thing it measures
        _LOG.debug("activity ledger: could not record %s", action, exc_info=True)
        return None


def read_entries(limit: int = 200) -> list[dict[str, Any]]:
    """The newest ``limit`` entries, newest first. A damaged line is skipped."""
    try:
        lines = ledger_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines):
        if len(out) >= max(0, limit):
            break
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("action"):
            out.append(rec)
    return out


def compact_if_needed(max_lines: int = MAX_LINES) -> int:
    """Keep the newest ``max_lines`` lines; returns how many were dropped."""
    try:
        with _LOCK:
            p = ledger_path()
            lines = p.read_text(encoding="utf-8").splitlines()
            if len(lines) <= max_lines:
                return 0
            keep = lines[-max_lines:]
            tmp = p.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(keep) + "\n", encoding="utf-8", newline="\n")
            os.replace(tmp, p)
            return len(lines) - len(keep)
    except OSError:
        return 0
