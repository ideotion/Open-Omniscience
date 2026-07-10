"""A11: honest ephemeral-root detection for the opt-in persistent data_dir.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The 2026-07-09 field event: a disposable-VM crash vaporized a ~60K-article corpus. This
assessment nudges a user on a PROVABLY-volatile root (tmpfs / Qubes disposable) toward the
opt-in persistent OO_DATA_DIR — but never guesses, and never says "stop using disposable
VMs". These pin the honest verdict for each signal.
"""

from __future__ import annotations

import src.monitoring.forensics as forensics


def _persist(monkeypatch, *, fstype, disposable, override, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path)) if override else monkeypatch.delenv(
        "OO_DATA_DIR", raising=False
    )
    monkeypatch.setattr(forensics, "_filesystem_type", lambda _p: fstype)
    monkeypatch.setattr(forensics, "_qubes_disposable", lambda: disposable)
    return forensics.data_dir_persistence()


def test_tmpfs_data_dir_is_at_risk_with_a_note(monkeypatch, tmp_path):
    p = _persist(monkeypatch, fstype="tmpfs", disposable=None, override=False, tmp_path=tmp_path)
    assert p["at_risk"] is True
    assert p["volatile_filesystem"] is True
    assert p["note"] and "OO_DATA_DIR" in p["note"]
    assert "stop using" not in p["note"].lower()  # never blames the user's VM choice


def test_qubes_disposable_is_at_risk(monkeypatch, tmp_path):
    p = _persist(monkeypatch, fstype="ext4", disposable=True, override=False, tmp_path=tmp_path)
    assert p["at_risk"] is True
    assert p["qubes_disposable"] is True
    assert p["note"]


def test_explicit_override_on_stable_fs_is_not_at_risk(monkeypatch, tmp_path):
    p = _persist(monkeypatch, fstype="ext4", disposable=None, override=True, tmp_path=tmp_path)
    assert p["at_risk"] is False
    assert p["explicit_override"] is True
    assert p["note"] is None  # no alarm; the user chose the location


def test_unknown_is_never_a_guess(monkeypatch, tmp_path):
    """A non-volatile fs, no override, not provably disposable -> honest 'unknown', not a
    false alarm and not a false all-clear."""
    p = _persist(monkeypatch, fstype="ext4", disposable=None, override=False, tmp_path=tmp_path)
    assert p["at_risk"] is None
    assert p["note"] is None
    assert p["how_to_persist"]  # guidance is always available


def test_filesystem_type_none_off_linux_degrades(monkeypatch, tmp_path):
    p = _persist(monkeypatch, fstype=None, disposable=None, override=False, tmp_path=tmp_path)
    assert p["at_risk"] is None  # can't prove volatile -> unknown, never a guess
    assert p["filesystem"] is None


def test_no_score_fields(monkeypatch, tmp_path):
    p = _persist(monkeypatch, fstype="tmpfs", disposable=None, override=False, tmp_path=tmp_path)
    for k in p:
        assert "score" not in k.lower() and "ranking" not in k.lower()


def test_filesystem_type_reads_proc_mounts_for_a_real_path(tmp_path):
    """The real reader returns SOME fstype for a real path on Linux (or None off Linux) —
    never raises."""
    fs = forensics._filesystem_type(tmp_path)
    assert fs is None or isinstance(fs, str)


def test_session_forensics_embeds_persistence(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    sf = forensics.session_forensics()
    assert "data_dir_persistence" in sf
    assert sf["data_dir_persistence"]["explicit_override"] is True
