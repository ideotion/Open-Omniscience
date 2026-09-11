"""A DEFERRED Stage A row comes back, and comes back exactly once.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

The 2026-09-11 ruling: "no, never drop a refused row -- keep them deferred." A deferral is
not a verdict, so the row is owed another look, and Stage A looks at worklists. This builds
that worklist from finished runs.

Measured on the real fleet output the day the ruling shipped: 8 VM shards, 37,079 judged
institutions, 23,237 of them deferred -- 15,875 on robots alone, against 255 explicit
Disallows. That 62:1 is why the retry path exists rather than a `robots_unavailable` column
in a rejection file nobody reads again.

What these pin is the part a careless build would get wrong: a rejection is NOT a deferral,
a row must not be re-asked twice, and the earlier reason travels as CONTEXT, never as a
verdict the retry inherits.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.analysis.build_candidate_kit import WORKLIST_FIELDS
from scripts.analysis.build_retry_worklist import build

_ROOT = Path(__file__).resolve().parents[1]


def _run(tmp_path: Path, rows: list[dict], name: str = "w3") -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "verified.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return d


def _row(domain, status, reason, **kw):
    base = {"domain": domain, "name": domain.split(".")[0], "source_type": "institution",
            "country": "fr", "language_detected": "fr", "language_basis": "detected",
            "tags": ["government", "institution"], "status": status, "reason": reason}
    base.update(kw)
    return base


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_a_deferral_comes_back_and_a_real_rejection_does_not(tmp_path):
    """THE distinction the whole ruling rests on. A robots failure told us nothing about the
    outlet, so the row is owed another look. An explicit Disallow is the publisher's ANSWER,
    and a stale feed is a measurement -- re-asking either would be re-asking a settled
    question, which is both rude and pointless."""
    run = _run(tmp_path, [
        _row("deferred-robots.example", "deferred", "robots_unavailable"),
        _row("deferred-refused.example", "deferred", "robots_refused"),
        _row("deferred-down.example", "deferred", "homepage_unreachable"),
        _row("said-no.example", "rejected", "robots_disallowed"),
        _row("stale.example", "rejected", "feed_stale"),
        _row("nofeed.example", "rejected", "no_feed_found"),
        _row("good.example", "verified", "verified"),
    ])
    out = tmp_path / "worklist_5_retry.csv"
    stats = build([run], out)

    assert stats["judged"] == 7 and stats["written"] == 3
    domains = {r["domain"] for r in _read(out)}
    assert domains == {"deferred-robots.example", "deferred-refused.example",
                       "deferred-down.example"}
    assert "said-no.example" not in domains, (
        "an explicit Disallow is the publisher's answer -- re-asking it is exactly what the "
        "project promises never to do"
    )


def test_a_host_is_never_queued_twice_even_if_two_runs_overlap(tmp_path):
    """A fleet run shards BY HOST, so a domain cannot legitimately appear in two shards -- but
    re-running one shard would put it in two run directories, and silently doubling a
    publisher's request count is the one thing the politeness design must not do."""
    a = _run(tmp_path, [_row("dup.example", "deferred", "robots_unavailable")], "a")
    b = _run(tmp_path, [_row("dup.example", "deferred", "homepage_unreachable")], "b")
    out = tmp_path / "w.csv"
    stats = build([a, b], out)
    assert stats["judged"] == 2 and stats["written"] == 1
    assert [r["domain"] for r in _read(out)] == ["dup.example"]


def test_the_earlier_reason_travels_as_context_never_as_a_verdict(tmp_path):
    """The retry must judge the row FRESH. The reason is carried so an operator can see what
    is being re-asked, in ``flags`` -- the column that already means exactly that -- and not
    in any field the verifier reads as an outcome."""
    run = _run(tmp_path, [_row("x.example", "deferred", "robots_refused")])
    out = tmp_path / "w.csv"
    build([run], out)
    (row,) = _read(out)
    assert row["flags"] == "retry:robots_refused"
    assert row["tier"] == "institution" and row["source_type"] == "institution"
    assert "robots" not in row["tags"], "a robots outcome must not leak into the row's tags"
    assert set(row) == set(WORKLIST_FIELDS), (
        "the retry list must be a worklist in the KIT'S format, or none of the kit's "
        "machinery -- sharding, packaging, the RESULTS roll-up -- applies to it"
    )


def test_the_identity_fields_survive_the_round_trip(tmp_path):
    """They came from the export, and re-deriving them here would be a second implementation
    of the ladder that produced them."""
    run = _run(tmp_path, [_row("ministere.fr", "deferred", "robots_unavailable",
                               name="Ministere de la Culture", country="fr")])
    out = tmp_path / "w.csv"
    build([run], out)
    (row,) = _read(out)
    assert row["name"] == "Ministere de la Culture"
    assert row["country"] == "fr" and row["language"] == "fr"
    assert row["language_basis"] == "detected"
    assert row["tags"] == "government,institution"


def test_the_deferral_set_is_the_verifiers_own(tmp_path):
    """ANTI-DIVERGENCE. Two lists of "what counts as deferred" would drift, and the drift
    would be invisible: rows would quietly stop coming back."""
    from scripts.analysis import build_retry_worklist as brw
    from scripts.analysis.verify_candidate_feeds import DEFERRED_REASONS

    assert brw.DEFERRED_REASONS is DEFERRED_REASONS, (
        "the retry builder fell back to its own copy of the deferral set -- it must import "
        "the verifier's, or the two will disagree about which rows are owed another look"
    )
    assert "robots_disallowed" not in DEFERRED_REASONS


def test_a_run_directory_without_results_fails_loudly(tmp_path):
    """Silence here would produce an EMPTY retry worklist that looks like 'nothing to do'."""
    with pytest.raises(SystemExit, match="verified.jsonl"):
        build([tmp_path / "absent"], tmp_path / "w.csv")
