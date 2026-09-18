"""The shipped-verdict editor: adopt / export / revert, and the admission route it closes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1106 = a (2026-09-15) asks for the editor in Settings. Building it surfaced something
the ruling does not mention and S1 did not reach: ``apply_overlay`` IS AN ADMISSION
ROUTE. The catalogue ships its rows ``enabled: true`` awaiting a verdict, so adopting a
shipped ``qualified`` verdict onto one takes it from unreachable to actively scraped --
live-reproduced as ``select_sources`` going from ``[]`` to ``[the domain]`` while the
admission audit stayed empty and the undo had nothing to act on. That is the same defect
the audit's unit was rewritten to close in ``evaluate_and_stamp``, alive in a second path,
and a "revert" built over it would have had nothing to revert.

So the tests below are mostly about the SECOND path and the REFUSALS:

  * adoption records an admission, with the verdict ``inherited`` -- the project's own
    word for a stamp this instance did not measure, so the audit says which KIND of
    evidence let a source in;
  * a revert puts back only what it can PROVE this install's adoption stamped, and names
    the two populations it will not touch rather than skipping them silently;
  * a revert HOLDS -- adoption looks for rows reading ``unqualified``, which is exactly
    the state a revert restores, so without the preference the next boot would undo it.

The fixture separates every population by construction: a row that is admitted, a row
that is stamped but admits nothing, a row judged locally, and a row the catalogue stamped
by ruling. A fixture where those coincide would let each assertion pass for the wrong
reason.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.catalog.qualification import (  # noqa: E402
    CURATED_CRITERIA_VERSION,
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
    VERDICT_CURATED,
    VERDICT_INHERITED,
    is_collectable,
)
from src.catalog.qualification_overlay import (  # noqa: E402
    REVERT_DECLINE_CURATED,
    REVERT_DECLINE_JUDGED,
    apply_overlay,
    overlay_status,
    revert_overlay,
)
from src.database.models import (  # noqa: E402
    Base,
    Source,
    SourceAdmissionEvent,
    SourceQualificationAttempt,
)

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)

_OVERLAY_YML = """\
generated_at: 2026-05-01
criteria_version: t
verdicts:
  - {domain: cat.example, status: qualified, qualified_at: 2026-05-01, criteria_version: t}
  - {domain: off.example, status: qualified, qualified_at: 2026-05-01, criteria_version: t}
  - {domain: local.example, status: qualified, qualified_at: 2026-05-01, criteria_version: t}
  - {domain: cur.example, status: disqualified, qualified_at: 2026-05-01, criteria_version: t}
