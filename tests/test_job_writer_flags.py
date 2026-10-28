"""Every background job that commits to the corpus says so: the ``is_writer`` inventory (R360, from the restore-writers audit).

``is_writer`` is read by one thing, the offline maintenance hold-off (``yield_reason`` in ``offline_maintenance.py``), which skips the WHOLE maintenance window (counter
reconcile, orphan prune, language reconcile, incremental vacuum, the hourly snapshot) while a writer job runs. It is checked when a tick starts and between continuation
passes; a writer job that starts mid-window does not end it. Two jobs
that commit to the corpus file, ``wikidata-items`` (``store_items``) and ``resolve-places`` (``resolve_mentioned``), were registered with ``is_writer=False``
under a comment whose premise (the flag would ask the operator to stop a collection pass) was wrong: that ask reads ``_DB_WRITER_KINDS`` in ``api/jobs.py``.

The inventory is by AST over every ``BackgroundJob(...)`` in ``src/``, so a new job cannot join the registry as a non-writer without a line here that says why: the
set of kinds NOT flagged is pinned exactly, in both directions. A job added with the flag omitted or False fails until its reason is written; a job named here
that becomes a writer fails until its row is removed.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"

#: Not a writer to the corpus file, one reason each (read from the job's module in the R360 pass; a new row needs the same reading).
NOT_CORPUS_WRITERS: dict[str, str] = {
    "ai-check": "reads: a connectivity and model probe",
    "all-diagnostics": "writes the diagnostics zip on disk",
    "bulletin-narration": "writes the edition JSON on disk (narration_job.py documents it)",
    "card-audit": "reads the corpus to audit briefing cards",
    "keyword-triage": "opens a session and adds nothing (triage_job.py)",
    "model-bench": "benchmarks a model; no corpus write",
    "p0-validation": "restores into a scratch copy; never commits the live corpus",
    "release-run-0-4": "starts collection, the wiki lane and the qualification drain through those jobs' own paths; commits nothing itself",
    "source-tags": "opens a session and adds nothing (source_tags_job.py)",
    "vllm-install": "installs a runtime; no database",
    "vllm-model-download": "downloads model files; no database",
    "wikidata-rings": "writes ring YAML on disk (insights.py)",
}

#: Jobs that DO commit to the corpus and are still not flagged, because flipping the flag is not the whole answer. Each row is an open decision, not a reason.
WRITERS_LEFT_UNFLAGGED: dict[str, str] = {
    "ai-coordinator": (
        "its sweeps commit (perception extraction per article, title and keyword translation), but it is a loop: when every sweep is done it sleeps 30 s and goes "
        "round again, so it stays `running` while the setting is on and a True flag would hold offline maintenance off for as long. OPEN DECISION (R362)"
    ),
}


def _jobs() -> dict[str, bool]:
    """kind (or ``module:CONSTANT`` when the kind is not a literal) -> is_writer is literally True."""
    found: dict[str, bool] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", getattr(node.func, "attr", None)) == "BackgroundJob"
            ):
                continue
            first = node.args[0] if node.args else None
            kind = (
                first.value
                if isinstance(first, ast.Constant)
                else f"{path.stem}:{getattr(first, 'id', '?')}"
            )
            flag = next((k.value for k in node.keywords if k.arg == "is_writer"), None)
            found[str(kind)] = isinstance(flag, ast.Constant) and flag.value is True
    return found


def test_the_inventory_finds_the_jobs_it_is_meant_to_see():
    jobs = _jobs()
    assert len(jobs) >= 29, "the scan lost jobs: it must see every BackgroundJob( in src/"
    assert (
        jobs["mailbox-pull"] is True and jobs["wikidata-rings"] is False
    )  # a known writer and a known non-writer


def test_the_jobs_that_commit_to_the_corpus_are_flagged_as_writers():
    jobs = _jobs()
    for kind in ("wikidata-items", "resolve-places"):
        assert jobs[kind] is True, (
            f"{kind} commits to the corpus file: it must be registered with is_writer=True"
        )


def test_the_set_of_non_writer_jobs_is_exactly_the_one_with_a_reason():
    jobs = _jobs()
    not_writers = {k for k, v in jobs.items() if not v}
    known = NOT_CORPUS_WRITERS.keys() | WRITERS_LEFT_UNFLAGGED.keys()
    assert not_writers - known == set(), (
        "a job is registered without is_writer=True and has no reason in NOT_CORPUS_WRITERS: read its module, then flag it or write the reason"
    )
    assert NOT_CORPUS_WRITERS.keys() - not_writers == set(), (
        "a job named in NOT_CORPUS_WRITERS is now a writer (or gone): remove its row"
    )
