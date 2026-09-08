"""
P1 audit finding (2026-09-08): the OpenTimestamps chain-of-custody anchoring
feature is real, IP-revealing network egress to three public third-party
calendar servers, on three reachable paths that previously fired with no
per-action consent -- a violation of CLAUDE.md's informed-consent
non-negotiable and UI invariant #14/#14e.

This file pins the fix's three gates:

* ``src.custody.timestamp.ots_stamp`` refuses, honestly and by name, when the
  network kill switch is engaged, BEFORE attempting any calendar submission
  (the #14e corollary: "a refusal BY THE KILL SWITCH must be named as such").
* ``src.custody.settings.save_settings`` refuses to turn ``anchoring_mode`` ON
  to ``"opentimestamps"`` (the trigger for Path 1's silent, recurring,
  per-ingest egress) without an explicit ``ots_consent`` flag, but does not
  re-demand it on every resave once the setting is already on.
* The frontend's two remaining paths -- the manual "Anchor root" button
  (``anchorRoot``) and the settings save flow (``saveCustody``) -- route
  through the app's one consent mechanism (``ensureOnline``) before making the
  real request, mirroring every other network-triggering action in this app
  (invariant #14).

Heavier, full-``TestClient`` coverage of the ``POST /api/custody/anchor``
consent gate lives alongside the rest of the custody API tests in
``test_custody_api.py`` and the settings-PUT gate in ``test_custody_settings.py``
(both need the full FastAPI app import chain); this file covers what is
reachable with only the custody/ingest modules themselves.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from src.custody import settings as cset
from src.custody import timestamp as ts
from src.custody.settings import CustodySettingsError
from src.custody.timestamp import TimestampUnavailable, sha256
from src.ingest import activate_kill_switch, clear_kill_switch, kill_switch_active
from tests.js_source_helper import app_js, assert_present, function_body

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"

DIGEST = sha256(b"custody consent gate test")


# --------------------------------------------------------------------------- #
# ots_stamp() -- the shared egress point for BOTH Path 1 (auto per-ingest) and
# Path 2 (the /api/custody/anchor endpoint)
# --------------------------------------------------------------------------- #


class _CalendarThatMustNeverBeReached:
    """Fails the test if OTS ever tries to reach the network -- the kill-switch
    refusal must happen BEFORE any RemoteCalendar is even constructed."""

    def __init__(self, url):  # pragma: no cover - only reached on regression
        raise AssertionError(
            "RemoteCalendar was constructed while the kill switch was engaged -- "
            "the honest early refusal in ots_stamp() did not run first"
        )


def test_ots_stamp_refuses_named_when_kill_switch_engaged(monkeypatch):
    monkeypatch.setattr(ts, "OTS_AVAILABLE", True)
    # raising=False: this sandbox may not have the real 'opentimestamps' package
    # installed, in which case RemoteCalendar was never bound as a module attribute
    # (the try/except import guard at the top of timestamp.py) -- the substitute
    # must still take, since OTS_AVAILABLE is forced True above regardless.
    monkeypatch.setattr(ts, "RemoteCalendar", _CalendarThatMustNeverBeReached, raising=False)
    assert not kill_switch_active(), "test isolation: the kill switch must start OFF"
    activate_kill_switch()
    try:
        with pytest.raises(TimestampUnavailable) as exc:
            ts.ots_stamp(DIGEST)
    finally:
        clear_kill_switch()
    # #14e: named as the kill switch, not a bare connection-refused/socket error.
    msg = str(exc.value).lower()
    assert "kill switch" in msg or "airplane" in msg


def test_ots_stamp_kill_switch_check_runs_before_calendar_construction(monkeypatch):
    """Same as above, phrased as a positive: with the switch OFF, the (fake, dead)
    calendar IS reached -- proving the refusal above is conditional on the switch,
    not a blanket short-circuit that would silently defeat every other test.

    ``Timestamp`` is also stubbed (``raising=False``): this sandbox may not have
    the real 'opentimestamps' package, so the name is unbound by the module's own
    try/except import guard, same as ``RemoteCalendar`` above -- a bare object is
    enough, since ``ots_stamp`` never touches it before the (immediately-raising)
    calendar submission.
    """
    monkeypatch.setattr(ts, "OTS_AVAILABLE", True)
    monkeypatch.setattr(ts, "Timestamp", lambda digest: object(), raising=False)

    reached = []

    class _DeadCalendar:
        def __init__(self, url):
            reached.append(url)

        def submit(self, digest, timeout=None):
            raise OSError("network down")

    monkeypatch.setattr(ts, "RemoteCalendar", _DeadCalendar, raising=False)
    assert not kill_switch_active()
    with pytest.raises(TimestampUnavailable):
        ts.ots_stamp(DIGEST, calendars=("https://x",))
    assert reached == ["https://x"]


# --------------------------------------------------------------------------- #
# save_settings() -- Path 1's consent gate (turning anchoring_mode ON)
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _isolated_custody_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))


def test_turning_on_opentimestamps_without_consent_is_refused():
    with pytest.raises(CustodySettingsError, match="consent"):
        cset.save_settings({"anchoring_mode": "opentimestamps"})
    assert cset.load_settings().anchoring_mode == "local"  # refused BEFORE writing


def test_turning_on_opentimestamps_with_consent_succeeds():
    s = cset.save_settings({"anchoring_mode": "opentimestamps", "ots_consent": True})
    assert s.anchoring_mode == "opentimestamps"


def test_resaving_while_already_on_does_not_re_demand_consent():
    """A genuine, one-time confirmation at the moment of opt-in -- not a rubber
    stamp required on every unrelated resave while it stays on."""
    cset.save_settings({"anchoring_mode": "opentimestamps", "ots_consent": True})
    # No ots_consent this time, and the mode is unchanged (still opentimestamps) --
    # this must NOT raise.
    s = cset.save_settings({"default_actor": "reporter"})
    assert s.anchoring_mode == "opentimestamps"
    assert s.default_actor == "reporter"


def test_turning_off_needs_no_consent():
    cset.save_settings({"anchoring_mode": "opentimestamps", "ots_consent": True})
    s = cset.save_settings({"anchoring_mode": "local"})  # no ots_consent -- fine
    assert s.anchoring_mode == "local"


def test_ots_consent_flag_itself_is_never_persisted():
    """A one-shot instruction to THIS call, not a stored preference -- so it can
    never be replayed by a later, unrelated PUT."""
    cset.save_settings({"anchoring_mode": "opentimestamps", "ots_consent": True})
    raw = cset._read_raw()
    assert raw is not None
    assert "ots_consent" not in raw


# --------------------------------------------------------------------------- #
# Frontend: anchorRoot() and saveCustody() route the real request through the
# app's one consent mechanism (invariant #14), mirroring app-backup.js:firstRun.
# --------------------------------------------------------------------------- #


def test_anchor_root_gates_opentimestamps_through_ensure_online():
    app = app_js()
    body = function_body(app, "anchorRoot")
    assert_present(body, "ensureOnline(", why="Path 3 must follow the ensureOnline() pattern")
    assert_present(
        body,
        't("Anchor this Merkle root into Bitcoin via OpenTimestamps")',
        why="the gate must name the real action, not a generic reason",
    )
    # The gate names the request's own provider, not a hardcoded name -- and only
    # skips the dialog for the fully-offline "local" provider.
    assert_present(body, 'provider !== "local"')


def test_anchor_root_only_sends_consent_true_for_opentimestamps():
    app = app_js()
    body = function_body(app, "anchorRoot")
    assert_present(body, 'consent: provider !== "local"')


def test_save_custody_gates_turning_on_opentimestamps():
    app = app_js()
    body = function_body(app, "saveCustody")
    assert_present(body, "confirm(", why="Path 1 needs a genuine, one-time transactional yes")
    assert_present(body, "ensureOnline(")
    assert_present(body, "ots_consent")
    assert_present(
        body,
        "!_custodyOtsWasOn",
        why="the confirm() must gate the TRANSITION, not fire on every resave",
    )


def test_save_custody_does_not_confirm_every_resave():
    """The confirm() call must be reachable only through the turningOn branch --
    not unconditionally on every save (that would be a rubber stamp, not consent)."""
    app = app_js()
    body = function_body(app, "saveCustody")
    # `confirm(` must appear strictly after the `turningOn` guard is computed and
    # inside its `if` block, not before it (i.e. not unconditional). This is an
    # ORDER check, not a slice -- re.search avoids tests/test_source_slicing_discipline.py's
    # hand-rolled-slicer detector (which flags .index/.find/.split/.rindex/.partition
    # on a code-shaped literal), since neither the correctness risk nor the fix that
    # detector exists for (over-running / truncating a source slice) applies here.
    guard_at = re.search(re.escape("const turningOn"), body).start()
    confirm_at = re.search(re.escape("confirm("), body).start()
    assert confirm_at > guard_at


# --------------------------------------------------------------------------- #
# i18n: every new string introduced by the gates is keyed in all 12 locales
# --------------------------------------------------------------------------- #

_NEW_CONSENT_STRINGS = [
    "Anchor this Merkle root into Bitcoin via OpenTimestamps",
    "Turn on OpenTimestamps anchoring? From now on, every article this app ingests will "
    "submit a hash to public Bitcoin calendar servers — revealing your IP and the "
    "timing to those servers — for as long as this stays on. This repeats on every "
    "future ingest, not just once.",
    "Enable OpenTimestamps anchoring (submits a hash to public calendar servers on every "
    "future ingest)",
]


def test_every_new_consent_string_is_keyed_in_all_twelve_locales():
    locale_files = sorted(_LOCALES.glob("*.json"))
    assert len(locale_files) == 12
    missing: list[str] = []
    for path in locale_files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for s in _NEW_CONSENT_STRINGS:
            if s not in data:
                missing.append(f"{path.name}: {s[:60]!r}")
            elif not str(data[s]).strip():
                missing.append(f"{path.name}: {s[:60]!r} is EMPTY")
    assert not missing, "unkeyed consent strings:\n  " + "\n  ".join(missing)


def test_new_consent_strings_are_actually_used_via_t_calls():
    """The keys above must be strings the JS actually passes to t(), not orphans
    added to en.json that no code site uses."""
    app = app_js()
    for s in _NEW_CONSENT_STRINGS:
        assert_present(app, f't("{s}")', why=f"{s[:40]!r} must be wrapped in a real t() call")