"""


@pytest.fixture
def overlay_file(tmp_path: Path) -> Path:
    p = tmp_path / "source_qualification.yml"
    p.write_text(_OVERLAY_YML, encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """The adoption preference is a REAL persisted setting, and these tests flip it.

    Redirected to a per-test file rather than mocked away: the preference and the restore
    are one operation (a revert whose second half depends on a separate call is a revert
    that can half-happen), so a test that stubbed the write would be testing a different
    function from the one that ships.
    """
    import src.config.app_settings as app_settings

    monkeypatch.setattr(
        app_settings, "_settings_path", lambda: tmp_path / "app_settings.json"
    )
    monkeypatch.setattr(app_settings, "_kv_enabled", lambda: False, raising=False)
    return app_settings


@pytest.fixture
def db(tmp_path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'ov.db'}", future=True)
    Base.metadata.create_all(engine)
    s = Session(engine, future=True)

    def add(domain, enabled, status, **kw):
        row = Source(name=domain, domain=domain, tags="news,via:curated",
                     enabled=enabled, status=status, **kw)
        s.add(row)
        s.commit()
        return row

    # THE CATALOGUE SHAPE: ships enabled, awaiting a verdict. Adoption ADMITS it -- the
    # path that was unrecorded.
    add("cat.example", True, STATUS_UNQUALIFIED)
    # Disabled and awaiting a verdict: adoption stamps it and admits nothing. The
    # difference between changing what the app KNOWS and what it DOES.
    add("off.example", False, STATUS_UNQUALIFIED)
    # Judged HERE. Local wins, in both directions -- adoption declines it.
    loc = add("local.example", True, STATUS_QUALIFIED)
    s.add(SourceQualificationAttempt(
        source_id=loc.id, attempted_at=NOW - timedelta(days=30),
        verdict=STATUS_QUALIFIED, criteria_version="t"))
    # Stamped qualified BY RULING (2026-09-10), never measured. A shipped, measured
    # verdict outranks it -- and here that verdict is `disqualified`, so adopting takes
    # this row OUT of collection.
    cur = add("cur.example", True, STATUS_QUALIFIED,
              qualification_criteria_version=CURATED_CRITERIA_VERSION)
    s.add(SourceQualificationAttempt(
        source_id=cur.id, attempted_at=NOW - timedelta(days=60),
        verdict=VERDICT_CURATED, criteria_version=CURATED_CRITERIA_VERSION))
    s.commit()
    return s


def _by_domain(db: Session, domain: str) -> Source:
    return db.query(Source).filter(Source.domain == domain).one()


def _collecting(db: Session) -> set[str]:
    from src.scheduler.runner import select_sources
    from src.scheduler.settings import SchedulerSettings

    return {s.domain for s in select_sources(db, SchedulerSettings())}


def test_the_fixture_separates_the_four_shapes(db: Session) -> None:
    """Anti-vacuity. Every assertion below rests on these four rows answering differently;
    if a future edit makes any two alike, the tests keep passing for the wrong reason."""
    shapes = {
        s.domain: (s.enabled, s.status, s.qualification_criteria_version)
        for s in db.query(Source).all()
    }
    assert len(set(shapes.values())) == 4, f"the fixture no longer separates them: {shapes}"
    assert _collecting(db) == {"local.example", "cur.example"}


# --------------------------------------------------------------------------- #
# The second admission route
# --------------------------------------------------------------------------- #
def test_adopting_a_shipped_verdict_onto_a_catalogue_row_records_an_admission(
    db: Session, overlay_file: Path
) -> None:
    """THE DEFECT THIS CLOSES, driven end to end through the collection gate rather than
    through the tally: before, this transition moved `select_sources` and left the audit
    empty, so the operator had no record and no undo for a source that started being
    scraped."""
    cat = _by_domain(db, "cat.example")
    assert not is_collectable(cat.enabled, cat.status)
    assert "cat.example" not in _collecting(db)

    tally = apply_overlay(db, now=NOW, path=overlay_file)

    assert "cat.example" in _collecting(db), "adoption did not admit it"
    assert tally["admitted"] == 1
    events = db.query(SourceAdmissionEvent).all()
    assert [e.source_id for e in events] == [cat.id], (
        "adoption admitted a source without writing the audit row the undo needs"
    )


def test_the_admission_row_says_the_verdict_was_inherited_not_measured(
    db: Session, overlay_file: Path
) -> None:
    """A stamp this instance did not earn is recorded with the project's existing word for
    that. Without it the audit would show a local judgement and a shipped file as the same
    kind of evidence, which is the anti-false-triangulation rule pointed at our own
    verdicts."""
    apply_overlay(db, now=NOW, path=overlay_file)
    ev = db.query(SourceAdmissionEvent).one()
    assert ev.verdict == VERDICT_INHERITED
    assert ev.verdict != STATUS_QUALIFIED
    # And the prior state is the one an undo restores.
    assert ev.prior_enabled is True
    assert ev.prior_status == STATUS_UNQUALIFIED


def test_adopting_onto_a_disabled_row_stamps_it_and_admits_nothing(
    db: Session, overlay_file: Path
) -> None:
    """NEGATIVE SPACE. Over-recording is its own defect: an audit that listed every
    adoption would invite an operator to 'undo' something that never reached collection,
    and would bury the rows that did."""
    apply_overlay(db, now=NOW, path=overlay_file)
    off = _by_domain(db, "off.example")
    assert off.status == STATUS_QUALIFIED, "the verdict was not adopted"
    assert off.enabled is False, "adoption must never flip `enabled` -- only judging does"
    assert "off.example" not in _collecting(db)
    assert db.query(SourceAdmissionEvent).filter_by(source_id=off.id).count() == 0


def test_the_ordinary_undo_reverses_an_adoption_driven_admission(
    db: Session, overlay_file: Path
) -> None:
    """One undo, whatever admitted the source. The audit is a list of admissions, not a
    list of qualification passes, so a row that arrived by a different road must come out
    by the same door."""
    from src.catalog.qualification import undo_admission

    apply_overlay(db, now=NOW, path=overlay_file)
    ev = db.query(SourceAdmissionEvent).one()
    undo_admission(db, ev.id, now=NOW.replace(tzinfo=None))

    cat = _by_domain(db, "cat.example")
    assert cat.status == STATUS_UNQUALIFIED
    assert cat.enabled is True
    assert "cat.example" not in _collecting(db)


def test_adopting_twice_admits_nothing_the_second_time(
    db: Session, overlay_file: Path
) -> None:
    """Idempotence is what makes adoption safe on every boot. A second audit row for the
    same unchanged state would be a false record of a decision nobody made."""
    apply_overlay(db, now=NOW, path=overlay_file)
    again = apply_overlay(db, now=NOW + timedelta(minutes=5), path=overlay_file)
    assert again["adopted"] == 0
    assert again.get("admitted", 0) == 0
    assert db.query(SourceAdmissionEvent).count() == 1


# --------------------------------------------------------------------------- #
# The preview
# --------------------------------------------------------------------------- #
def test_the_preview_counts_both_directions_before_anything_is_written(
    db: Session, overlay_file: Path
) -> None:
    """Adopting is a write, so what it would do is on the screen first -- INCLUDING the
    direction a reader would not think to ask about, where a shipped `disqualified`
    verdict takes a source out of collection. Measured on a fixture where the three
    figures differ, so none of them can be the others by accident."""
    st = overlay_status(db, path=overlay_file)
    assert st["in_overlay"] == 4
    assert st["shipped_qualified"] == 3
    assert st["shipped_disqualified"] == 1
    assert st["would_adopt"] == 3, "local.example must be declined -- local wins"
    assert st["would_admit"] == 1, "only the enabled, unjudged catalogue row"
    assert st["would_withdraw"] == 1, "the curated row loses its stamp to a measured one"
    assert st["adopted_here"] == 0 and st["revertible"] == 0
    assert st["caveat"].strip() and st["method"].strip()


def test_the_preview_matches_what_adopting_actually_does(
    db: Session, overlay_file: Path
) -> None:
    """The preview and the action are two code paths over the same rule, which is how a
    surface and a gate come to disagree. Driven against each other rather than against
    written-down numbers."""
    before = overlay_status(db, path=overlay_file)
    was_collecting = _collecting(db)
    tally = apply_overlay(db, now=NOW, path=overlay_file)
    now_collecting = _collecting(db)

    assert tally["adopted"] == before["would_adopt"]
    assert tally["admitted"] == before["would_admit"]
    assert len(now_collecting - was_collecting) == before["would_admit"]
    assert len(was_collecting - now_collecting) == before["would_withdraw"]


def test_an_install_with_no_overlay_says_so_rather_than_showing_zeros(
    db: Session, tmp_path: Path
) -> None:
    """An absent file and an empty one are different facts, and an install that ships no
    overlay behaves exactly as it did before the file existed."""
    st = overlay_status(db, path=tmp_path / "absent.yml")
    assert st["file"]["exists"] is False
    assert st["in_overlay"] == 0
    assert st["would_adopt"] == 0


# --------------------------------------------------------------------------- #
# Revert
# --------------------------------------------------------------------------- #
def test_revert_puts_back_what_adoption_stamped_and_leaves_nothing_collecting(
    db: Session, overlay_file: Path
) -> None:
    apply_overlay(db, now=NOW, path=overlay_file)
    assert "cat.example" in _collecting(db)

    out = revert_overlay(db, now=NOW + timedelta(hours=1), path=overlay_file)

    assert out["reverted"] == 2, "cat + off; the curated row is refused, the local one untouched"
    assert out["still_collecting"] == 0
    assert _by_domain(db, "cat.example").status == STATUS_UNQUALIFIED
    assert _by_domain(db, "cat.example").qualified_at is None
    assert _by_domain(db, "off.example").status == STATUS_UNQUALIFIED
    assert "cat.example" not in _collecting(db)


def test_revert_closes_the_admission_it_is_undoing(
    db: Session, overlay_file: Path
) -> None:
    """An audit that went on listing a live admission for a source that is no longer
    collectable would be reporting something that has stopped being true."""
    apply_overlay(db, now=NOW, path=overlay_file)
    out = revert_overlay(db, now=NOW + timedelta(hours=1), path=overlay_file)
    assert out["admissions_undone"] == 1
    assert db.query(SourceAdmissionEvent).filter(
        SourceAdmissionEvent.undone_at.is_(None)
    ).count() == 0
    assert db.query(SourceAdmissionEvent).count() == 1, "the record is append-only"


def test_revert_refuses_a_row_this_install_judged_since_and_counts_it(
    db: Session, overlay_file: Path
) -> None:
    """The live verdict is this install's own, whatever it happens to agree with, and
    reverting it would throw away a measurement rather than an adoption. REFUSED and
    counted -- 'nothing to revert' and 'one row I will not touch' are different states."""
    apply_overlay(db, now=NOW, path=overlay_file)
    cat = _by_domain(db, "cat.example")
    # A real local judgement AFTER the adoption, agreeing with it.
    db.add(SourceQualificationAttempt(
        source_id=cat.id, attempted_at=NOW + timedelta(minutes=10),
        verdict=STATUS_QUALIFIED, criteria_version="t"))
    db.commit()

    st = overlay_status(db, path=overlay_file)
    assert st["declined"][REVERT_DECLINE_JUDGED] == 1

    out = revert_overlay(db, now=NOW + timedelta(hours=1), path=overlay_file)
    assert out["declined"][REVERT_DECLINE_JUDGED] == 1
    assert _by_domain(db, "cat.example").status == STATUS_QUALIFIED
    assert "cat.example" in _collecting(db)


def test_revert_refuses_a_row_the_overlay_stamped_over_a_curated_stamp(
    db: Session, overlay_file: Path
) -> None:
    """`unqualified` is not what that row looked like before, so reverting it would invent
    a state rather than restore one. The refusal is named and counted; guessing is what
    this whole area exists not to do."""
    tally = apply_overlay(db, now=NOW, path=overlay_file)
    assert tally["replaced_curated"] == 1

    out = revert_overlay(db, now=NOW + timedelta(hours=1), path=overlay_file)
    assert out["declined"][REVERT_DECLINE_CURATED] == 1
    cur = _by_domain(db, "cur.example")
    assert cur.status == STATUS_DISQUALIFIED, "left exactly as the overlay made it"


def test_a_revert_holds_across_the_next_startup_adoption(
    db: Session, overlay_file: Path, isolated_settings
) -> None:
    """THE HALF THAT MAKES IT A REVERT. Adoption looks for rows reading `unqualified`,
    which is precisely the state a revert restores -- so without the preference the next
    boot re-adopts and the operator's decision lasts until they close the app."""
    apply_overlay(db, now=NOW, path=overlay_file)
    out = revert_overlay(db, now=NOW + timedelta(hours=1), path=overlay_file)
    assert out["preference_held"] is True
    assert isolated_settings.load_settings().adopt_shipped_verdicts is False

    again = apply_overlay(db, now=NOW + timedelta(hours=2), path=overlay_file)
    assert again["adopted"] == 0
    assert again["declined_by_preference"] is True
    assert _by_domain(db, "cat.example").status == STATUS_UNQUALIFIED


