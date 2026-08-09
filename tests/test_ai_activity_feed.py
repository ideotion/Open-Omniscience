"""The AI details feed reads what the sweeps already write, under its own ceiling.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer ask 2026-08-09: "a collapsed 'details' section giving details about what
exactly has been done by the AI background metadata enhancement ... latest detected
keywords, languages, and so forth, and the amount total for each category, and the
remaining amount ... article processing per hour (per category + total)."

The fixtures use the REAL record shapes, taken from the log this repo actually has on
disk (`data/triage/oo-perception-extract-*.jsonl`) and from the `batch_record` builders
in `src/ai_layer/{triage,source_tags}.py` — a hand-invented shape would let the reader
pass while the shipped writer emitted something else.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.ai_layer.activity import (
    DEFAULT_TAIL_BYTES,
    newest_log,
    rates_from_batches,
    read_tail_records,
    recent_activity,
    run_activity_selftest,
)


def _write(path: Path, records: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
#  bounded reading — the reader's own ceiling, not an assumption about the writer
# --------------------------------------------------------------------------- #
def test_the_tail_reader_never_materialises_a_large_log(tmp_path):
    """A 1.6 GB journal read whole is how this app once OOM'd at boot, and a sweep left
    running for days writes a log whose size tracks how much there was to report."""
    log = tmp_path / "big.jsonl"
    filler = json.dumps({"schema": "x", "pad": "y" * 500}) + "\n"
    with log.open("w", encoding="utf-8") as fh:
        for _ in range(5000):  # ~2.5 MB
            fh.write(filler)
        fh.write(json.dumps({"schema": "x", "marker": "newest"}) + "\n")
    recs = read_tail_records(log, tail_bytes=16 * 1024)
    assert 0 < len(recs) < 200, f"{len(recs)} records: the ceiling did not bite"
    assert any(r.get("marker") == "newest" for r in recs), "the tail must reach the end"


def test_a_half_written_last_line_is_dropped_not_raised(tmp_path):
    """The normal state of a file being appended to right now."""
    log = tmp_path / "partial.jsonl"
    log.write_text(
        json.dumps({"schema": "x", "n": 1}) + "\n" + '{"schema": "x", "n": 2',
        encoding="utf-8",
    )
    recs = read_tail_records(log)
    assert [r["n"] for r in recs] == [1]


def test_a_missing_file_is_empty_not_an_exception(tmp_path):
    assert read_tail_records(tmp_path / "nope.jsonl") == []


def test_the_newest_log_is_chosen_by_name_not_mtime(tmp_path):
    """The names carry a sortable stamp, and a coordinator turn APPENDS to an older
    run's log — so mtime would pick a file the operator would not call current."""
    old = tmp_path / "oo-keyword-triage-20260101-000000-000000.jsonl"
    new = tmp_path / "oo-keyword-triage-20260202-000000-000000.jsonl"
    _write(new, [{"schema": "x"}])
    _write(old, [{"schema": "x"}])  # written LAST, so its mtime is newest
    assert newest_log(tmp_path, "oo-keyword-triage-") == new


# --------------------------------------------------------------------------- #
#  the two rates
# --------------------------------------------------------------------------- #
def test_the_two_rates_separate_the_model_from_the_scheduler():
    """Under the coordinator the sweeps take turns, so "how fast is the model" and
    "what does the corpus gain" are different numbers. Either alone misleads: the first
    promises a completion date the machine cannot keep, the second blames the model for
    the scheduler."""
    batches = [
        {"attempted": 10, "started_at": "2026-01-01T00:00:00",
         "finished_at": "2026-01-01T00:00:10"},
        {"attempted": 10, "started_at": "2026-01-01T00:01:40",
         "finished_at": "2026-01-01T00:01:50"},
    ]
    r = rates_from_batches(batches, item_key="attempted")
    assert r["measurable"] is True and r["batches"] == 2 and r["items"] == 20
    # 20 items over 20 s of actual work.
    assert r["while_working_per_hour"] == 3600.0
    # 20 items over a 110 s span, most of it waiting its turn.
    assert r["wall_clock_per_hour"] == 654.5
    assert r["while_working_per_hour"] > r["wall_clock_per_hour"]


def test_the_unit_is_the_sweeps_own_not_articles_for_everything():
    """Triage judges keywords, source-tags judges domains, perception processes
    articles. One label over three units would be a fabricated comparison."""
    r = rates_from_batches(
        [{"verdicts_out": 4, "started_at": "2026-01-01T00:00:00",
          "finished_at": "2026-01-01T00:00:04"}],
        item_key="verdicts_out",
    )
    assert r["item_unit"] == "verdicts_out" and r["items"] == 4


def test_a_batch_with_no_clock_yields_no_rate():
    r = rates_from_batches([{"attempted": 5}], item_key="attempted")
    assert r["measurable"] is False and r["reason"]


