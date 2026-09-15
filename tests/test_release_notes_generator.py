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

    monkeypatch.setattr(
        rn,
        "build",
        lambda args: ("body\n", {"telemetry_returncode": 1}),
    )
    out = tmp_path / "n.md"
    assert rn.main(["--tag", "v9.9.9", "-o", str(out)]) == 1


def test_a_passing_ratchet_exits_zero(monkeypatch, tmp_path):
    """The twin: an exit code that is always non-zero blocks every release."""
    monkeypatch.setattr(rn, "build", lambda args: ("body\n", {"telemetry_returncode": 0}))
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
    sites = {"src/a.py": "reason A, long enough to say something", "src/b.py": "reason B, also long enough"}
    body = rn.render(
        _selection(),
        group_by="segment",
        telemetry=rn.TelemetryCheck(mode="skip"),
        sites=sites,
        covered=("socket", "requests"),
        bar="a bar",
        head_sha="deadbeef",
    )
    for path, reason in sites.items():
        assert f"`{path}` — {reason}" in body
    assert "**2**" in body and "2 socket-capable libraries" in body


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
