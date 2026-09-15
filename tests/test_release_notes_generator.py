"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Guards for ``scripts/release_notes.py`` — the Q111 = a release-notes generator.

WHAT THESE ARE SHAPED AGAINST. The generator's whole value is that a reader can
re-open a release body and check every line against ``shipped.csv``. Three ways that
value evaporates, and there is one guard family per way:

1. **A row lands in the wrong bucket.** The selection rule has four outcomes and the
   fixtures below make all four reachable, with the entities distinguishable — the
   recorded "a fixture where two dates coincide cannot test which one a rule used"
   trap, so the previous tag's day, the tag's day and a row's own day are all
   different values here.
2. **A refusal fails open.** The ``PR pending`` check is the one the brief names, and
   its twins matter more than the positive case: a placeholder OUT of range must not
   refuse (or no notes could ever be produced while one historical row carries one),
   and a row whose SUMMARY merely mentions the phrase must not refuse either — the
   2026-09-11 lesson that a ledger which records its own maintenance will always
   match a whole-file grep for the thing it retired.
3. **A value is mirrored instead of read.** The outbound call sites and the
   verification bar both live in other files. A hardcoded copy fails in the
   safe-looking direction, so the guards prove the reader FOLLOWS a changed source
   and REFUSES a shape it cannot parse — never falls back to a last-known value.

Every guard here was mutation-checked: each assertion was re-run with the mechanism
it names neutered, and each reddens by name. Where a mutation survived, it is
recorded in the test's own docstring rather than left as coverage.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "release_notes.py"
_REAL_CSV = _ROOT / "docs" / "ledger" / "shipped.csv"
_RELEASE_YML = _ROOT / ".github" / "workflows" / "release.yml"
_GATE = _ROOT / "docs" / "product" / "RELEASE_0.4_GATE.md"
_CONSENT_TEST = _ROOT / "tests" / "test_network_consent.py"