def test_a_declined_boot_adoption_says_so_rather_than_reporting_a_clean_zero(
    db: Session, overlay_file: Path, isolated_settings
) -> None:
    """NEGATIVE SPACE: 'adopted 0' because everything was already in force and 'adopted 0'
    because the operator turned it off are different facts, and a boot step that declined
    to run is one the editor shows."""
    isolated_settings.save_settings({"adopt_shipped_verdicts": False})
    out = apply_overlay(db, now=NOW, path=overlay_file)
    assert out["declined_by_preference"] is True
    assert out["available"] is True, "the file is there; it is the preference that declined"
    assert overlay_status(db, path=overlay_file)["adopting_at_startup"] is False


def test_the_preference_read_fails_open_so_a_broken_settings_file_cannot_block_boot(
    monkeypatch, db: Session, overlay_file: Path
) -> None:
    """It is read on the BOOT path. The safe direction for an unreadable preference is the
    behaviour that shipped before it existed -- so a corrupt settings file costs an
    operator their revert, never their app."""
    import src.catalog.qualification_overlay as ov

    def boom():
        raise OSError("settings unreadable")

    monkeypatch.setattr("src.config.app_settings.load_settings", boom)
    assert ov.adoption_enabled() is True
    assert apply_overlay(db, now=NOW, path=overlay_file)["adopted"] == 3