def test_a_sub_second_window_states_no_rate_rather_than_a_huge_one():
    """The real log on disk has a batch that starts and finishes in the same second.
    Dividing by that produces a number with precision it has not earned."""
    r = rates_from_batches(
        [{"attempted": 6, "started_at": "2026-01-01T00:00:00",
          "finished_at": "2026-01-01T00:00:00"}],
        item_key="attempted",
    )
    assert r["measurable"] is True
    assert r["while_working_per_hour"] is None and r["wall_clock_per_hour"] is None


def test_every_rate_states_the_window_it_covers():
    """A figure over the last few batches must never read as a figure over the run."""
    r = rates_from_batches(
        [{"attempted": 2, "started_at": "2026-01-01T00:00:00",
          "finished_at": "2026-01-01T00:00:05"}],
        item_key="attempted",
    )
    assert r["window_from"] and r["window_to"] and r["method"]


# --------------------------------------------------------------------------- #
#  per-sweep reading, against the real record shapes
# --------------------------------------------------------------------------- #
def test_perception_reads_the_shape_the_shipped_writer_emits(tmp_path):
    _write(
        tmp_path / "oo-perception-extract-20260101-000000-000000.jsonl",
        [
            {"schema": "oo-perception-extract-run-1", "started_at": "2026-01-01T00:00:00"},
            {"schema": "oo-perception-extract-batch-1", "batch": 0, "attempted": 6,
             "stored": 6, "who": 6, "where": 6, "when": 6, "last_id": 6,
             "started_at": "2026-01-01T00:00:00", "finished_at": "2026-01-01T00:00:12"},
        ],
    )
    got = recent_activity(directory=tmp_path)
    sweep = next(s for s in got["sweeps"] if s["key"] == "perception_extract")
    assert sweep["rates"]["measurable"] is True
    assert sweep["rates"]["items"] == 6


def test_perception_says_where_its_findings_are_rather_than_showing_an_empty_list(tmp_path):
    """Its batch records carry counts only — the names/places/dates go to ai_keyword.
    An empty `latest` with no explanation reads as "it found nothing"."""
    _write(
        tmp_path / "oo-perception-extract-20260101-000000-000000.jsonl",
        [{"schema": "oo-perception-extract-batch-1", "attempted": 1,
          "started_at": "2026-01-01T00:00:00", "finished_at": "2026-01-01T00:00:02"}],
    )
    sweep = next(
        s for s in recent_activity(directory=tmp_path)["sweeps"]
        if s["key"] == "perception_extract"
    )
    assert sweep["latest"] == [] and sweep["latest_note"]


def test_triage_surfaces_the_terms_it_judged(tmp_path):
    _write(
        tmp_path / "oo-keyword-triage-20260101-000000-000000.jsonl",
        [
            {"schema": "oo-keyword-triage-batch-1", "verdicts_out": 2,
             "started_at": "2026-01-01T00:00:00", "finished_at": "2026-01-01T00:00:04"},
            {"schema": "oo-keyword-triage-verdicts-1", "batch": 0,
             "verdicts": {"flooding": {"verdict": "keep", "kind": "term"},
                          "cookies": {"verdict": "drop", "kind": "furniture"}},
             "missing": []},
        ],
    )
    sweep = next(
        s for s in recent_activity(directory=tmp_path)["sweeps"]
        if s["key"] == "keyword_triage"
    )
    terms = {x["term"]: x.get("verdict") for x in sweep["latest"]}
    assert terms == {"flooding": "keep", "cookies": "drop"}


def test_source_tags_surfaces_the_domains_and_the_tags_proposed(tmp_path):
    _write(
        tmp_path / "oo-source-tags-20260101-000000-000000.jsonl",
        [
            {"schema": "oo-source-tags-batch-1", "sources_in": 1,
             "started_at": "2026-01-01T00:00:00", "finished_at": "2026-01-01T00:00:06"},
            {"schema": "oo-source-tags-detail-1", "domain": "example.org",
             "proposed_tags": ["science"], "status": "tagged"},
        ],
    )
    sweep = next(
        s for s in recent_activity(directory=tmp_path)["sweeps"]
        if s["key"] == "source_tags"
    )
    assert sweep["latest"][0]["domain"] == "example.org"
    assert sweep["latest"][0]["tags"] == ["science"]


def test_a_sweep_that_never_ran_says_so_instead_of_reporting_zero(tmp_path):
    for sweep in recent_activity(directory=tmp_path)["sweeps"]:
        if sweep["key"] == "langdetect":
            continue
        assert sweep["running_log"] is None
        assert sweep["note"], f"{sweep['key']} owes an explanation, not an empty rate"


