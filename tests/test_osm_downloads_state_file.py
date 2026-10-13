"""The OSM region download manager's state file: it keeps what a NEWER build wrote beside the keys this build knows, and a
stored error text that this process cannot check for a passphrase is never overwritten on disk by the marker that stands in
for it. Two notes the review of the exception-text change left open.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json

from src.geo.osm_downloads import OsmDownloadManager
from src.monitoring import secret_scrub

HELD = "held-by-the-process-for-a-state-file-test-5521"


def _seed(tmp_path) -> OsmDownloadManager:
    m = OsmDownloadManager(base_dir=tmp_path, http_get=None)
    m._entry_for("europe")
    return m


def _state(m: OsmDownloadManager) -> dict:
    return json.loads(m.state_path.read_text("utf-8"))


def test_keys_a_newer_build_wrote_survive_a_rewrite_by_this_one(tmp_path):
    # MUTATION TARGET: `_extra` / `_extra_state` (read at load, handed back by `state_dict` / `_save`).
    m = _seed(tmp_path)
    state = _state(m)
    state["entries"]["europe"]["checksum_state"] = {"verified": True}
    state["mirror_health"] = {"geofabrik": "ok"}
    m.state_path.write_text(json.dumps(state), "utf-8")
    reloaded = OsmDownloadManager(base_dir=tmp_path, http_get=None)
    reloaded._save()  # any state change rewrites the file: here nothing else changed
    after = _state(reloaded)
    assert after["entries"]["europe"]["checksum_state"] == {"verified": True}
    assert after["mirror_health"] == {"geofabrik": "ok"}


def test_a_key_this_build_declares_is_never_taken_from_the_extras(tmp_path):
    m = _seed(tmp_path)
    state = _state(m)
    state["entries"]["europe"]["status"] = "paused"
    m.state_path.write_text(json.dumps(state), "utf-8")
    reloaded = OsmDownloadManager(base_dir=tmp_path, http_get=None)
    reloaded._entries["europe"].status = "queued"
    reloaded._save()
    assert _state(reloaded)["entries"]["europe"]["status"] == "queued"


def test_the_extras_never_reach_the_api_dict(tmp_path):
    m = _seed(tmp_path)
    state = _state(m)
    state["entries"]["europe"]["checksum_state"] = {"verified": True}
    m.state_path.write_text(json.dumps(state), "utf-8")
    shown = OsmDownloadManager(base_dir=tmp_path, http_get=None).list()
    assert all("checksum_state" not in e and "_extra" not in e for e in shown)


def _store_an_error(tmp_path, text: str) -> str:
    m = _seed(tmp_path)
    state = _state(m)
    state["entries"]["europe"]["status"] = "error"
    state["entries"]["europe"]["error"] = text
    m.state_path.write_text(json.dumps(state), "utf-8")
    return m.state_path.read_text("utf-8")


def test_an_error_text_that_cannot_be_checked_is_served_as_the_marker_and_kept_as_it_is_on_disk(
    tmp_path, monkeypatch
):
    # MUTATION TARGET: the `_UNCHECKED` branch in `_load` (the old form wrote the marker over the text for good).
    original = _store_an_error(tmp_path, "the transfer said: connection reset")
    monkeypatch.setattr(secret_scrub, "held_passphrases", lambda: None)
    m = OsmDownloadManager(base_dir=tmp_path, http_get=None)
    shown = next(e for e in m.list() if e["key"] == "europe")
    assert shown["error"] == secret_scrub.UNREADABLE_TEXT
    assert "connection reset" not in json.dumps(shown)
    assert m.state_path.read_text("utf-8") == original, (
        "the load must not replace the words with the marker"
    )
    m._save()  # a later save by this process writes the words it read, not the marker
    assert _state(m)["entries"]["europe"]["error"] == "the transfer said: connection reset"


def test_the_words_come_back_once_what_the_process_holds_can_be_read_again(tmp_path, monkeypatch):
    _store_an_error(tmp_path, "the transfer said: connection reset")
    with monkeypatch.context() as unreadable:
        unreadable.setattr(secret_scrub, "held_passphrases", lambda: None)
        OsmDownloadManager(base_dir=tmp_path, http_get=None)
    shown = next(
        e
        for e in OsmDownloadManager(base_dir=tmp_path, http_get=None).list()
        if e["key"] == "europe"
    )
    assert shown["error"] == "the transfer said: connection reset"


def test_a_new_error_replaces_an_unchecked_one_and_is_served_as_itself(tmp_path, monkeypatch):
    _store_an_error(tmp_path, "an older words")
    monkeypatch.setattr(secret_scrub, "held_passphrases", lambda: None)
    m = OsmDownloadManager(base_dir=tmp_path, http_get=None)
    m._entries[
        "europe"
    ].error = (
        "OSError: its text is withheld"  # what a failed download stores when nothing can be read
    )
    shown = next(e for e in m.list() if e["key"] == "europe")
    assert shown["error"] == "OSError: its text is withheld", (
        "the class stays visible, distinct from the unchecked marker"
    )
    assert shown["error"] != secret_scrub.UNREADABLE_TEXT


def test_a_failed_download_is_recorded_by_class_when_the_held_passphrases_cannot_be_read(
    tmp_path, monkeypatch
):
    # The live path: the text is made where the failure is caught, and when nothing can be checked the class is what remains.
    monkeypatch.setattr(secret_scrub, "held_passphrases", lambda: None)

    def failing_get(*_a, **_k):
        raise ConnectionResetError("connection reset by peer")

    m = OsmDownloadManager(base_dir=tmp_path, http_get=failing_get)
    entry = m._entry_for("europe")
    m._download(entry, stop_event=None)
    assert entry.status == "error"
    assert entry.error == "ConnectionResetError: its text is withheld"
    assert entry.error != secret_scrub.UNREADABLE_TEXT
    assert "connection reset by peer" not in m.state_path.read_text("utf-8")