def _load():
    """Load the shipped script by path — never a re-typed copy, so a guard here can
    only ever pass against the file the workflow calls.

    It is registered in ``sys.modules`` BEFORE execution because ``@dataclass`` resolves
    its annotations through ``sys.modules[cls.__module__]``; an unregistered module
    raises there, which reads as a bug in the script rather than in the loader.
    """
    spec = importlib.util.spec_from_file_location("_release_notes", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rn = _load()


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
_HEADER = ["date", "area", "item", "status", "refs", "key_paths", "summary"]

#: The four selection outcomes plus one row strictly before the previous tag, each
#: with a DISTINCT area so an assertion can name which one moved. The previous tag's
#: day (2026-02-10), the tag's day (2026-03-01) and every row date are different
#: values: a fixture where two of them coincide cannot say which one the rule read.
_ROWS = [
    ("2026-01-05", "old/before", "shipped in the previous release", "shipped", "PR #1"),
    ("2026-02-10", "edge/boundary", "dated on the previous tag's own day", "shipped", "PR #2"),
    ("2026-02-11", "core/first", "the first row of this release", "shipped", "PR #3"),
    ("2026-03-01", "core/tagday", "dated on the tag's own day", "partial", "PR #4"),
    ("2026-03-02", "later/after", "landed after the tag was cut", "shipped", "PR #5"),
    ("", "undated/nodate", "a row no range can place", "shipped", "PR #6"),
]

_PREV_DAY, _TAG_DAY = "2026-02-10", "2026-03-01"


def _write_csv(path: Path, rows, *, crlf: bool = False, extra=()) -> Path:
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\r\n" if crlf else "\n")
    w.writerow(_HEADER)
    for r in rows:
        date, area, item, status, refs = r
        w.writerow([date, area, item, status, refs, "src/x.py", f"summary of {area}"])
    for r in extra:
        w.writerow(r)
    path.write_bytes(buf.getvalue().encode("utf-8"))
    return path


def _accounting(*, returncode: int) -> dict:
    """An accounting dict shaped like the one ``build`` really returns.

    Deliberately not a two-key stub: a double that omits a field production always
    supplies sends the code under test down a path production never takes, and the
    repair for that belongs in the double rather than in a `.get()` that papers over
    it in `main`. Keys here mirror `build`'s own return.
    """
    return {
        "tag": "v9.9.9", "tag_day": _TAG_DAY, "previous_tag": "v9.9.8",
        "previous_day": _PREV_DAY, "unshallowed": False, "in_range": 3, "boundary": 1,
        "after_tag": 0, "undated": 0, "telemetry_mode": "run",
        "telemetry_returncode": returncode, "telemetry_summary": "7 passed in 9.25s",
        "outbound_call_sites": 9, "body_bytes": 5,
    }


def test_the_accounting_double_matches_what_build_really_returns():
    """Pins the double to production's own key set, so it cannot drift into describing
    an accounting `build` could never produce."""
    import inspect

    src = inspect.getsource(rn.build)
    double = _accounting(returncode=0)
    for key in double:
        assert f'"{key}"' in src, f"the double invents a key build never sets: {key}"
    # AND THE OTHER DIRECTION, which is the half that was missing. One-way pinning
    # catches a double that over-claims but is blind to a double that has fallen
    # BEHIND production -- and that blindness has a cost this file already names:
    # with the double short a key, the honest repair (index it in `main`) reddens the
    # suite, so the path of least resistance is the `.get()` this helper's own
    # docstring rules out. Adding `telemetry_summary` to `build` walked straight into
    # it. Now a key added to `build` must be added here too.
    for key in re.findall(r'^\s{8}"([a-z_]+)":', src, re.M):
        assert key in double, (
            f"build sets {key!r} and the double does not -- add it here rather than "
            f"reaching for .get() in main"
        )


def _selection(tag="v9.9.9", prev="v9.9.8", prev_day=_PREV_DAY, tag_day=_TAG_DAY):
    return rn.Selection(tag=tag, tag_day=tag_day, prev_tag=prev, prev_day=prev_day)


def _select_fixture(tmp_path, rows=_ROWS, **kw):
    path = _write_csv(tmp_path / "shipped.csv", rows, **kw)
    return rn.select(rn.read_rows(path), _selection())


# --------------------------------------------------------------------------- #
# 1. the selection rule — all four outcomes, each reachable and distinguishable
# --------------------------------------------------------------------------- #
def test_every_row_lands_in_exactly_one_bucket_and_the_buckets_are_the_rule(tmp_path):
    """The stated rule: prev < date <= tagd is the body; == prev is ambiguous; > tagd is
    out; a non-ISO date can never be placed. A fixture whose dates all differ is what
    makes 'which bucket' answerable at all."""
    sel = _select_fixture(tmp_path)
    assert [r["area"] for r in sel.in_range] == ["core/first", "core/tagday"]
    assert [r["area"] for r in sel.boundary] == ["edge/boundary"]
    assert [r["area"] for r in sel.after_tag] == ["later/after"]
    assert [r["area"] for r in sel.undated] == ["undated/nodate"]
    # The fifth row is in NO bucket: it belongs to the previous release. Asserting the
    # partition (rather than only the four lists) is what catches a rule that silently
    # double-counts or drops.
    placed = len(sel.in_range) + len(sel.boundary) + len(sel.after_tag) + len(sel.undated)
    assert placed == len(_ROWS) - 1


def test_a_row_on_the_tag_s_own_day_is_INCLUDED_and_one_on_the_previous_tag_s_is_not(tmp_path):
    """The two day-resolution decisions, pinned apart. They are opposite calls on the
    same ambiguity and a single test of 'the boundary works' cannot tell them apart."""
    sel = _select_fixture(tmp_path)
    assert any(r["date"] == _TAG_DAY for r in sel.in_range)
    assert not any(r["date"] == _PREV_DAY for r in sel.in_range)


def test_with_no_previous_tag_everything_up_to_the_tag_is_in_range(tmp_path):
    """``previous_tag`` returning None is a real state — the first tagged release —
    and must not be read as 'no rows'."""
    path = _write_csv(tmp_path / "shipped.csv", _ROWS)
    sel = rn.select(
        rn.read_rows(path),
        rn.Selection(tag="v0.1.0", tag_day=_TAG_DAY, prev_tag=None, prev_day=None),
    )
    assert {r["area"] for r in sel.in_range} == {
        "old/before", "edge/boundary", "core/first", "core/tagday"
    }
    assert not sel.boundary


def test_the_body_lists_in_range_rows_and_holds_the_boundary_rows_apart(tmp_path):
    """Behavioural, not a grep for a heading: the ambiguous row must be present (so it is
    not lost) and must NOT be inside a body area group (so it is not claimed)."""
    sel = _select_fixture(tmp_path)
    body = rn.render(
        sel,
        group_by="segment",
        telemetry=rn.TelemetryCheck(mode="skip"),
        sites={"src/x.py": "a reason long enough to be a reason"},
        covered=("socket",),
        bar="a bar",
        head_sha="deadbeef",
    )
    first = body.index("the first row of this release")
    boundary_at = body.index("dated on the previous tag's own day")
    heading = body.index("Dated on `v9.9.8`'s own day")
    assert first < heading < boundary_at, "the ambiguous row must sit under its own heading"
    assert "landed after the tag was cut" not in body
    assert "a row no range can place" not in body
    assert "shipped in the previous release" not in body


def test_the_accounting_counts_are_the_FULL_counts_not_what_was_listed(tmp_path):
    """Anti-capping: a cap may bound which examples are listed and may never bound a
    reported number. The `after_tag` line reports an exact count and a date span; the
    truncation line reports how many fields were clipped, not how many were shown."""
    rows = list(_ROWS) + [
        (f"2026-03-{d:02d}", f"late/{d}", "x" * 400, "y" * 200, "PR #9")
        for d in range(3, 13)
    ]
    path = _write_csv(tmp_path / "shipped.csv", rows)
    sel = rn.select(rn.read_rows(path), _selection())
    body = rn.render(
        sel,
        group_by="segment",
        telemetry=rn.TelemetryCheck(mode="skip"),
        sites={"src/x.py": "a reason long enough to be a reason"},
        covered=("socket",),
        bar="a bar",
        head_sha="deadbeef",
    )
    assert "**11**, dated 2026-03-02 … 2026-03-12" in body, "the exact count and span"
    assert "Rows carrying no `YYYY-MM-DD` date, which no range can place: **1**" in body


def test_a_long_field_is_truncated_MARKED_and_the_truncation_is_disclosed(tmp_path):
    """A silent truncation is a fabricated field. The mark and the disclosure are two
    separate halves and each needs its own assertion.

    THE NEEDLE IS THE EXACT CLIPPED VALUE, not a bare `…`. A first draft asserted
    ``"…" in body`` and SURVIVED the mutation that removes the mark — because the
    disclosure sentence one section down quotes the very character it describes
    ("Truncated for length and marked `…`"). That is the recorded trap of a guard
    satisfied by its own explanation, arriving in a rendered document rather than in
    source, and only the mutation said so.
    """
    rows = [("2026-02-15", "big/row", "I" * 500, "S" * 300, "PR #7")]
    path = _write_csv(tmp_path / "shipped.csv", rows)
    sel = rn.select(rn.read_rows(path), _selection())
    body = rn.render(
        sel,
        group_by="segment",
        telemetry=rn.TelemetryCheck(mode="skip"),
        sites={"src/x.py": "a reason long enough to be a reason"},
        covered=("socket",),
        bar="a bar",
        head_sha="deadbeef",
    )
    assert "I" * 500 not in body, "the cap must bite"
    assert "I" * (rn._ITEM_CAP - 1) + "…" in body, "the clipped item must carry the mark"
    assert "S" * (rn._STATUS_CAP - 1) + "…" in body, "the clipped status must carry it too"
    assert "**1** `item` field(s) over 200" in body
    assert "**1** `status` field(s) over 60" in body


# --------------------------------------------------------------------------- #
# 2. the refusals — each with the twin that stops it firing on correct input
# --------------------------------------------------------------------------- #
def test_a_PR_pending_placeholder_in_a_CITED_row_is_refused_by_name(tmp_path):
    """Protocol rule (5b): the placeholder is not a value. Publishing one makes a
    permanent citation out of a to-do, so the generator refuses rather than emitting it."""
    rows = list(_ROWS) + [("2026-02-20", "held/row", "swept later", "shipped", "PR pending")]
    path = _write_csv(tmp_path / "shipped.csv", rows)
    sel = rn.select(rn.read_rows(path), _selection())
    with pytest.raises(rn.ReleaseNotesError) as exc:
        rn.refuse_placeholders(sel)
    assert "held/row" in str(exc.value), "the refusal must name the row, not just fail"
    assert "5b" in str(exc.value)


def test_a_placeholder_on_the_BOUNDARY_day_is_also_refused(tmp_path):
    """The boundary rows are cited too — they are listed in the body under their own
    heading — so the refusal has to cover them. Scoping it to ``in_range`` alone would
    publish a placeholder through the one section built to be read carefully."""
    rows = [(_PREV_DAY, "edge/held", "on the seam", "shipped", "PR pending")]
    path = _write_csv(tmp_path / "shipped.csv", rows)
    sel = rn.select(rn.read_rows(path), _selection())
    assert sel.boundary and not sel.in_range
    with pytest.raises(rn.ReleaseNotesError):
        rn.refuse_placeholders(sel)


def test_a_placeholder_OUTSIDE_the_range_does_NOT_refuse(tmp_path):
    """The negative-space twin, and the one that makes the guard usable: a historical
    row's unswept placeholder is somebody else's release's problem. A refusal scoped to
    the file rather than to the cited rows would block every release forever."""
    rows = [
        ("2026-01-01", "old/held", "an old unswept row", "shipped", "PR pending"),
        ("2026-03-05", "late/held", "a future unswept row", "shipped", "PR pending"),
        ("2026-02-15", "core/ok", "a real row", "shipped", "PR #8"),
    ]
    path = _write_csv(tmp_path / "shipped.csv", rows)
    sel = rn.select(rn.read_rows(path), _selection())
    rn.refuse_placeholders(sel)  # must not raise


def test_the_placeholder_check_reads_the_refs_COLUMN_never_the_file(tmp_path):
    """The 2026-09-11 lesson, pinned: a ledger that records its own maintenance will
    always match a whole-file grep for the phrase it retired. This row's SUMMARY quotes
    the placeholder while its `refs` carries a real number — a file-level check refuses
    it and is wrong; the column-aware one accepts it."""
    rows = [("2026-02-15", "ledger/sweep", "swept the PR pending placeholders", "shipped", "PR #1132")]
    extra_summary = 'the phrase "PR pending" now returns 0 in the refs column'
    path = _write_csv(tmp_path / "shipped.csv", rows)
    raw = path.read_bytes().replace(b"summary of ledger/sweep", extra_summary.encode())
    path.write_bytes(raw)
    sel = rn.select(rn.read_rows(path), _selection())
    assert sel.in_range and "PR pending" in (sel.in_range[0]["summary"] or "")
    rn.refuse_placeholders(sel)  # must not raise
    assert b"PR pending" in path.read_bytes(), "the fixture must really contain the phrase"


def test_a_dirty_tree_is_refused(monkeypatch):
    """Notes name a SHA, so they must describe that SHA."""
    monkeypatch.setattr(rn, "_git", lambda *a, **k: " M src/x.py")
    with pytest.raises(rn.ReleaseNotesError, match="dirty"):
        rn.require_clean_tree()


def test_a_clean_tree_is_accepted(monkeypatch):
    """The twin: a guard that refuses everything is not a guard."""
    monkeypatch.setattr(rn, "_git", lambda *a, **k: "")
    rn.require_clean_tree()


def test_a_clone_that_stays_shallow_is_refused_and_says_why(monkeypatch):
    """CLAUDE.md rule (5b): a truncated history answers every 'when did this first
    appear' question with its own boundary, and nothing distinguishes that from a real
    answer. Here it would silently move the previous tag and therefore the whole range."""
    monkeypatch.setattr(rn, "_git", lambda *a, **k: "true")
    with pytest.raises(rn.ReleaseNotesError) as exc:
        rn.ensure_unshallow()
    assert "SHALLOW" in str(exc.value) and "5b" in str(exc.value)


def test_a_shallow_clone_that_unshallows_is_accepted_and_reports_that_it_did(monkeypatch):
    """The twin. And the return value is load-bearing: the accounting records whether
    the generator had to repair the clone, so a reader can tell a full clone from a
    repaired one."""
    answers = iter(["true", "", "false"])
    monkeypatch.setattr(rn, "_git", lambda *a, **k: next(answers))
    assert rn.ensure_unshallow() is True


def test_a_full_clone_never_fetches(monkeypatch):
    calls: list[tuple] = []

    def fake(*args, **kwargs):
        calls.append(args)
        return "false"

    monkeypatch.setattr(rn, "_git", fake)
    assert rn.ensure_unshallow() is False
    assert not any("fetch" in a for a in calls), "a full clone must not touch the network"


# --------------------------------------------------------------------------- #
# 3. values read from their source of truth, never mirrored
# --------------------------------------------------------------------------- #
def test_the_outbound_call_sites_come_from_the_consent_test_itself():
    """Read, not mirrored. The list in the notes IS ``_ALLOWED_SOCKET_IMPORTERS``, so a
    module added to (or removed from) the ratchet's allowlist reaches the notes with no
    second edit — which is what stops the notes describing an older app than the one
    being tagged."""
    sites, covered = rn.outbound_call_sites()
    src = _CONSENT_TEST.read_text(encoding="utf-8")
    assert sites and covered
    for path in sites:
        assert f'"{path}"' in src
    assert "src/ingest/__init__.py" in sites and "src/safety/fetcher.py" in sites
    assert "requests" in covered and "opentimestamps" in covered


def test_the_reader_FOLLOWS_a_changed_allowlist(tmp_path):
    """The discriminating case a mirror passes: change the source and the reader has to
    change with it. A hardcoded copy passes every assertion above and fails this one."""
    fake = tmp_path / "t.py"
    fake.write_text(
        '_SOCKET_CAPABLE_MODULES = ("socket",)\n'
        '_ALLOWED_SOCKET_IMPORTERS: dict[str, str] = {"src/only/here.py": "because"}\n',
        encoding="utf-8",
    )
    sites, covered = rn.outbound_call_sites(fake)
    assert sites == {"src/only/here.py": "because"}
    assert covered == ("socket",)


def test_an_unreadable_allowlist_REFUSES_rather_than_falling_back(tmp_path):
    """"When the source of truth is refactored into a shape your parser cannot read,
    FAIL LOUDLY" — falling back to a last-known value is the mirror bug with extra
    steps, and it fails toward 'everything is fine'."""
    fake = tmp_path / "t.py"
    fake.write_text("def build(): return {}\n", encoding="utf-8")
    with pytest.raises(rn.ReleaseNotesError, match="_ALLOWED_SOCKET_IMPORTERS"):
        rn.outbound_call_sites(fake)

    fake.write_text('_ALLOWED_SOCKET_IMPORTERS: dict[str, str] = {"a": "b"}\n', encoding="utf-8")
    with pytest.raises(rn.ReleaseNotesError, match="_SOCKET_CAPABLE_MODULES"):
        rn.outbound_call_sites(fake)


def test_the_verification_bar_is_read_from_the_gate_and_is_Q1128s_sentence():
    """The bar lives in ``RELEASE_0.4_GATE.md`` behind its marker. Asserting the WORDS
    here as well as the mechanism is deliberate: the mechanism test alone would pass
    against a gate that had been reworded into something else entirely."""
    bar = rn.verification_bar()
    assert bar == (
        "Chromium in the sandbox + the maintainer's click-through = verified; "
        "Gecko best-effort."
    )
    assert rn._BAR_MARKER in _GATE.read_text(encoding="utf-8")


def test_the_bar_reader_FOLLOWS_the_gate_and_REFUSES_when_the_marker_goes(tmp_path):
    """Both directions. Following proves it is not a copy; refusing proves it does not
    quote silence — an empty bar would render a blockquote with nothing in it, which
    reads as the bar having been dropped."""
    fake = tmp_path / "gate.md"
    fake.write_text(f"noise\n\n{rn._BAR_MARKER}\n> a different bar entirely.\n\nmore\n", encoding="utf-8")
    assert rn.verification_bar(fake) == "a different bar entirely."

    fake.write_text("no marker here\n> a bar\n", encoding="utf-8")
    with pytest.raises(rn.ReleaseNotesError, match="verification-bar"):
        rn.verification_bar(fake)

    fake.write_text(f"{rn._BAR_MARKER}\n\nnot a blockquote\n", encoding="utf-8")
    with pytest.raises(rn.ReleaseNotesError, match="blockquote"):
        rn.verification_bar(fake)


def test_the_working_mode_carries_the_same_bar_sentence():
    """Two documents, one sentence. The working mode is what a BUILDING session reads and
    the gate is what the notes CITE; if they drift, a session stamps a surface against a
    bar the release does not claim."""
    wm = (
        _ROOT / "docs" / "plans" / "2026-09-12-beta-pathway" / "_WORKING_MODE.md"
    ).read_text(encoding="utf-8")
    flat = " ".join(wm.split())
    assert (
        "Chromium in the sandbox + the maintainer's click-through = verified; "
        "Gecko best-effort." in flat
    )


# --------------------------------------------------------------------------- #
# 4. the no-telemetry re-check — never templated as a pass
# --------------------------------------------------------------------------- #
def test_skip_states_plainly_that_nothing_was_re_checked(tmp_path):
    """An OMITTED section would read as 'nothing to say'. The explicit line is the point:
    a release body that does not carry the re-check has to say so in the same place the
    re-check would have been."""
    body = rn.render(
        _selection(),
        group_by="segment",
        telemetry=rn.TelemetryCheck(mode="skip"),
        sites={"src/x.py": "a reason long enough to be a reason"},
        covered=("socket",),
        bar="a bar",
        head_sha="deadbeef",
    )
    assert "NOT RE-CHECKED in this run" in body
    assert "it is not a pass" in body
    assert "PASSED" not in body


def test_a_failing_ratchet_is_reported_as_FAILED_and_exits_non_zero(monkeypatch, tmp_path):
    """The whole ritual exists to re-confirm a claim made to the user. A run that fails
    must not publish past this step, and the body must say which way it went."""
    body = rn.render(
        _selection(),
        group_by="segment",
        telemetry=rn.TelemetryCheck(
            mode="run", command=["python", "-m", "pytest"], returncode=1, summary="1 failed"
        ),
        sites={"src/x.py": "a reason long enough to be a reason"},
        covered=("socket",),
        bar="a bar",
        head_sha="deadbeef",
    )
    assert "exit **1** (FAILED)" in body and "1 failed" in body

    monkeypatch.setattr(rn, "build", lambda args: ("body\n", _accounting(returncode=1)))
    out = tmp_path / "n.md"
    assert rn.main(["--tag", "v9.9.9", "-o", str(out)]) == 1


def test_a_passing_ratchet_exits_zero(monkeypatch, tmp_path):
    """The twin: an exit code that is always non-zero blocks every release."""
    monkeypatch.setattr(rn, "build", lambda args: ("body\n", _accounting(returncode=0)))
    out = tmp_path / "n.md"
    assert rn.main(["--tag", "v9.9.9", "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == "body\n"


def test_the_ratchet_run_captures_the_REAL_exit_code_and_summary(tmp_path):
    """Driven against a real pytest run over a throwaway file, in both directions —
    a check that only ever sees a green environment cannot tell a pass from a template."""
    good = tmp_path / "test_good.py"
    good.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    bad = tmp_path / "test_bad.py"
    bad.write_text("def test_no():\n    assert False\n", encoding="utf-8")

    ok = rn.run_telemetry_check("run", str(good))
    assert ok.returncode == 0 and "passed" in (ok.summary or "")
    nope = rn.run_telemetry_check("run", str(bad))
    assert nope.returncode != 0 and "failed" in (nope.summary or "")


def test_the_notes_name_every_outbound_call_site_with_its_reason(tmp_path):
    """A count with no names is not an enumeration. The notes carry each path AND the
    sentence recorded beside it, because the reason is what a reader checks."""
    sites = {
        "src/a.py": "reason A, long enough to say something",
        "src/b.py": "reason B, also long enough",
        "src/c.py": "reason C, so the two counts differ",
    }
    covered = ("socket", "requests")
    body = rn.render(
        _selection(),
        group_by="segment",
        telemetry=rn.TelemetryCheck(mode="skip"),
        sites=sites,
        covered=covered,
        bar="a bar",
        head_sha="deadbeef",
    )
    for path, reason in sites.items():
        assert f"`{path}` — {reason}" in body
    # The two counts are DIFFERENT lengths on purpose. With both at 2 the assertion
    # `"**2**" in body` reads as a claim about `sites` and is in fact ambiguous between
    # them — it survives today only because one count is bolded and the other is not,
    # which is a rendering detail an edit could flip without turning anything red.
    assert len(sites) != len(covered), "the fixture must be able to tell the two apart"
    assert f"**{len(sites)}**" in body
    assert f"{len(covered)} socket-capable libraries" in body


# --------------------------------------------------------------------------- #
# 5. the ledger is read as bytes and parsed as CSV
# --------------------------------------------------------------------------- #
def test_a_CRLF_ledger_parses_identically_to_an_LF_one(tmp_path):
    """``shipped.csv`` is mixed CRLF / LF (17 CRLF rows on 2026-09-15). A reader that
    normalises or splits on lines would disagree between the two."""
    lf = rn.read_rows(_write_csv(tmp_path / "lf.csv", _ROWS))
    crlf = rn.read_rows(_write_csv(tmp_path / "crlf.csv", _ROWS, crlf=True))
    assert lf == crlf
    assert b"\r\n" in (tmp_path / "crlf.csv").read_bytes(), "the fixture must really be CRLF"


def test_a_quoted_multi_line_summary_is_ONE_row(tmp_path):
    """No row in the ledger spans lines today, which is exactly why this is pinned: the
    day one does, a line-oriented reader silently turns it into two rows — one of them a
    fragment that would be rendered as a release line."""
    path = tmp_path / "ml.csv"
    _write_csv(
        path,
        [("2026-02-15", "multi/line", "a row", "shipped", "PR #1")],
        extra=[["2026-02-16", "multi/two", "second", "shipped", "PR #2", "src/y.py", "line one\nline two"]],
    )
    rows = rn.read_rows(path)
    assert len(rows) == 2
    assert rows[1]["summary"] == "line one\nline two"
    assert rows[1]["area"] == "multi/two"


def test_the_generator_never_writes_the_ledger(tmp_path):
    """A generator that round-trips the CSV would rewrite every CRLF row — the recorded
    ``read_text`` normalisation defect, which on a ``merge=union`` file becomes duplicate
    rows in the permanent record. Proven by bytes, not by reading the code."""
    path = _write_csv(tmp_path / "shipped.csv", _ROWS, crlf=True)
    before = path.read_bytes()
    sel = rn.select(rn.read_rows(path), _selection())
    rn.render(
        sel,
        group_by="segment",
        telemetry=rn.TelemetryCheck(mode="skip"),
        sites={"src/x.py": "a reason long enough to be a reason"},
        covered=("socket",),
        bar="a bar",
        head_sha="deadbeef",
    )
    assert path.read_bytes() == before


def test_a_ledger_missing_a_column_is_refused(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_bytes(b"date,area\n2026-02-15,x\n")
    with pytest.raises(rn.ReleaseNotesError, match="missing column"):
        rn.read_rows(path)


# --------------------------------------------------------------------------- #
# 6. against the REAL ledger and the REAL tags (the brief's own acceptance)
# --------------------------------------------------------------------------- #
def test_the_real_ledger_partitions_exactly_for_the_real_tag_range():
    """The brief asks for the generator run on the real CSV and the current tag range.
    The property that survives the ledger growing: every row lands in exactly one of the
    five places, and the four reported buckets plus the un-reported 'before' account for
    all of them."""
    rows = rn.read_rows(_REAL_CSV)
    sel = rn.select(
        rows, rn.Selection(tag="v0.3.0", tag_day="2026-08-23", prev_tag="v0.2.0", prev_day="2026-07-18")
    )
    before = [
        r
        for r in rows
        if rn._ISO_DAY.match((r.get("date") or "").strip()) and (r["date"] or "") < "2026-07-18"
    ]
    assert (
        len(sel.in_range) + len(sel.boundary) + len(sel.after_tag) + len(sel.undated) + len(before)
        == len(rows)
    )
    assert sel.in_range, "the real v0.2.0..v0.3.0 range is not empty"
    assert sel.undated, "the ledger really does carry undated rows (8 on 2026-09-15)"


def test_the_real_ledger_carries_no_placeholder_any_release_would_cite():
    """Protocol rule (5b) as a live check rather than a habit: if this reddens, a row was
    written before its PR number existed and has not been swept."""
    rows = rn.read_rows(_REAL_CSV)
    offenders = [r for r in rows if rn.refs_carry_placeholder(r)]
    assert not offenders, (
        "unswept `PR pending` placeholder(s) in shipped.csv's refs column: "
        + ", ".join(f"{r['date']} {r['area']}" for r in offenders)
    )


def test_the_generator_runs_end_to_end_on_the_real_tree(tmp_path):
    """A subprocess drive of the shipped script, not of an imported copy: it is what the
    workflow calls, and the CLI is part of the contract."""
    out = tmp_path / "body.md"
    proc = subprocess.run(
        [
            sys.executable, str(_SCRIPT),
            "--tag", "v0.3.0",
            "--telemetry-check", "skip",
            "--allow-dirty",
            "-o", str(out),
        ],
        cwd=_ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    body = out.read_text(encoding="utf-8")
    assert "### What shipped since `v0.2.0`" in body
    assert "### No-telemetry re-check" in body
    assert "### Verification bar" in body
    assert rn.verification_bar() in body


# --------------------------------------------------------------------------- #
# 7. the workflow wiring — and what it must NOT have touched
# --------------------------------------------------------------------------- #
def _release_workflow() -> dict:
    """Parsed, not sliced. A YAML parse is structurally stronger than a source grep and
    keeps this file out of the ad-hoc-slicer budget."""
    return yaml.safe_load(_RELEASE_YML.read_text(encoding="utf-8"))


def _release_steps() -> list[dict]:
    return _release_workflow()["jobs"]["release"]["steps"]


def test_the_workflow_produces_the_notes_with_the_generator():
    """Behaviourally anchored on the step that writes the body: a grep for the script's
    name anywhere in the file would pass against a step that never runs."""
    runs = [s.get("run", "") for s in _release_steps()]
    assert any("scripts/release_notes.py" in r for r in runs), (
        "release.yml must call the generator where the notes are produced"
    )
    joined = "\n".join(runs)
    assert "release_notes.md" in joined


def test_the_v_star_trigger_the_prerelease_rule_and_the_tag_check_are_untouched():
    """The three things S04-15 says this slice may not change. Pinned by their MEANING —
    the parsed trigger, the 0.x pre-release case, the tag-vs-pyproject refusal — so a
    reformat does not redden them and a real change does."""
    wf = _release_workflow()
    # PyYAML parses a bare `on:` key as the boolean True.
    triggers = wf.get("on", wf.get(True))
    assert triggers["push"]["tags"] == ["v*"]
    runs = "\n".join(s.get("run", "") for s in _release_steps())
    assert 'case "${TAG#v}" in 0.*) prerelease="--prerelease" ;; esac' in runs
    assert 'echo "::error::tag v$tag does not match pyproject version $pkg"' in runs
    assert "--verify-tag" in runs


def test_the_release_job_still_gates_on_the_full_suite():
    """``needs: test`` is what stops a tag publishing attested-broken artifacts (the
    2026-07-02 RC). Adding a notes step must not have loosened it."""
    wf = _release_workflow()
    assert wf["jobs"]["release"]["needs"] == "test"
    assert "pytest" in wf["jobs"]["test"]["steps"][-1]["run"]


def test_the_release_checkout_fetches_enough_history_for_the_previous_tag():
    """The generator needs the tags and the history to answer 'since the previous tag',
    and it REFUSES a shallow clone rather than answering from the truncation point. The
    default checkout is depth 1, so this is the half that makes the refusal never fire
    in CI — belt and braces, deliberately, since the script's refusal is the net."""
    checkout = next(
        s for s in _release_steps() if "actions/checkout" in (s.get("uses") or "")
    )
    assert str(checkout.get("with", {}).get("fetch-depth")) == "0"


# --------------------------------------------------------------------------- #
# 8. the adversarial round — nine findings, each with the guard it earned
#
# Every test below exists because a defect was REPRODUCED, not imagined. Finding 1
# was live on this branch when it was found: the generator refused, and in
# `release.yml` under `set -euo pipefail` that refusal blocks the whole
# release-publish step.
# --------------------------------------------------------------------------- #
def test_a_PROSE_MENTION_of_the_marker_does_not_hijack_the_bar(tmp_path):
    """The regression that was live. `str.find` takes the FIRST textual occurrence, and
    the gate's own board table names the marker in a sentence 270 lines above the real
    one — which is exactly the sentence a reader needs. The repair is never to reword
    that prose; it is to match the marker as a whole LINE, which a mid-sentence mention
    can never be."""
    fake = tmp_path / "gate.md"
    fake.write_text(
        f"| F | row | the citable sentence lives behind `{rn._BAR_MARKER}` |\n"
        "\nsome other section\n\n"
        f"{rn._BAR_MARKER}\n> the real bar.\n",
        encoding="utf-8",
    )
    assert rn.verification_bar(fake) == "the real bar."


def test_TWO_real_markers_are_a_refusal_not_a_silent_pick(tmp_path):
    """The bar has one home. Two line-anchored markers mean somebody split it, and
    picking the first silently would publish whichever happened to sort earlier."""
    fake = tmp_path / "gate.md"
    fake.write_text(
        f"{rn._BAR_MARKER}\n> bar one.\n\n{rn._BAR_MARKER}\n> bar two.\n", encoding="utf-8"
    )
    with pytest.raises(rn.ReleaseNotesError, match="2 lines"):
        rn.verification_bar(fake)


def test_the_real_gate_carries_exactly_one_line_anchored_marker():
    """The property the fix rests on, asserted against the real file rather than a
    fixture — this is what was false when the defect was live."""
    lines = _GATE.read_text(encoding="utf-8").splitlines()
    exact = [line for line in lines if line.strip() == rn._BAR_MARKER]
    mentions = [line for line in lines if rn._BAR_MARKER in line]
    assert len(exact) == 1, "the bar has one home"
    assert len(mentions) > len(exact), (
        "the gate is expected to also MENTION the marker in prose — that mention is "
        "what broke the first reader, and this guard exists to keep it harmless"
    )
    assert rn.verification_bar() == (
        "Chromium in the sandbox + the maintainer's click-through = verified; "
        "Gecko best-effort."
    )


@pytest.mark.parametrize(
    ("iso", "want"),
    [
        ("2026-08-23T14:39:48+02:00", "2026-08-23"),  # the real v0.3.0 commit
        ("2026-08-24T00:39:48+12:00", "2026-08-23"),  # past midnight east -> previous
        ("2026-08-23T20:10:00-05:00", "2026-08-24"),  # evening west -> next
        ("2026-08-23T12:00:00Z", "2026-08-23"),
    ],
)
def test_utc_day_crosses_midnight_in_both_directions(iso, want):
    """Both directions, because a conversion that is right in one is a sign flip away
    from being wrong in the other."""
    assert rn.utc_day(iso) == want


def test_a_timestamp_with_no_offset_is_refused_not_assumed_local():
    """Assuming the local zone is the whole defect, wearing a default."""
    with pytest.raises(rn.ReleaseNotesError, match="no timezone"):
        rn.utc_day("2026-08-23T12:00:00")


def test_commit_day_is_the_SAME_under_two_process_timezones():
    """The discriminating test, and the one the old code fails.

    `git log --date=format-local` renders in the PROCESS's timezone, so the same tag
    gave `2026-08-23` under TZ=UTC0 and `2026-08-24` under TZ=Pacific/Auckland — a
    different cutoff day, a different set of ledger rows claimed by the same release,
    decided by whichever machine generated the notes. A CI runner is UTC and would
    never have shown it; the script's own docstring recommends a local dry run, which
    is exactly where it bites. Driven in SUBPROCESSES because the timezone is process
    state that `time.tzset()` cannot un-see for an already-imported module.
    """
    prog = (
        "import importlib.util, sys;"
        f"spec=importlib.util.spec_from_file_location('rn', {str(_SCRIPT)!r});"
        "m=importlib.util.module_from_spec(spec);sys.modules['rn']=m;"
        "spec.loader.exec_module(m);print(m.commit_day('v0.3.0'))"
    )
    out = {}
    for tz in ("UTC0", "Pacific/Auckland", "America/Los_Angeles"):
        proc = subprocess.run(
            [sys.executable, "-c", prog],
            cwd=_ROOT, capture_output=True, text=True, env={**os.environ, "TZ": tz},
        )
        assert proc.returncode == 0, proc.stderr
        out[tz] = proc.stdout.strip()
    assert len(set(out.values())) == 1, f"the cutoff day moved with the timezone: {out}"
    assert out["UTC0"] == "2026-08-23"


# --------------------------------------------------------------------------- #
# A ledger field is PROSE, and three shapes in it can restructure the document.
# --------------------------------------------------------------------------- #
def _one_bullet(**row) -> str:
    base = {"date": "2026-08-10", "area": "x/one", "item": "i", "status": "s", "refs": "r"}
    return rn._bullet({**base, **row}, {"item": 0, "status": 0})


def test_a_stray_backtick_cannot_open_a_span_that_swallows_the_next_row():
    """A code span closes at the next backtick run ANYWHERE later in the document, so
    one stray backtick pairs with the following bullet's opening one and everything
    between them — including that bullet's own `- ` list marker — becomes code. The
    real ledger's 997 rows all carry even counts, so this is latent by luck."""
    line = _one_bullet(item="a stray backtick right here ` never closed")
    assert "\\`" in line, "the backtick must be escaped, not emitted raw"
    unescaped = re.findall(r"(?<!\\)`+", line)
    assert len(unescaped) % 2 == 0, f"unbalanced code span in: {line}"


def test_a_newline_in_area_or_refs_cannot_inject_a_block():
    """`area` and `refs` are not clipped, so nothing was flattening them — a blank line
    plus `# ` at column 0 is a real ATX heading in the release body. Fields are handled
    by what they ARE, not by whether some other function touched them on the way past."""
    for field_name in ("area", "refs"):
        line = _one_bullet(**{field_name: "PR #1\n\n# Forged heading injected\n\nmore"})
        assert "\n" not in line, f"{field_name} escaped its bullet: {line!r}"
        assert line.startswith("- ")


def test_a_lone_CR_is_flattened_too():
    """A lone `\\r` is a valid CommonMark line ending, and a `\\r\\n`-then-`\\n` pair of
    replacements walks straight past it."""
    line = _one_bullet(item="before\rafter")
    assert "\r" not in line and "before after" in line


def test_angle_brackets_are_escaped_rather_than_passed_through_as_raw_html():
    """Inline `<style>`/`<script>` are raw-text elements: an unclosed one swallows
    everything up to a closing tag this document does not contain. This is not
    hypothetical — the row below is in the real ledger."""
    line = _one_bullet(item="The <style>/<script> strip was quadratic")
    assert "\\<style\\>" in line and "<style>" not in line.replace("\\<", "").replace("\\>", "<")
    assert not re.search(r"(?<!\\)<", line)


def test_an_area_containing_a_backtick_still_renders_as_a_code_span():
    """A code span ignores backslash escapes, so `area` needs the CommonMark fence
    construction instead. No real area has ever contained a backtick — this is so the
    day one does, the field renders rather than breaking the line."""
    line = _one_bullet(area="odd/`tick`")
    assert "`` odd/`tick` ``" in line


def test_the_cap_is_measured_on_the_SOURCE_text_not_the_escaped_form():
    """Escaping is invisible to a reader, so charging it against a length budget would
    clip two fields of the same real length differently by their punctuation alone."""
    plain, clipped_plain = rn._clip("a" * rn._ITEM_CAP, rn._ITEM_CAP)
    ticky, clipped_ticky = rn._clip("`" * rn._ITEM_CAP, rn._ITEM_CAP)
    assert clipped_plain is False and clipped_ticky is False
    assert len(plain) == len(ticky) == rn._ITEM_CAP


def test_the_real_ledger_renders_with_balanced_spans_and_no_raw_html():
    """The property over the REAL data, not a fixture: every code span in a real
    release body closes, and no field reaches the reader as raw HTML."""
    sel = rn.select(
        rn.read_rows(_REAL_CSV),
        rn.Selection(tag="v0.3.0", tag_day="2026-08-23", prev_tag="v0.2.0", prev_day="2026-07-18"),
    )
    body = rn.render(
        sel, group_by="segment", telemetry=rn.TelemetryCheck(mode="skip"),
        sites={"src/x.py": "a reason long enough to be a reason"}, covered=("socket",),
        bar="a bar", head_sha="deadbeef",
    )
    bullets = "\n".join(ln for ln in body.splitlines() if ln.startswith("- `"))
    assert len(re.findall(r"(?<!\\)`+", bullets)) % 2 == 0, "an unterminated code span"
    assert not re.search(r"(?<!\\)<", bullets), "raw HTML reached a bullet"
    assert "\r" not in body


# --------------------------------------------------------------------------- #
# The refusals that were raw crashes, and the history walk that was not first-parent.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "shape",
    [
        '_ALLOWED_SOCKET_IMPORTERS: dict[str, str] = dict([("a", "b")])',
        '_ALLOWED_SOCKET_IMPORTERS: dict[str, str] = {k: v for k, v in []}',
        '_ALLOWED_SOCKET_IMPORTERS: dict[str, str] = {"a": f"because {1}"}',
    ],
)
def test_an_unevaluable_allowlist_shape_REFUSES_in_the_documented_way(tmp_path, shape):
    """The docstring promises a refusal. Letting `ast.literal_eval`'s own ValueError
    escape gives a traceback and an exit code this tool never chose — in a CI log that
    reads as a crash rather than as the actionable "go re-derive the reader" it is."""
    fake = tmp_path / "t.py"
    fake.write_text(f'_SOCKET_CAPABLE_MODULES = ("socket",)\n{shape}\n', encoding="utf-8")
    with pytest.raises(rn.ReleaseNotesError, match="not a literal this reader can evaluate"):
        rn.outbound_call_sites(fake)


def test_previous_tag_walks_FIRST_PARENT_only(tmp_path, monkeypatch):
    """Without `--first-parent`, `git describe` walks into merged side branches and
    names a tag that only ever existed on one of them as "the previous release".
    Constructed rather than asserted: this repo's two real tags are first-parent
    ancestors of each other, so no fixture drawn from it can tell the two forms apart."""
    repo = tmp_path / "hist"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@e.com")
    git("config", "user.name", "T")
    (repo / "a").write_text("a", encoding="utf-8")
    git("add", "a")
    git("commit", "-qm", "A")
    git("checkout", "-q", "-b", "side")
    (repo / "s").write_text("s", encoding="utf-8")
    git("add", "s")
    git("commit", "-qm", "S")
    git("tag", "v-side-0.5.0")
    git("checkout", "-q", "main")
    (repo / "b").write_text("b", encoding="utf-8")
    git("add", "b")
    git("commit", "-qm", "B")
    git("merge", "-q", "--no-ff", "side", "-m", "M")
    (repo / "c").write_text("c", encoding="utf-8")
    git("add", "c")
    git("commit", "-qm", "C")
    git("tag", "v-main-1.0.0")

    # THE PRODUCTION FUNCTION, not a hand-rolled `git describe` beside it. A first
    # draft of this test asserted the two git invocations directly and SURVIVED the
    # mutation that drops `--first-parent` from the shipped code — because it never
    # called it. A test of the mechanism is not a test of the wiring.
    monkeypatch.setattr(rn, "_ROOT", repo)

    plain = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "--match", "v*", "v-main-1.0.0^"],
        cwd=repo, capture_output=True, text=True,
    ).stdout.strip()
    assert plain == "v-side-0.5.0", "the fixture must genuinely reproduce the defect"

    assert rn.previous_tag("v-main-1.0.0") is None, (
        "a tag that exists only on a merged side branch is not a previous RELEASE"
    )


def test_previous_tag_still_finds_the_real_previous_release():
    """The twin. A walk that finds nothing is not a fix — it is the same defect
    pointing the other way, and it would make every release claim the whole ledger."""
    assert rn.previous_tag("v0.3.0") == "v0.2.0"


# --------------------------------------------------------------------------- #
# The summary scraper: the verdict and the reason are different facts.
# --------------------------------------------------------------------------- #
class _Proc:
    def __init__(self, stdout, stderr, returncode):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def test_a_PASSING_runs_stderr_warning_never_becomes_the_result(monkeypatch):
    """The first cut concatenated stdout + stderr and scanned backward, and stderr text
    always lands after stdout text in that concatenation regardless of when it was
    written — so an interpreter-shutdown ResourceWarning became "the result" of a
    legally-binding no-telemetry re-check."""
    monkeypatch.setattr(
        rn.subprocess, "run",
        lambda *a, **k: _Proc(
            "tests/x.py .   [100%]\n\n1 passed in 0.04s\n",
            "ResourceWarning: unclosed socket -- ignoring an error during shutdown\n",
            0,
        ),
    )
    assert rn.run_telemetry_check("run", "x").summary == "1 passed in 0.04s"


def test_a_FAILING_run_keeps_BOTH_the_verdict_and_the_reason():
    """Real pytest against a node that does not exist: stdout says `no tests ran`
    (true and useless on its own) while stderr carries `ERROR: file or directory not
    found`. Reporting only the first hides why; only the second lets a warning stand in
    for a result. Also pins the case-insensitivity — pytest writes ERROR in capitals."""
    got = rn.run_telemetry_check("run", "/tmp/oo-does-not-exist.py")
    assert got.returncode != 0
    assert "no tests ran" in (got.summary or "")
    assert "file or directory not found" in (got.summary or "")


# --------------------------------------------------------------------------- #
# 12. the reason when pytest never reached a verdict.
#
# The generator's refusal was always correct here — non-zero exit, "FAILED", no
# false green. What was wrong was the DIAGNOSIS: `_last_match` only recognises
# pytest's own vocabulary (passed/failed/error/no tests ran), and the most common
# real reason carries none of it, so the reason was discarded for a placeholder
# that told the operator nothing. Found by running the generator against its own
# merge commit with an interpreter that had no pytest.
#
# This is the family invariant #14e's corollary names — a refusal reported as
# something other than what it is — so the guards below are about the TEXT the
# operator reads, not about whether the refusal happened.
# --------------------------------------------------------------------------- #
def _no_verdict(stderr: str, *, stdout: str = "", rc: int = 1):
    """A run where pytest never printed a verdict. Driven through the shipped
    function, never through the nested helper, so these test the WIRING — the
    recorded lesson that a test proving the mechanism is not a test of the wiring."""
    import unittest.mock as _m

    with _m.patch.object(rn.subprocess, "run", lambda *a, **k: _Proc(stdout, stderr, rc)):
        return rn.run_telemetry_check("run", "x")


def test_a_stderr_reason_OUTSIDE_pytests_vocabulary_still_reaches_the_notes():
    """THE DEFECT, verbatim: a bare interpreter says `No module named pytest`, which
    carries none of passed/failed/error/no tests ran. The old code fell through to the
    placeholder and published it OVER the one line that said what was wrong."""
    got = _no_verdict("/usr/local/bin/python3: No module named pytest\n")
    assert "No module named pytest" in (got.summary or "")
    assert "no summary line" not in (got.summary or "")


def test_the_stream_is_named_so_a_reader_knows_no_verdict_was_reached():
    """`stderr:` is the load-bearing prefix, not decoration. Without it the line reads
    as pytest's own verdict, when in fact pytest never produced one — the file's own
    comment claimed the stream was 'NAMED either way' while this branch named nothing."""
    assert (_no_verdict("boom\n").summary or "").startswith("stderr: ")


def test_pytests_own_vocabulary_still_WINS_over_a_merely_later_line():
    """Widening the fallback must not demote the better answer. When stderr carries a
    real pytest line AND trailing noise after it, the pytest line is the reason — the
    last non-empty line is the fallback for when there is no such line, not a
    replacement for it."""
    got = _no_verdict("ERROR: file or directory not found: x\nlibfoo: some trailing noise\n")
    assert "file or directory not found" in (got.summary or "")
    assert "trailing noise" not in (got.summary or "")


def test_nothing_on_either_stream_says_EXACTLY_that():
    """The placeholder still exists and is still honest — it just no longer fires over
    a stderr line that had something to say. Its wording names both streams, because
    'no summary line' described only one of them."""
    got = _no_verdict("")
    assert got.summary == "(pytest produced no output on either stream)"


def test_a_runaway_stderr_line_is_clipped_and_the_clip_is_DISCLOSED():
    """Subprocess text has no length budget and this lands in a published release body.
    Clipped at _REASON_CAP through the same `_clip` every other field uses, so the
    clip carries its own mark rather than silently truncating a diagnosis."""
    got = _no_verdict("x" * 5000 + "\n")
    body = got.summary or ""
    assert len(body) < 400, f"unbounded subprocess text reached the notes: {len(body)}"
    assert body.endswith("…"), "a clip that does not mark itself is a silent truncation"


def test_a_PASSING_run_still_cannot_pick_up_a_stderr_line():
    """The widened fallback is gated on stdout having NO verdict, so it can never
    reach a run that passed. Re-pinned here because this change is exactly the kind
    that would reopen the concatenation defect the section above exists for."""
    got = _no_verdict("noise on stderr\n", stdout="1 passed in 0.04s\n", rc=0)
    assert got.summary == "1 passed in 0.04s"


def _ratchet_body(summary: str, command=("python", "-m", "pytest", "-q", "x")) -> str:
    return rn.render(
        _selection(),
        group_by="segment",
        telemetry=rn.TelemetryCheck(
            mode="run", command=list(command), returncode=1, summary=summary
        ),
        sites={"src/x.py": "a reason long enough to be a reason"},
        covered=("socket",),
        bar="a bar",
        head_sha="deadbeef",
    )


def _code_spans(text: str) -> list[str]:
    """Every CommonMark code span in ``text``, by the real rule: a backtick run of
    length N opens a span closed by the next run of EXACTLY length N, and an opener
    with no match is literal text. Content has one leading+trailing space stripped
    when both are present, as CommonMark specifies.

    Hand-rolled ON PURPOSE. `markdown-it-py` is importable here, but only because
    `rich` happens to depend on it — it is declared nowhere in `pyproject.toml`, and a
    guard that silently depends on somebody else's transitive dependency fails for a
    reason that has nothing to do with the thing it guards. This scanner was
    cross-checked against `markdown-it-py`'s CommonMark parser on nine shapes,
    including the two the renderer actually produces, and agreed on all nine.
    """
    runs = [(m.start(), m.end(), m.end() - m.start()) for m in re.finditer(r"`+", text)]
    spans: list[str] = []
    i = 0
    while i < len(runs):
        _, end, n = runs[i]
        j = next((k for k in range(i + 1, len(runs)) if runs[k][2] == n), None)
        if j is None:
            i += 1
            continue
        content = text[end : runs[j][0]]
        if len(content) > 2 and content[0] == " " and content[-1] == " " and content.strip():
            content = content[1:-1]
        spans.append(content)
        i = j + 1
    return spans


#: The bullet rendered immediately after the ratchet line. If a stray backtick opens a
#: span that never closes where it should, THIS is the text that gets swallowed — so
#: it is the honest canary, rather than counting backticks (a count is not the rule:
#: ``a ` b`` is a valid span with an ODD number of them, which is how the first cut of
#: these guards passed one case by coincidence and failed another that was correct).
_CANARY = "The ratchet covers"


def test_a_BACKTICK_in_the_ratchet_summary_cannot_break_the_code_span():
    """Defect 3 of this file's own adversarial round, in the one field that round never
    looked at. It was latent while `summary` could only be a pytest summary line; the
    stderr fallback makes it arbitrary subprocess text, so the raw-backtick render
    became a live path and now goes through `_code_span` like every other field.

    Driven against the real shape: an interpreter reporting a quoted module name."""
    text = "stderr: ModuleNotFoundError: No module named `pytest`"
    body = _ratchet_body(text)
    assert text in "".join(_code_spans(body)), "the text must survive, not be dropped"
    assert not any(_CANARY in s for s in _code_spans(body)), (
        "a stray backtick swallowed the following bullet into a code span"
    )


def test_a_BACKTICK_in_the_COMMAND_cannot_break_it_either():
    """`shown` is built from a caller-supplied --telemetry-node path and was rendered
    with bare backticks too. Neither interpolation is ours to trust."""
    body = _ratchet_body("1 failed", command=("python", "-m", "pytest", "-q", "tests/w`ird.py"))
    assert any("w`ird.py" in s for s in _code_spans(body))
    assert not any(_CANARY in s for s in _code_spans(body))


def test_the_TERMINAL_refusal_names_the_reason_not_just_FAILED(monkeypatch, tmp_path, capsys):
    """The same defect one layer out. The notes file carries the reason, but the person
    running this is looking at a terminal, and `main` printed only "the ratchet FAILED"
    — so the operator's next move was to go read the generator rather than the one line
    saying pytest was not installed. The reason is INDEXED out of the accounting, not
    `.get()`-ed: the `_accounting` helper's own docstring rules that out, because a
    `.get()` in production is how a double that has fallen behind stops reddening."""
    acc = _accounting(returncode=1)
    acc["telemetry_summary"] = "stderr: /usr/bin/python3: No module named pytest"
    monkeypatch.setattr(rn, "build", lambda args: ("body\n", acc))
    assert rn.main(["--tag", "v9.9.9", "-o", str(tmp_path / "n.md")]) == 1
    err = capsys.readouterr().err
    assert "No module named pytest" in err, "the terminal refusal still says nothing useful"
    assert "ratchet FAILED" in err, "and it must still say the ratchet failed"
