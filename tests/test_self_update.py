"""The in-app update: what counts as newer, what is refused, and the helper's git swap (real git, no network).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.maintenance import self_update as su

ROOT = Path(__file__).resolve().parents[1]
SHA_A = "a" * 40
SHA_B = "b" * 40
#: scripts/launch_stopped.cmd, which must never change (see the test that pins it).
FROZEN_STOP_SHA256 = "8ec4653d7df400296bcc0bea64accd6c7f8de6c59b61016774d7401478e35f6e"


def _helper():
    spec = importlib.util.spec_from_file_location("apply_update", ROOT / "scripts" / "apply_update.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tags(*pairs):
    return [{"name": n, "commit": {"sha": s}} for n, s in pairs]


def test_newest_tag_is_the_highest_semver_and_skips_malformed_rows():
    rows = _tags(("v0.4.0", SHA_A), ("v0.10.0", SHA_B), ("v0.9.9", SHA_A), ("nightly", SHA_A), ("v1.0.0-rc1", SHA_A)) + [
        {"name": "v9.9.9", "commit": {"sha": "not-a-sha"}},
        "junk",
        {"name": 5},
    ]
    assert su.pick_newest_tag(rows) == ("v0.10.0", SHA_B)
    assert su.pick_newest_tag([]) is None
    assert su.pick_newest_tag({"message": "rate limited"}) is None


def test_check_compares_against_the_newest_tag_and_never_moves_backwards(monkeypatch):
    monkeypatch.setattr(su, "current_version", lambda: "0.5.0")
    monkeypatch.setattr(su, "install_status", lambda root=None: {"kind": "git", "can_apply": True, "reason": "", "manual_steps": []})
    newer = su.check(lambda url: _tags(("v0.5.0", SHA_A), ("v0.6.0", SHA_B)))
    assert newer["update_available"] and newer["ref"] == "v0.6.0" and newer["sha"] == SHA_B and newer["kind"] == "tag"
    same = su.check(lambda url: _tags(("v0.5.0", SHA_A), ("v0.4.0", SHA_B)))
    assert not same["update_available"]
    older = su.check(lambda url: _tags(("v0.3.0", SHA_A)))
    assert not older["update_available"]


def test_check_falls_back_to_main_only_when_no_tag_exists(monkeypatch):
    monkeypatch.setattr(su, "current_version", lambda: "0.5.0")
    monkeypatch.setattr(su, "_local_head", lambda root: SHA_A)
    monkeypatch.setattr(su, "install_status", lambda root=None: {"kind": "git", "can_apply": True, "reason": "", "manual_steps": []})
    seen = []

    def fetch(url):
        seen.append(url)
        return [] if url == su.TAGS_URL else {"sha": SHA_B}

    out = su.check(fetch)
    assert seen == [su.TAGS_URL, su.MAIN_URL]
    assert out["kind"] == "main" and out["update_available"] and out["sha"] == SHA_B
    with pytest.raises(su.UpdateError):
        su.check(lambda url: [] if url == su.TAGS_URL else {"sha": "zz"})


def test_apply_needs_the_exact_checked_ref_and_sha_and_a_fresh_check(monkeypatch):
    monkeypatch.setattr(su, "current_version", lambda: "0.5.0")
    ok = {"kind": "git", "can_apply": True, "reason": "", "manual_steps": []}
    monkeypatch.setattr(su, "install_status", lambda root=None: ok)
    su._LAST_CHECK.clear()
    with pytest.raises(su.UpdateError, match="Check for an update first"):
        su.validate_apply("v0.6.0", SHA_B)
    su.check(lambda url: _tags(("v0.6.0", SHA_B)), now=1000.0)
    assert su.validate_apply("v0.6.0", SHA_B, now=1100.0)["sha"] == SHA_B
    with pytest.raises(su.UpdateError, match="not the one"):
        su.validate_apply("v0.6.0", SHA_A, now=1100.0)
    with pytest.raises(su.UpdateError, match="not the one"):
        su.validate_apply("v9.9.9", SHA_B, now=1100.0)
    with pytest.raises(su.UpdateError, match="hour old"):
        su.validate_apply("v0.6.0", SHA_B, now=1000.0 + su.CHECK_TTL_S + 1)
    monkeypatch.setattr(su, "install_status", lambda root=None: {**ok, "can_apply": False, "reason": "local_changes"})
    with pytest.raises(su.UpdateError, match="local_changes"):
        su.validate_apply("v0.6.0", SHA_B, now=1100.0)


def test_a_check_in_airplane_mode_is_named_by_the_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.ingest import activate_kill_switch, clear_kill_switch

    activate_kill_switch()
    try:
        r = TestClient(app, base_url="http://127.0.0.1").post("/api/system/update/check")
    finally:
        clear_kill_switch()
    assert r.status_code == 409 and "Airplane mode" in r.json()["detail"]


def test_apply_endpoint_refuses_without_confirm_and_without_a_check():
    from fastapi.testclient import TestClient

    from src.api.main import app

    c = TestClient(app, base_url="http://127.0.0.1")
    assert c.post("/api/system/update/apply", json={"ref": "v1.0.0", "sha": SHA_A}).status_code == 400
    su._LAST_CHECK.clear()
    assert c.post("/api/system/update/apply", json={"confirm": True, "ref": "v1.0.0", "sha": SHA_A}).status_code == 409


# --- the helper, against real git repositories ---------------------------------------------------------------------- #


def _g(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), *a], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def repos(tmp_path):
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True, capture_output=True)
    for k, v in (("user.email", "t@example.org"), ("user.name", "t")):
        _g(work, "config", k, v)
    (work / "a.txt").write_text("1", encoding="utf-8")
    _g(work, "add", ".")
    _g(work, "commit", "-qm", "one")
    _g(work, "branch", "-M", "main")
    _g(work, "push", "-q", "origin", "main")
    # the checkout under test: origin NAMES the real repository, git is told where that address really is
    inst = tmp_path / "inst"
    subprocess.run(["git", "clone", "-q", str(bare), str(inst)], check=True, capture_output=True)
    _g(inst, "remote", "set-url", "origin", "https://github.com/ideotion/Open-Omniscience.git")
    _g(inst, "config", f"url.{bare}.insteadOf", "https://github.com/ideotion/Open-Omniscience.git")
    (work / "a.txt").write_text("2", encoding="utf-8")
    _g(work, "commit", "-qam", "two")
    _g(work, "tag", "v0.6.0")
    _g(work, "push", "-q", "origin", "main", "--tags")
    return inst, work, _g(work, "rev-parse", "HEAD")


def _plan(inst, sha, ref="v0.6.0"):
    return {"root": str(inst), "ref": ref, "sha": sha, "python": "python"}


def test_helper_fast_forwards_to_the_checked_commit(repos):
    inst, _work, sha = repos
    status, old = _helper().apply(_plan(inst, sha))
    assert status == "updated" and _g(inst, "rev-parse", "HEAD") == sha and old != sha
    assert _g(inst, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_helper_refuses_a_commit_that_is_not_the_one_the_check_named(repos):
    inst, _work, sha = repos
    before = _g(inst, "rev-parse", "HEAD")
    status, _ = _helper().apply(_plan(inst, "0" * 40))
    assert status == "commit_mismatch" and _g(inst, "rev-parse", "HEAD") == before


def test_helper_refuses_dirty_tree_other_branch_and_foreign_origin(repos):
    inst, _work, sha = repos
    h = _helper()
    (inst / "a.txt").write_text("local edit", encoding="utf-8")
    assert h.apply(_plan(inst, sha))[0] == "local_changes"
    _g(inst, "checkout", "-q", ".")
    _g(inst, "checkout", "-q", "-b", "side")
    assert h.apply(_plan(inst, sha))[0] == "not_on_main"
    _g(inst, "checkout", "-q", "main")
    _g(inst, "remote", "set-url", "origin", "https://github.com/someone-else/fork.git")
    assert h.apply(_plan(inst, sha))[0] == "origin_not_this_repository"
    assert h.apply({**_plan(inst, sha), "ref": "--upload-pack=x"})[0] == "bad_plan"


def test_helper_reports_a_version_the_checkout_already_has(repos):
    inst, _work, sha = repos
    h = _helper()
    assert h.apply(_plan(inst, sha))[0] == "updated"
    assert h.apply(_plan(inst, sha))[0] == "already_current"


def test_a_timeout_or_missing_program_is_a_failed_step_not_a_crash(tmp_path):
    h = _helper()
    assert h._run(tmp_path, "oo-no-such-program-xyz").returncode == 127
    assert h._run(tmp_path, sys.executable, "-c", "import time; time.sleep(5)", timeout=1).returncode == 124


def test_a_second_apply_is_refused_and_the_check_is_spent(monkeypatch):
    monkeypatch.setattr(su, "current_version", lambda: "0.5.0")
    monkeypatch.setattr(su, "_checkout_contains", lambda root, sha: False)
    monkeypatch.setattr(su, "install_status", lambda root=None: {"kind": "git", "can_apply": True, "reason": "", "manual_steps": []})
    monkeypatch.setattr(su, "launch_helper", lambda *a, **k: None)
    monkeypatch.setattr(su, "_helper_running", lambda root=None: False)
    monkeypatch.setattr(su, "refuse_offline_or_protected", lambda: None)
    monkeypatch.setattr(su, "_APPLYING", None)
    monkeypatch.setattr(su, "_LAST_CHECK", {})
    su.check(lambda url: _tags(("v0.6.0", SHA_B)), now=1000.0)
    su.begin_apply("v0.6.0", SHA_B, now=1001.0)
    with pytest.raises(su.UpdateError, match="already starting"):
        su.begin_apply("v0.6.0", SHA_B, now=1002.0)
    assert su._LAST_CHECK == {}


def test_check_says_up_to_date_when_the_checkout_runs_the_tag_commit(monkeypatch):
    monkeypatch.setattr(su, "current_version", lambda: "0.3.0")  # stale metadata, as when v0.4.0 was cut before its version flip
    monkeypatch.setattr(su, "_local_head", lambda root: SHA_B)
    monkeypatch.setattr(su, "install_status", lambda root=None: {"kind": "git", "can_apply": True, "reason": "", "manual_steps": []})
    assert su.check(lambda url: _tags(("v0.4.0", SHA_B)))["update_available"] is False


def test_helper_never_touches_the_install_when_the_app_does_not_exit():
    h = _helper()
    assert h.wait_for_exit(1, 0.0, alive=lambda pid: True, sleep=lambda s: None) is False
    assert h.wait_for_exit(1, 5.0, alive=(lambda it: (lambda pid: next(it)))(iter([True, True, False])), sleep=lambda s: None) is True


def test_install_status_reports_a_non_checkout_with_manual_steps(tmp_path):
    st = su.install_status(tmp_path)
    assert st["can_apply"] is False and st["reason"] == "not_a_git_checkout" and st["manual_steps"]


def test_check_says_up_to_date_when_the_checkout_is_ahead_of_the_tag(repos, monkeypatch):
    inst, work, tag_sha = repos
    _g(inst, "pull", "-q", "--ff-only", "origin", "main")
    (inst / "a.txt").write_text("3", encoding="utf-8")
    _g(inst, "-c", "user.email=t@example.org", "-c", "user.name=t", "commit", "-qam", "ahead")
    monkeypatch.setattr(su, "current_version", lambda: "0.3.0")
    monkeypatch.setattr(su, "install_status", lambda root=None: {"kind": "git", "can_apply": True, "reason": "", "manual_steps": []})
    assert su.check(lambda url: _tags(("v0.6.0", tag_sha)), root=inst)["update_available"] is False
    # a commit this checkout has never seen is not "contained"
    assert su.check(lambda url: _tags(("v0.6.0", "c" * 40)), root=inst)["update_available"] is True


def test_the_helper_lock_obeys_a_live_fresh_holder_and_takes_over_a_stale_one(tmp_path):
    h = _helper()
    lock = tmp_path / "update.lock"
    lock.write_text("111 424242", encoding="utf-8")
    assert h.take_lock(lock, 111, alive=lambda pid: True) is False  # a live duplicate for this same shutdown
    assert h.take_lock(lock, 222, alive=lambda pid: True) is False  # a live helper still applying for an earlier app run
    # older than any real run: stale even if its helper pid looks alive (recycled after a reboot)
    assert h.take_lock(lock, 222, alive=lambda pid: True, now=lambda: time.time() + h.LOCK_STALE_S + 1) is True
    assert lock.read_text(encoding="utf-8") == f"222 {os.getpid()}"
    lock.write_text("222 424242", encoding="utf-8")
    assert h.take_lock(lock, 222, alive=lambda pid: False) is True  # its helper is gone
    lock.write_text("garbage", encoding="utf-8")
    assert h.take_lock(lock, 222, alive=lambda pid: True) is True
    assert sorted(p.name for p in tmp_path.iterdir()) == ["update.lock"], "no temp file is left behind"
    h.release_lock(lock)
    assert not lock.exists()
    lock.write_text("222 424242", encoding="utf-8")
    h.release_lock(lock)  # not ours: left alone
    assert lock.exists()


def test_apply_is_refused_before_the_app_stops_while_a_helper_is_still_running(monkeypatch):
    monkeypatch.setattr(su, "current_version", lambda: "0.5.0")
    monkeypatch.setattr(su, "_checkout_contains", lambda root, sha: False)
    monkeypatch.setattr(su, "install_status", lambda root=None: {"kind": "git", "can_apply": True, "reason": "", "manual_steps": []})
    started = []
    monkeypatch.setattr(su, "launch_helper", lambda *a, **k: started.append(a))
    monkeypatch.setattr(su, "_helper_running", lambda root=None: True)
    monkeypatch.setattr(su, "refuse_offline_or_protected", lambda: None)
    monkeypatch.setattr(su, "_APPLYING", None)
    monkeypatch.setattr(su, "_LAST_CHECK", {})
    su.check(lambda url: _tags(("v0.6.0", SHA_B)), now=1000.0)
    with pytest.raises(su.UpdateError, match="still being applied"):
        su.begin_apply("v0.6.0", SHA_B, now=1001.0)
    assert started == [] and su._APPLYING is None


def test_helper_reports_already_current_when_the_checkout_is_ahead(repos):
    inst, _work, sha = repos
    _g(inst, "pull", "-q", "--ff-only", "origin", "main")
    (inst / "a.txt").write_text("3", encoding="utf-8")
    _g(inst, "-c", "user.email=t@example.org", "-c", "user.name=t", "commit", "-qam", "ahead")
    assert _helper().apply(_plan(inst, sha))[0] == "already_current"


def test_the_server_reads_the_real_helper_lock(tmp_path, monkeypatch):
    import src.paths as paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    assert su._helper_running(ROOT) is False  # no lock
    (tmp_path / "update.lock").write_text(f"1 {os.getpid() + 0}", encoding="utf-8")
    # the lock names THIS test process as its helper, which lock_holder_alive never counts as another holder
    assert su._helper_running(ROOT) is False
    (tmp_path / "update.lock").write_text(f"1 {os.getppid()}", encoding="utf-8")
    assert su._helper_running(ROOT) is True  # a live helper (our parent stands in for it)
    assert su._helper_running(ROOT, now=lambda: time.time() + su.LOCK_STALE_S + 1) is False  # too old to be a real run
    assert su._helper_running(ROOT, alive=lambda pid: False) is False  # its helper is gone
    (tmp_path / "update.lock").write_text("garbage", encoding="utf-8")
    assert su._helper_running(ROOT) is False  # unreadable: no holder, never a 500
    # the server's reading and the helper's own agree on every case above
    h = _helper()
    lock = tmp_path / "update.lock"
    for text, alive, later in ((f"1 {os.getppid()}", True, 0), (f"1 {os.getppid()}", False, 0), (f"1 {os.getppid()}", True, h.LOCK_STALE_S + 1), ("x", True, 0)):
        lock.write_text(text, encoding="utf-8")
        clock = (lambda d: (lambda: time.time() + d))(later)
        assert su._helper_running(ROOT, alive=lambda pid, a=alive: a, now=clock) == (
            h.lock_holder_alive(lock, alive=lambda pid, a=alive: a, now=clock) is not None
        )


def test_wait_for_server_gives_up_and_reports(tmp_path):
    h = _helper()
    assert h.wait_for_server(1, 0.0, answers=lambda port: False, sleep=lambda s: None) is False
    seq = iter([False, True])
    assert h.wait_for_server(1, 5.0, answers=lambda port: next(seq), sleep=lambda s: None) is True


def test_main_refused_by_a_live_holder_touches_nothing_and_relaunches_only_for_an_earlier_run(tmp_path, monkeypatch):
    import json as _json

    h = _helper()
    plan = tmp_path / "update-plan.json"
    plan.write_text(_json.dumps({"ref": "v0.6.0", "sha": SHA_B, "kind": "tag", "pid": 111, "root": str(tmp_path), "port": "1"}), encoding="utf-8")
    relaunched, applied = [], []
    monkeypatch.setattr(h, "pid_alive", lambda pid: pid == 999)  # the holder helper is alive, the apps are gone
    monkeypatch.setattr(h, "relaunch", lambda root, **k: relaunched.append(root))
    monkeypatch.setattr(h, "apply", lambda plan, **k: applied.append(plan) or ("updated", ""))
    monkeypatch.setattr(h, "wait_for_server", lambda port, *a, **k: False)
    lock = tmp_path / "update.lock"
    lock.write_text("111 999", encoding="utf-8")  # the same shutdown's helper
    assert h.main(["x", str(plan)]) == 1 and relaunched == [] and applied == []
    lock.write_text("50 999", encoding="utf-8")  # an earlier run's helper, still alive
    monkeypatch.setattr(h, "wait_for_exit", lambda pid, *a, **k: True)
    assert h.main(["x", str(plan)]) == 1 and len(relaunched) == 1 and applied == []


# --- the security read's must-fixes (2026-11-08): each guard below fails when it is removed --------------------------- #


def _checked_for_apply(monkeypatch, started):
    monkeypatch.setattr(su, "current_version", lambda: "0.5.0")
    monkeypatch.setattr(su, "_checkout_contains", lambda root, sha: False)
    monkeypatch.setattr(su, "install_status", lambda root=None: {"kind": "git", "can_apply": True, "reason": "", "manual_steps": []})
    monkeypatch.setattr(su, "launch_helper", lambda *a, **k: started.append(a))
    monkeypatch.setattr(su, "_helper_running", lambda root=None: False)
    monkeypatch.setattr(su, "_APPLYING", None)
    monkeypatch.setattr(su, "_LAST_CHECK", {})
    su.check(lambda url: _tags(("v0.6.0", SHA_B)), now=time.time())


def _standard_settings(monkeypatch, **kw):
    import src.safety.settings as settings

    st = settings.SafetySettings(**kw)
    monkeypatch.setattr(settings, "load_settings", lambda: st)
    return st


def test_apply_is_refused_in_airplane_mode_before_any_helper_starts(monkeypatch):
    from src.ingest import activate_kill_switch, clear_kill_switch

    started: list = []
    _checked_for_apply(monkeypatch, started)
    _standard_settings(monkeypatch)
    activate_kill_switch()
    try:
        with pytest.raises(su.UpdateError) as exc:
            su.begin_apply("v0.6.0", SHA_B)
    finally:
        clear_kill_switch()
    assert str(exc.value) == su.AIRPLANE_REFUSAL and started == [] and su._APPLYING is None


def test_the_apply_endpoint_names_airplane_mode_and_never_stops_the_app(monkeypatch):
    from fastapi.testclient import TestClient

    import src.safety.shutdown as shutdown
    from src.api.main import app
    from src.ingest import activate_kill_switch, clear_kill_switch

    started: list = []
    stopped: list = []
    _checked_for_apply(monkeypatch, started)
    _standard_settings(monkeypatch)
    monkeypatch.setattr(shutdown, "request_shutdown", lambda **k: stopped.append(k) or {})
    activate_kill_switch()
    try:
        r = TestClient(app, base_url="http://127.0.0.1").post(
            "/api/system/update/apply", json={"confirm": True, "ref": "v0.6.0", "sha": SHA_B}
        )
    finally:
        clear_kill_switch()
    assert r.status_code == 409 and r.json()["detail"]["code"] == "airplane"
    assert started == [] and stopped == []


def test_apply_is_refused_in_protected_mode_and_when_settings_cannot_be_read(monkeypatch):
    started: list = []
    _checked_for_apply(monkeypatch, started)
    _standard_settings(monkeypatch, fetch_mode="protected")
    with pytest.raises(su.UpdateError) as exc:
        su.begin_apply("v0.6.0", SHA_B)
    assert str(exc.value) == su.PROTECTED_REFUSAL and started == []
    st = _standard_settings(monkeypatch)
    st.read_failed = True
    with pytest.raises(su.UpdateError):
        su.begin_apply("v0.6.0", SHA_B)
    import src.safety.settings as settings

    monkeypatch.setattr(settings, "load_settings", lambda: (_ for _ in ()).throw(RuntimeError("locked")))
    with pytest.raises(su.UpdateError):
        su.begin_apply("v0.6.0", SHA_B)
    assert started == []
    _standard_settings(monkeypatch)
    su.begin_apply("v0.6.0", SHA_B)  # standard mode, online: it starts
    assert len(started) == 1


def test_the_helper_is_started_without_the_passphrase_and_starts_nothing_with_it(monkeypatch, tmp_path):
    import src.paths as paths
    from src.monitoring.secret_scrub import HELD_ENV_VARS

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    for name in HELD_ENV_VARS:
        monkeypatch.setenv(name, "s3cret-value")
    seen: list = []
    su.launch_helper("v0.6.0", SHA_B, "tag", root=ROOT, popen=lambda argv, **k: seen.append(k))
    assert seen and all(name not in seen[0]["env"] for name in HELD_ENV_VARS)
    assert "s3cret-value" not in (tmp_path / su.PLAN_FILE).read_text(encoding="utf-8")
    h = _helper()
    assert tuple(h.SECRET_ENV) == tuple(HELD_ENV_VARS) and h.LOCK_STALE_S == su.LOCK_STALE_S
    env = h.child_env()
    assert all(name not in env for name in HELD_ENV_VARS) and env["GIT_TERMINAL_PROMPT"] == "0"
    out = h._run(tmp_path, sys.executable, "-c", "import os; print(os.environ.get('OO_DB_PASSPHRASE', 'absent'))")
    assert out.stdout.strip() == "absent"
    launched: list = []
    h.relaunch(tmp_path, popen=lambda argv, **k: launched.append(k))
    assert all(name not in launched[0]["env"] for name in HELD_ENV_VARS)


def test_a_redirect_off_the_api_host_is_refused_not_followed(monkeypatch):
    import src.safety.fetcher as fetcher

    class _Session:
        def get(self, *a, **k):
            raise fetcher.RedirectRefused("a redirect left the hosts this session may reach")

    seen: dict = {}

    def fake_session(**k):
        seen.update(k)
        return _Session()

    monkeypatch.setattr(fetcher, "guarded_session", fake_session)
    with pytest.raises(su.UpdateError, match="refused"):
        su._get_json(su.TAGS_URL)
    assert seen["allowed_hosts"] == ("api.github.com",)


def test_the_ui_asks_the_consent_popup_before_the_update_starts():
    js = (ROOT / "src" / "static" / "app-settings.js").read_text(encoding="utf-8")
    body = js[js.index("async function updApply()"):js.index("(function _updWire()")]
    gate, confirm, post = body.index("await ensureOnline("), body.index("window.confirm("), body.index('"/api/system/update/apply"')
    assert gate < confirm < post
    # protected mode is read first, so the consent popup never takes the app online for an update the server will refuse
    assert body.index('st.blocked === "protected"') < gate
    assert 'code === "protected"' in body and 'code === "airplane"' in body


class _Proc:
    def __init__(self, code):
        self.code = code

    def poll(self):
        return self.code


def test_watch_start_tells_up_from_a_failed_start_from_a_slow_one():
    h = _helper()
    nap = lambda s: None  # noqa: E731
    assert h.watch_start(_Proc(None), 1, 5.0, answers=lambda p: True, sleep=nap) == "up"
    assert h.watch_start(_Proc(1), 1, 5.0, answers=lambda p: False, sleep=nap) == "exited"
    assert h.watch_start(None, 1, 5.0, answers=lambda p: False, sleep=nap) == "exited"
    assert h.watch_start(_Proc(None), 1, 0.0, answers=lambda p: False, sleep=nap) == "unknown"
    # a window the person closed is their stop, not a failed start
    assert h.watch_start(_Proc(0xC000013A), 1, 5.0, answers=lambda p: False, sleep=nap) == "closed"
    assert h.watch_start(_Proc(-1073741510), 1, 5.0, answers=lambda p: False, sleep=nap) == "closed"


def test_a_new_version_that_does_not_start_is_undone_and_the_old_one_started(tmp_path, monkeypatch):
    import json as _json

    h = _helper()
    plan = tmp_path / "update-plan.json"
    plan.write_text(_json.dumps({"ref": "v0.6.0", "sha": SHA_B, "kind": "tag", "pid": 111, "root": str(tmp_path), "port": "1"}), encoding="utf-8")
    monkeypatch.setattr(h, "wait_for_exit", lambda pid, *a, **k: True)
    monkeypatch.setattr(h, "server_answers", lambda port: False)
    monkeypatch.setattr(h, "apply", lambda plan, **k: ("updated", SHA_A))
    launched: list = []
    monkeypatch.setattr(h, "relaunch", lambda root, **k: launched.append(root) or _Proc(1))
    monkeypatch.setattr(h, "watch_start", lambda proc, port, *a, **k: "exited")
    monkeypatch.setattr(h, "changed_files", lambda root, old, new, **k: ["a.txt"])
    undone: list = []
    monkeypatch.setattr(h, "roll_back", lambda root, old, changed, py, **k: undone.append(old) or True)
    assert h.main(["x", str(plan)]) == 1
    assert undone == [SHA_A] and len(launched) == 2
    assert _json.loads((tmp_path / h.RESULT_FILE).read_text(encoding="utf-8"))["status"] == "start_failed_rolled_back"
    # a slow start is reported, never undone
    plan.write_text(_json.dumps({"ref": "v0.6.0", "sha": SHA_B, "kind": "tag", "pid": 111, "root": str(tmp_path), "port": "1"}), encoding="utf-8")
    monkeypatch.setattr(h, "watch_start", lambda proc, port, *a, **k: "unknown")
    undone.clear()
    assert h.main(["x", str(plan)]) == 0 and undone == []
    assert _json.loads((tmp_path / h.RESULT_FILE).read_text(encoding="utf-8"))["status"] == "start_unconfirmed"


def test_every_tag_page_is_read(monkeypatch):
    monkeypatch.setattr(su, "current_version", lambda: "0.5.0")
    monkeypatch.setattr(su, "_checkout_contains", lambda root, sha: False)
    monkeypatch.setattr(su, "install_status", lambda root=None: {"kind": "git", "can_apply": True, "reason": "", "manual_steps": []})
    page_one = _tags(*((f"v0.0.{i}", SHA_A) for i in range(100)))
    seen: list = []

    def fetch(url):
        seen.append(url)
        return page_one if url == su.TAGS_URL else _tags(("v0.10.0", SHA_B))

    out = su.check(fetch)
    assert out["ref"] == "v0.10.0" and seen == [su.TAGS_URL, su.TAGS_URL + "&page=2"]


def _plan_file(tmp_path):
    import json as _json

    plan = tmp_path / "update-plan.json"
    plan.write_text(_json.dumps({"ref": "v0.6.0", "sha": SHA_B, "kind": "tag", "pid": 111, "root": str(tmp_path), "port": "1"}), encoding="utf-8")
    return plan


def _result(tmp_path, h):
    import json as _json

    return _json.loads((tmp_path / h.RESULT_FILE).read_text(encoding="utf-8"))["status"]


def test_an_app_already_running_again_is_never_swapped_under(tmp_path, monkeypatch):
    h = _helper()
    plan = _plan_file(tmp_path)
    applied: list = []
    launched: list = []
    monkeypatch.setattr(h, "wait_for_exit", lambda pid, *a, **k: True)
    monkeypatch.setattr(h, "apply", lambda plan, **k: applied.append(1) or ("updated", SHA_A))
    monkeypatch.setattr(h, "relaunch", lambda root, **k: launched.append(k) or _Proc(None))
    monkeypatch.setattr(h, "server_answers", lambda port: True)
    assert h.main(["x", str(plan)]) == 1 and applied == [] and launched == []
    assert _result(tmp_path, h) == "app_running_again"
    # started by hand WHILE the files were swapped: said so, and no second launcher
    plan = _plan_file(tmp_path)
    answers = iter([False, True])
    monkeypatch.setattr(h, "server_answers", lambda port: next(answers))
    assert h.main(["x", str(plan)]) == 1 and applied == [1] and launched == []
    assert _result(tmp_path, h) == "app_started_during_update"


def test_a_failed_start_whose_rollback_fails_says_so(tmp_path, monkeypatch):
    h = _helper()
    plan = _plan_file(tmp_path)
    monkeypatch.setattr(h, "wait_for_exit", lambda pid, *a, **k: True)
    monkeypatch.setattr(h, "server_answers", lambda port: False)
    monkeypatch.setattr(h, "apply", lambda plan, **k: ("updated", SHA_A))
    launched: list = []
    monkeypatch.setattr(h, "relaunch", lambda root, **k: launched.append(k) or _Proc(1))
    monkeypatch.setattr(h, "watch_start", lambda proc, port, *a, **k: "exited")
    monkeypatch.setattr(h, "changed_files", lambda root, old, new, **k: ["requirements.lock"])
    monkeypatch.setattr(h, "roll_back", lambda *a, **k: False)
    assert h.main(["x", str(plan)]) == 1 and _result(tmp_path, h) == "rollback_incomplete"
    assert launched[0] == {"watched": True} and launched[1] == {}  # only the start being judged is watched
    # a window the person closed is their stop: never undone
    plan = _plan_file(tmp_path)
    undone: list = []
    monkeypatch.setattr(h, "roll_back", lambda *a, **k: undone.append(1) or True)
    monkeypatch.setattr(h, "watch_start", lambda proc, port, *a, **k: "closed")
    assert h.main(["x", str(plan)]) == 0 and undone == [] and _result(tmp_path, h) == "start_unconfirmed"


def test_update_status_names_protected_mode_for_the_button(monkeypatch):
    from fastapi.testclient import TestClient

    from src.api.main import app

    c = TestClient(app, base_url="http://127.0.0.1")
    _standard_settings(monkeypatch, fetch_mode="protected")
    assert c.get("/api/system/update/status").json()["blocked"] == "protected"
    _standard_settings(monkeypatch)
    assert c.get("/api/system/update/status").json()["blocked"] is None


def _commit_file(work, name, text, tag):
    (work / name).write_text(text, encoding="utf-8")
    _g(work, "add", ".")
    _g(work, "commit", "-qm", name)
    _g(work, "tag", tag)
    _g(work, "push", "-q", "origin", "main", "--tags")
    return _g(work, "rev-parse", "HEAD")


_PYPROJECT = '[build-system]\nrequires = ["setuptools"]\n\n[project]\nname = "x"\nversion = "{v}"\ndependencies = [{deps}]\n'


def test_a_version_that_changes_the_dependencies_is_left_to_the_installer_untouched(repos):
    inst, work, _sha = repos
    h = _helper()
    before = _g(inst, "rev-parse", "HEAD")
    ran: list = []
    new = _commit_file(work, "requirements.lock", "x==1 --hash=sha256:00\n", "v0.7.0")
    assert h.apply(_plan(inst, new, "v0.7.0"), run=lambda *a, **k: ran.append(a))[0] == "dependencies_changed"
    assert _g(inst, "rev-parse", "HEAD") == before and ran == []  # nothing swapped, pip never run
    new = _commit_file(work, "pyproject.toml", _PYPROJECT.format(v="0.8.0", deps='"a>=2"'), "v0.8.0")
    assert h.apply(_plan(inst, new, "v0.8.0"), run=lambda *a, **k: ran.append(a))[0] == "dependencies_changed"
    assert _g(inst, "rev-parse", "HEAD") == before and ran == []


def test_a_version_flip_alone_is_applied_and_its_metadata_refreshed_offline(repos):
    inst, work, _sha = repos
    h = _helper()
    ok = subprocess.CompletedProcess([], 0, "", "")
    base = _commit_file(work, "pyproject.toml", _PYPROJECT.format(v="0.6.0", deps='"a>=1"'), "v0.6.1")
    assert h.apply(_plan(inst, base, "v0.6.1"), run=lambda *a, **k: ok)[0] == "dependencies_changed"  # pyproject appeared: a change
    _g(inst, "pull", "-q", "--ff-only", "origin", "main")
    new = _commit_file(work, "pyproject.toml", _PYPROJECT.format(v="0.7.0", deps='"a>=1"'), "v0.7.0")
    ran: list = []
    assert h.apply(_plan(inst, new, "v0.7.0"), run=lambda *a, **k: ran.append(a) or ok)[0] == "updated"
    assert _g(inst, "rev-parse", "HEAD") == new
    pip = [a for a in ran if "pip" in a]
    assert len(pip) == 1 and {"--no-index", "--no-deps", "--no-build-isolation", "-e"} <= set(pip[0])
    assert not any("--require-hashes" in a or "-r" in a for a in ran)


def test_a_failed_metadata_refresh_puts_the_checkout_back(repos):
    inst, work, _sha = repos
    h = _helper()
    _commit_file(work, "pyproject.toml", _PYPROJECT.format(v="0.6.0", deps=""), "v0.6.1")
    _g(inst, "pull", "-q", "--ff-only", "origin", "main")
    before = _g(inst, "rev-parse", "HEAD")
    new = _commit_file(work, "pyproject.toml", _PYPROJECT.format(v="0.7.0", deps=""), "v0.7.0")

    def pip_fails(root, *argv, **k):
        return subprocess.CompletedProcess([], 1 if "pip" in argv else 0, "", "")

    assert h.apply(_plan(inst, new, "v0.7.0"), run=pip_fails)[0] == "install_failed_rolled_back"
    assert _g(inst, "rev-parse", "HEAD") == before


def test_the_metadata_refresh_is_skipped_without_a_local_setuptools(tmp_path):
    h = _helper()
    calls: list = []

    def no_setuptools(root, *argv, **k):
        calls.append(argv)
        return subprocess.CompletedProcess([], 1 if "import setuptools" in argv else 0, "", "")

    assert h.refresh_metadata(tmp_path, "py", no_setuptools) and not any("pip" in c for c in calls)


def test_a_local_commit_ahead_is_never_merged_over(repos):
    inst, _work, sha = repos
    (inst / "b.txt").write_text("mine", encoding="utf-8")
    _g(inst, "add", ".")
    _g(inst, "-c", "user.email=t@example.org", "-c", "user.name=t", "commit", "-qm", "local work")
    mine = _g(inst, "rev-parse", "HEAD")
    assert _helper().apply(_plan(inst, sha))[0] == "not_a_fast_forward"
    assert _g(inst, "rev-parse", "HEAD") == mine


def test_the_apply_endpoint_names_protected_mode(monkeypatch):
    from fastapi.testclient import TestClient

    import src.safety.shutdown as shutdown
    from src.api.main import app

    started: list = []
    stopped: list = []
    _checked_for_apply(monkeypatch, started)
    _standard_settings(monkeypatch, fetch_mode="protected")
    monkeypatch.setattr(shutdown, "request_shutdown", lambda **k: stopped.append(k) or {})
    r = TestClient(app, base_url="http://127.0.0.1").post("/api/system/update/apply", json={"confirm": True, "ref": "v0.6.0", "sha": SHA_B})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "protected" and started == [] and stopped == []


def test_the_watch_flag_reaches_one_launcher_and_nothing_after_it(tmp_path, monkeypatch):
    import src.paths as paths

    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setenv("OO_UPDATE_WATCH", "1")  # as inherited by an app a watched launcher started
    h = _helper()
    assert "OO_UPDATE_WATCH" not in h.child_env()
    seen: list = []
    h.relaunch(tmp_path, popen=lambda argv, **k: seen.append(k), watched=True)
    h.relaunch(tmp_path, popen=lambda argv, **k: seen.append(k))
    assert seen[0]["env"].get("OO_UPDATE_WATCH") == "1" and "OO_UPDATE_WATCH" not in seen[1]["env"]
    helper_env: list = []
    su.launch_helper("v0.6.0", SHA_B, "tag", root=ROOT, popen=lambda argv, **k: helper_env.append(k["env"]))
    assert "OO_UPDATE_WATCH" not in helper_env[0]


def test_the_windows_launcher_clears_the_watch_flag_and_waits_in_a_frozen_file():
    import hashlib

    cmd = (ROOT / "scripts" / "launch.cmd").read_text(encoding="utf-8")
    # copied to a local and cleared before the server starts, so the server never inherits it
    assert cmd.index('set "OO_UPDATE_WATCH="') < cmd.index("launch_server.ps1\" -App")
    stopped = cmd[cmd.index(":stopped"):]
    assert "pause" not in stopped and "call " not in stopped.lower()  # chained, never called: control never returns to this file
    assert stopped.rstrip().endswith('"%~dp0launch_stopped.cmd"')
    frozen = (ROOT / "scripts" / "launch_stopped.cmd").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "if defined OO_WATCHED exit /b 0" in frozen and frozen.index("OO_WATCHED exit") < frozen.index("pause >nul")
    # FROZEN: a window waits for a key inside this file while an update may rewrite the checkout, and cmd.exe resumes by byte offset.
    # Changing it breaks every launcher window open at the moment of an update; this pin makes that a decision, never an accident.
    assert hashlib.sha256(frozen.encode()).hexdigest() == FROZEN_STOP_SHA256


def test_a_helper_that_fails_unexpectedly_still_brings_the_app_back(tmp_path, monkeypatch):
    h = _helper()
    plan = _plan_file(tmp_path)
    launched: list = []
    monkeypatch.setattr(h, "wait_for_exit", lambda pid, *a, **k: True)
    monkeypatch.setattr(h, "server_answers", lambda port: False)
    monkeypatch.setattr(h, "relaunch", lambda root, **k: launched.append(root))
    monkeypatch.setattr(h, "take_lock", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert h.main(["x", str(plan)]) == 1 and launched == [tmp_path]
    assert _result(tmp_path, h) == "helper_failed"
    (tmp_path / "update-plan.json").write_text("{not json", encoding="utf-8")
    assert h.main(["x", str(tmp_path / "update-plan.json")]) == 1 and len(launched) == 2  # the script's own checkout is started