def test_langdetect_is_honest_that_it_has_no_series_to_measure(tmp_path):
    """It writes one blob when a run ENDS, so there is no per-batch clock in a log. A
    rate derived from a single timestamp would be invented."""
    sweep = next(
        s for s in recent_activity(directory=tmp_path)["sweeps"] if s["key"] == "langdetect"
    )
    assert sweep["rates"]["measurable"] is False and sweep["rates"]["reason"]


def test_the_feed_states_why_a_working_sweep_can_look_idle(tmp_path):
    """The coordinator runs members directly rather than through their registered jobs,
    so each sweep's own status endpoint reads idle while the lane drives it. Without
    that stated, a busy machine reads as a stopped one."""
    note = recent_activity(directory=tmp_path)["coordinator"]["note"]
    assert "idle" in note.lower()


def test_no_session_is_a_stated_absence_not_a_crash(tmp_path):
    got = recent_activity(directory=tmp_path, session=None)
    assert got["stored"]["available"] is False and got["stored"]["reason"]


# --------------------------------------------------------------------------- #
#  honesty
# --------------------------------------------------------------------------- #
def test_no_field_name_carries_a_banned_substring(tmp_path):
    banned = ("score", "ranking", "rating", "grade")

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                low = str(k).lower()
                assert not any(b in low for b in banned), f"{path}.{k}"
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(recent_activity(directory=tmp_path))
    walk(run_activity_selftest())


def test_the_selftest_passes_and_is_registered_with_the_loop():
    from src.monitoring.recursive_loop import LOOP_SELFTESTS

    assert run_activity_selftest()["passed"] is True
    assert "ai-activity-selftest" in {n for n, _m, _f in LOOP_SELFTESTS}


def test_the_default_ceiling_is_a_real_bound():
    assert 0 < DEFAULT_TAIL_BYTES <= 2 * 1024 * 1024


def test_a_measured_zero_is_published_as_zero(tmp_path):
    """We looked, over a stated window, and found none. That is a measurement, and
    turning it into None would make "produced nothing lately" indistinguishable from
    "we could not tell" — the two are opposite answers. "Never ran" stays visible as a
    total of 0 beside it."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.ai_layer.activity import stored_activity
    from src.database.models import AiKeyword

    # A REAL session against an isolated engine, never a hand-written double: a stub of
    # this payload drifts the moment the reader consults one more field, and it fails
    # against correct code rather than catching a defect.
    engine = create_engine("sqlite://")
    AiKeyword.__table__.create(engine)
    with Session(engine) as session:
        out = stored_activity(session, recent=1, hours=24)
    for kind in out["kinds"]:
        assert kind["per_hour"] == 0.0, kind["kind"]
        assert kind["total"] == 0 and kind["in_window"] == 0


def test_a_real_row_is_counted_and_surfaced():
    """The negative-space twin. A reader that reports an honest zero for everything,
    forever, is indistinguishable from a working one until something is actually there."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from src.ai_layer.activity import stored_activity
    from src.database.models import AiKeyword

    engine = create_engine("sqlite://")
    AiKeyword.__table__.create(engine)
    now = datetime.now(UTC).replace(tzinfo=None)
    with Session(engine) as session:
        session.add_all([
            AiKeyword(article_id=1, term="fr", kind="language", language="fr",
                      model="m", created_at=now - timedelta(hours=1)),
            AiKeyword(article_id=2, term="Ministry of Health", kind="ai-who",
                      model="m", created_at=now - timedelta(minutes=5)),
            # Older than the window: counted in the total, not in the rate.
            AiKeyword(article_id=3, term="de", kind="language", language="de",
                      model="m", created_at=now - timedelta(days=9)),
        ])
        session.commit()
        out = stored_activity(session, recent=5, hours=24)

    by = {k["kind"]: k for k in out["kinds"]}
    assert by["language"]["total"] == 2, "the old row still counts toward the total"
    assert by["language"]["in_window"] == 1, "but not toward the window"
    assert by["language"]["per_hour"] == round(1 / 24, 1)
    assert by["ai-who"]["latest"][0]["term"] == "Ministry of Health"
    assert by["ai-who"]["latest"][0]["at"], "a found item carries when it was found"


# --------------------------------------------------------------------------- #
#  frontend: folded must not mean fetched
# --------------------------------------------------------------------------- #
def test_the_details_panel_polls_only_while_it_is_open():
    from tests.js_source_helper import function_body, read_static

    html = read_static("index.html")
    assert 'id="ai-activity-box"' in html and "onAiActivityToggle(this)" in html

    body = function_body(read_static("app.js"), "onAiActivityToggle")
    assert "el.open" in body, "the loader must be gated on the disclosure being open"
    assert "setInterval" in body and "clearInterval" in body, (
        "a details panel nobody opened must not cost a request every few seconds, and "
        "closing it must stop the one it started"
    )
