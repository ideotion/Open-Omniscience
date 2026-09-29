"""The data drive (R86, 2026-09-29): marker, boot guard, watchdog, countdowns, incident log.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import paths
from src.safety import data_location as dl
from src.safety import data_volume as dv

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def drive(tmp_path, monkeypatch):
    """A marked data folder, with the incident log and oo.env kept in tmp_path."""
    folder = tmp_path / "drive" / "OOS data"
    folder.mkdir(parents=True)
    vid = dv.write_marker(folder)
    monkeypatch.setenv("OO_DATA_DIR", str(folder))
    monkeypatch.setenv(dv.ENV_ID, vid)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(dl, "env_file_path", lambda: tmp_path / "oo.env")
    monkeypatch.setattr(dv, "_BOOT_CHECKED", False)
    return folder


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _monitor(clock, calls):
    return dv.VolumeMonitor(
        pause_fn=lambda: calls.append("pause"),
        restart_fn=lambda: calls.append("restart"),
        exit_fn=lambda: calls.append("exit"),
        clock=clock,
    )


def _events() -> list[str]:
    return [r["event"] for r in dv.read_incidents()]


# --- the marker and the boot guard ------------------------------------------------


def test_probe_names_each_state(drive, monkeypatch) -> None:
    assert dv.probe()["state"] == "ok"
    (drive / dv.MARKER_NAME).write_text(json.dumps({"id": "someone-else"}), encoding="utf-8")
    assert dv.probe()["state"] == "mismatch"
    (drive / dv.MARKER_NAME).unlink()
    assert dv.probe()["state"] == "missing"
    monkeypatch.delenv(dv.ENV_ID)
    assert dv.probe()["state"] == "unwatched"


def test_a_missing_marked_folder_is_never_created(drive) -> None:
    drive.rename(drive.parent / "elsewhere")
    with pytest.raises(paths.DataVolumeMissing):
        paths.data_dir()
    assert not drive.exists(), "the folder must not be recreated on the internal disk"


def test_an_unmarked_install_keeps_creating_its_folder(tmp_path, monkeypatch) -> None:
    folder = tmp_path / "plain"
    monkeypatch.setenv("OO_DATA_DIR", str(folder))
    monkeypatch.delenv(dv.ENV_ID, raising=False)
    assert paths.data_dir() == folder and folder.is_dir()


def test_a_marked_folder_that_is_present_resolves(drive) -> None:
    assert paths.data_dir() == drive
    assert paths.data_dir() == drive   # the cheap after-boot check too


def test_the_chooser_writes_the_marker_and_the_id(tmp_path, monkeypatch) -> None:
    env = tmp_path / "oo.env"
    env.write_text("export OO_DATA_VOLUME_ID=stale\nexport OTHER=1\n", encoding="utf-8")
    monkeypatch.setattr(dl, "env_file_path", lambda: env)
    out = dl.persist(str(tmp_path / "usb"))
    assert out["saved"] is True
    target = Path(out["path"])
    vid = dv.read_marker_id(target)
    lines = env.read_text(encoding="utf-8").splitlines()
    assert f"export {dv.ENV_ID}={vid}" in lines
    assert "export OTHER=1" in lines
    assert sum(ln.startswith(f"export {dv.ENV_ID}=") for ln in lines) == 1


def test_forgetting_the_id_after_a_wipe(drive, tmp_path) -> None:
    env = tmp_path / "oo.env"
    env.write_text(f"export OO_DATA_DIR=x\nexport {dv.ENV_ID}=abc\n", encoding="utf-8")
    dv.forget_volume_id()
    assert env.read_text(encoding="utf-8") == "export OO_DATA_DIR=x\n"
    assert not dv.watched()


# --- the watchdog -----------------------------------------------------------------


def test_one_miss_is_not_an_alarm_two_are(drive) -> None:
    clock, calls = _Clock(), []
    m = _monitor(clock, calls)
    m.tick()
    (drive / dv.MARKER_NAME).rename(drive / "moved")
    m.tick()
    assert m.phase == "ok"
    m.tick()
    assert m.phase == "reconnect" and m.snapshot()["seconds_left"] == dv.RECONNECT_SECONDS
    assert "disconnected" in _events()
    rec = [r for r in dv.read_incidents() if r["event"] == "disconnected"][0]
    assert rec["path"] == str(drive) and rec["last_ok_at"]


def test_the_two_countdowns_end_in_a_shutdown(drive) -> None:
    clock, calls = _Clock(), []
    m = _monitor(clock, calls)
    (drive / dv.MARKER_NAME).unlink()
    m.tick()
    m.tick()
    clock.now += dv.RECONNECT_SECONDS
    m.tick()
    assert m.phase == "shutdown" and m.snapshot()["seconds_left"] == dv.SHUTDOWN_SECONDS
    clock.now += dv.SHUTDOWN_SECONDS - 1
    m.tick()
    assert m.phase == "shutdown" and "exit" not in calls
    clock.now += 1
    m.tick()
    assert m.phase == "closing" and calls.count("exit") == 1
    assert _events()[-3:] == ["disconnected", "shutdown_countdown", "shutdown"]


@pytest.mark.parametrize("wait", [5, dv.RECONNECT_SECONDS + 5])
def test_the_same_drive_coming_back_restarts_the_app(drive, wait) -> None:
    clock, calls = _Clock(), []
    m = _monitor(clock, calls)
    marker = (drive / dv.MARKER_NAME).read_text(encoding="utf-8")
    (drive / dv.MARKER_NAME).unlink()
    m.tick()
    m.tick()
    clock.now += wait
    m.tick()
    (drive / dv.MARKER_NAME).write_text(marker, encoding="utf-8")
    m.tick()
    assert m.phase == "restarting" and calls.count("restart") == 1 and "exit" not in calls


def test_a_different_drive_at_the_same_path_is_not_a_reconnect(drive) -> None:
    clock, calls = _Clock(), []
    m = _monitor(clock, calls)
    (drive / dv.MARKER_NAME).unlink()
    m.tick()
    m.tick()
    (drive / dv.MARKER_NAME).write_text(json.dumps({"id": "another-drive"}), encoding="utf-8")
    m.tick()
    assert m.phase == "reconnect" and "restart" not in calls


def test_a_database_disk_error_needs_only_one_miss(drive) -> None:
    clock, calls = _Clock(), []
    m = _monitor(clock, calls)
    m.poke("database error: disk i/o error")
    assert m.phase == "ok", "a disk error with the drive still there is not a disconnection"
    (drive / dv.MARKER_NAME).unlink()
    m.poke("database error: disk i/o error")
    assert m.phase == "reconnect"


def test_close_now_only_while_a_disconnection_is_handled(drive) -> None:
    clock, calls = _Clock(), []
    m = _monitor(clock, calls)
    assert m.close_now() is False and "exit" not in calls
    (drive / dv.MARKER_NAME).unlink()
    m.tick()
    m.tick()
    assert m.close_now() is True and calls.count("exit") == 1


def test_a_deliberate_wipe_is_not_read_as_a_disconnection(drive, monkeypatch) -> None:
    clock, calls = _Clock(), []
    m = _monitor(clock, calls)
    monkeypatch.delenv(dv.ENV_ID)
    (drive / dv.MARKER_NAME).unlink()
    m.tick()
    m.tick()
    assert m.phase == "ok" and not calls


# --- what the operator sees -------------------------------------------------------


def test_the_waiting_page_is_translated_and_escaped(drive, monkeypatch) -> None:
    monkeypatch.setenv("OO_DATA_DIR", str(drive) + "<b>")
    page = dv.waiting_page({"state": "missing"}, "fr-FR,fr;q=0.9")
    assert "Votre disque de données n&#x27;est pas connecté" in page
    assert "&lt;b&gt;" in page and "<b>" not in page
    assert 'http-equiv="refresh"' in page and "/quit" in page


def test_the_state_endpoint_never_discloses_the_path(drive) -> None:
    from src.api.unlock import allowed_while_locked, data_volume_state

    out = data_volume_state()
    assert set(out) == {"watched", "phase", "seconds_left"}
    assert str(drive) not in json.dumps(out)
    assert allowed_while_locked("/api/system/data-volume", "locked")
    assert allowed_while_locked("/api/system/data-volume/close-now", "locked")


def test_the_countdown_script_is_on_both_pages() -> None:
    for page in ("index.html", "unlock.html"):
        html = (ROOT / "src/static" / page).read_text(encoding="utf-8")
        assert '<script src="/static/data-volume.js"></script>' in html, page
    js = (ROOT / "src/static/data-volume.js").read_text(encoding="utf-8")
    assert "onclick" not in js and "Math.random" not in js
    en = json.loads((ROOT / "src/static/locales/en.json").read_text(encoding="utf-8"))
    for key in ("Reconnect it within {n} s.", "The app will close in {n} s to protect your data.", "Close now"):
        assert key in js and key in en


def test_how_it_ended_names_the_drive(drive) -> None:
    from src.monitoring.exit_evidence import how_it_ended

    dv.record_incident("disconnected", detected_by="the marker check failed 2 times in a row (missing)")
    rec = dv.last_disconnect_since("2000-01-01T00:00:00")
    out = how_it_ended(launcher=None, killers=None, kernel=None, trace=None, drive=rec)
    assert out["known"] and "data drive was reported disconnected" in out["summary"]
    assert dv.last_disconnect_since("2999-01-01T00:00:00") is None


def test_recording_a_disconnection_can_reach_data_dir_without_hanging(drive, monkeypatch) -> None:
    """Found live: the first watchdog hung the whole API, because recording a
    disconnection reached data_dir(), whose guard poked the monitor back on the same
    thread while it held a plain Lock."""
    clock, calls = _Clock(), []
    m = _monitor(clock, calls)
    monkeypatch.setattr(dv, "_activity", lambda: (m.poke("re-entered"), {})[1])
    (drive / dv.MARKER_NAME).unlink()
    done = []
    import threading

    t = threading.Thread(target=lambda: (m.tick(), m.tick(), done.append(True)), daemon=True)
    t.start()
    t.join(5)
    assert done, "the watchdog deadlocked on its own re-entry"
    assert m.phase == "reconnect" and _events().count("disconnected") == 1
