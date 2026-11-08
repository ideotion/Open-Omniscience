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


def test_helper_rolls_back_when_the_dependency_install_fails(repos):
    inst, work, _sha = repos
    (work / "requirements.lock").write_text("x", encoding="utf-8")
    _g(work, "add", ".")
    _g(work, "commit", "-qm", "deps")
    _g(work, "tag", "v0.7.0")
    _g(work, "push", "-q", "origin", "main", "--tags")
    new = _g(work, "rev-parse", "HEAD")
    before = _g(inst, "rev-parse", "HEAD")
    h = _helper()
    fail = subprocess.CompletedProcess([], 1, "", "")
    good = subprocess.CompletedProcess([], 0, "", "")
    calls = []

    def first_fails(*a, **k):
        calls.append(a)
        return fail if len(calls) == 1 else good

    status, _ = h.apply(_plan(inst, new, "v0.7.0"), run=first_fails)
    # the checkout is back AND the old lock was installed again (two pip calls after the failed one)
    assert status == "dependencies_failed_rolled_back" and _g(inst, "rev-parse", "HEAD") == before and len(calls) == 3
    status, _ = h.apply(_plan(inst, new, "v0.7.0"), run=lambda *a, **k: fail)
    assert status == "rollback_incomplete" and _g(inst, "rev-parse", "HEAD") == before


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
    monkeypatch.setattr(su, "_helper_running", lambda: False)
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
    monkeypatch.setattr(su, "_helper_running", lambda: True)
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