def test_adopt_then_revert_then_adopt_returns_the_corpus_to_the_adopted_state(
    db: Session, overlay_file: Path, isolated_settings
) -> None:
    """The round trip, because a revert that cannot be re-adopted is a one-way door
    dressed as a toggle."""
    first = apply_overlay(db, now=NOW, path=overlay_file)
    collecting_after_adopt = _collecting(db)
    revert_overlay(db, now=NOW + timedelta(hours=1), path=overlay_file)
    isolated_settings.save_settings({"adopt_shipped_verdicts": True})
    second = apply_overlay(db, now=NOW + timedelta(hours=2), path=overlay_file)

    assert second["adopted"] == first["adopted"] - first["replaced_curated"], (
        "the curated row was refused by the revert, so it is already adopted"
    )
    assert _collecting(db) == collecting_after_adopt


# --------------------------------------------------------------------------- #
# The ROUTES, not the functions
# --------------------------------------------------------------------------- #
def test_the_three_endpoints_are_reachable_and_not_shadowed_by_the_by_id_route() -> None:
    """A handler exercised as a function is not a tested ROUTE, and this is what that
    costs.

    Every test above calls `overlay_status(db)` / `revert_overlay(db)` directly. All of
    them passed while `GET /api/sources/overlay` answered **422** -- `Input should be a
    valid integer, unable to parse string as an integer` -- because FastAPI matches in
    REGISTRATION order and `GET /api/sources/{source_id}`, defined earlier on the same
    router, swallows any single segment. The panel rendered that sentence where its counts
    belong, and only the Chromium walk saw it.

    So this drives the real app. It asserts a NON-422 rather than a 200, because the
    failure being guarded is the shadowing, and pinning a success body here would make the
    test fail for reasons that have nothing to do with route order.
    """
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        r = c.get("/api/sources/overlay")
        assert r.status_code != 422, (
            "GET /api/sources/overlay is shadowed by /{source_id} again -- move the "
            f"overlay routes back above it. Body: {r.text[:300]}"
        )
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("file", "in_overlay", "would_adopt", "would_admit", "would_withdraw",
                    "adopting_at_startup", "revertible", "declined", "caveat"):
            assert key in body, f"the editor's payload lost {key!r}"

        # The two POSTs travel the same road and would be shadowed the same way by a
        # future `POST /{source_id}/...`, so neither is assumed from the GET.
        for path in ("/api/sources/overlay/adopt", "/api/sources/overlay/revert"):
            assert c.post(path).status_code != 422, f"{path} is shadowed"


def test_the_overlay_routes_are_registered_before_the_by_id_route() -> None:
    """The structural half, so a reordering is named rather than merely observed as a 422.

    Read off the router's OWN definitions (immutable), never the shared mutable
    `app.routes` singleton -- the recorded flaky-guard lesson.
    """
    from src.api.source_management import router

    paths = [r.path for r in router.routes]
    first_overlay = min(i for i, p in enumerate(paths) if "/overlay" in p)
    first_by_id = min(i for i, p in enumerate(paths) if "{source_id}" in p)
    assert first_overlay < first_by_id, (
        f"an /overlay route ({paths[first_overlay]}) is registered after "
        f"{paths[first_by_id]}; FastAPI matches in order, so it will answer 422"
    )
