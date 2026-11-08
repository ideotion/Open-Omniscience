"""In-app "check for update / update": find a newer published version and hand the swap to a helper that runs after the app has stopped.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHAT INSTALL TYPES EXIST. ``scripts/bootstrap.sh`` and ``install.ps1`` clone the repository and ``pip install -e`` it, so every supported install is a
GIT CHECKOUT that runs from its own tree. That is the one install type an in-place update is built for. Anything else (a copied tree with no ``.git``, a
checkout whose ``origin`` is not this repository, a dirty tree, a branch other than ``main``, a detached head) is reported as NOT updatable here, with the
manual steps spelled out, so the button never guesses.

WHAT "NEWER" MEANS. The highest ``vX.Y.Z`` tag the repository publishes, when it is above the running version; tags are the maintainer's releases
(each is a GitHub pre-release today, so the release API's "latest" would answer nothing). Only a repository with NO such tag falls back to the tip of
``main``, and the answer says so (``kind: "main"``). The check never moves backwards: a running version at or above the newest tag is "up to date".

THE NETWORK. The CHECK is the one in-process fetch: one ``GET`` on ``api.github.com`` through :func:`src.safety.fetcher.guarded_session`, so the kill
switch (airplane mode), the protected-mode proxy and the host list all apply, and the UI asks the ONE consent popup first. The ``git fetch`` of the update
itself runs in :mod:`scripts.apply_update`, a separate process that starts only after this app has exited cleanly (the database and WAL closed through
the ordinary shutdown path). Neither the socket guard nor the proxy reaches that process, so the apply is REFUSED before anything stops while airplane
mode is on or protected mode is chosen (:func:`refuse_offline_or_protected`), the UI asks the consent popup first, and the helper is started without
the passphrase variables.

NEVER UNVERIFIED CODE, NEVER WITHOUT A CLICK. Applying needs ``confirm: true`` AND the exact ``ref``/``sha`` of a check this process made in the last hour,
so a request cannot name a ref of its own. The helper re-verifies after fetching: the fetched commit must be byte-for-byte the ``sha`` the check read, the
``origin`` URL must be this repository over https, the tree must be clean, and the swap is a fast-forward of ``main`` only (``git merge --ff-only``), which
cannot discard a local commit. Tags are not signature-verified (the project publishes no signing key): the check is "the commit GitHub named is the commit
fetched, from the pinned origin", stated as such in the SECURITY document rather than dressed up as more.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess  # noqa: S404 - fixed argv, no shell
import sys
import threading
import time
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("maintenance.self_update")

REPO = "ideotion/Open-Omniscience"
REPO_URL_HTTPS = f"https://github.com/{REPO}"
#: The two endpoints the check reads, and the one host its session may talk to (``guarded_session(allowed_hosts=...)``): a redirect anywhere else is
#: refused, not followed.
TAGS_URL = f"https://api.github.com/repos/{REPO}/tags?per_page=100"
MAIN_URL = f"https://api.github.com/repos/{REPO}/commits/main"
GITHUB_API_HOSTS = ("api.github.com",)

TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
#: How long a check stays good for an apply, seconds.
CHECK_TTL_S = 3600
_MAX_BODY = 2_000_000

RESULT_FILE = "update-result.json"
PLAN_FILE = "update-plan.json"

_LAST_CHECK: dict[str, Any] = {}


class UpdateError(Exception):
    """A refusal or failure with a fixed, address-free sentence (``str(exc)``) safe to show."""


class AirplaneRefused(UpdateError):
    """The apply was refused because airplane mode is on (the endpoint names it with ``code: "airplane"``)."""


class ProtectedRefused(UpdateError):
    """The apply was refused because protected mode is chosen (``code: "protected"``)."""


def current_version() -> str:
    try:
        return _pkg_version("open-omniscience")
    except PackageNotFoundError:
        return "0.0.0"


def _vtuple(text: str) -> tuple[int, ...] | None:
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", text.strip())
    return tuple(int(g) for g in m.groups()) if m else None


def pick_newest_tag(tags: Any) -> tuple[str, str] | None:
    """The ``(tag, commit sha)`` of the highest ``vX.Y.Z`` in a GitHub tags answer, or None. Malformed rows are skipped, never trusted."""
    best: tuple[tuple[int, ...], str, str] | None = None
    if not isinstance(tags, list):
        return None
    for row in tags:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        commit = row.get("commit")
        sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(name, str) or not isinstance(sha, str):
            continue
        m = TAG_RE.match(name)
        if not m or not SHA_RE.match(sha):
            continue
        key = tuple(int(g) for g in m.groups())
        if best is None or key > best[0]:
            best = (key, name, sha)
    return (best[1], best[2]) if best else None


# --- the install we are running from ---------------------------------------- #


def _env_without_passphrases() -> dict[str, str]:
    from src.llm.model_store import child_env

    return child_env()


def _git(root: Path, *args: str, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env={**_env_without_passphrases(), "GIT_TERMINAL_PROMPT": "0"},
    )


def _origin_ok(url: str) -> bool:
    return url.strip().removesuffix(".git").lower() == REPO_URL_HTTPS.lower()


def install_status(root: Path | None = None) -> dict[str, Any]:
    """What kind of install this is and whether an in-place update can run: ``{kind, can_apply, reason, manual_steps}``. Local reads only."""
    from src.paths import repo_root

    root = root or repo_root()
    manual = [
        f"git clone {REPO_URL_HTTPS}.git   (or open your install folder)",
        "git checkout main && git pull --ff-only",
        "re-run ./install.sh (Windows: install.ps1) so dependencies match, then start the app again",
    ]
    out: dict[str, Any] = {"kind": "other", "can_apply": False, "reason": "", "manual_steps": manual, "root": None}
    if not (root / ".git").exists():
        out["reason"] = "not_a_git_checkout"
        return out
    try:
        origin = _git(root, "config", "--get", "remote.origin.url")
        branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
        dirty = _git(root, "status", "--porcelain")
    except (OSError, subprocess.SubprocessError):
        out["reason"] = "git_unavailable"
        return out
    out["kind"] = "git"
    if origin.returncode != 0 or not _origin_ok(origin.stdout):
        out["reason"] = "origin_not_this_repository"
    elif branch.returncode != 0 or branch.stdout.strip() != "main":
        out["reason"] = "not_on_main"
    elif dirty.returncode != 0 or dirty.stdout.strip():
        out["reason"] = "local_changes"
    else:
        out["can_apply"] = True
    return out


# --- the check (the one in-process fetch) ------------------------------------ #


def _get_json(url: str) -> Any:
    from src.safety.fetcher import (
        FETCH_FAILURES,
        RedirectRefused,
        TransportUnavailable,
        failure_words,
        guarded_session,
    )

    session = guarded_session(isolation_token=url, allowed_hosts=GITHUB_API_HOSTS)
    refused = False
    failure: str | None = None
    body: Any = None
    try:
        resp = session.get(url, timeout=20, headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        if len(resp.content) > _MAX_BODY:
            raise ValueError("too large")
        try:
            body = resp.json()
        except RecursionError:
            raise ValueError("nested") from None
    except RedirectRefused:
        refused = True
    except TransportUnavailable:
        raise
    except FETCH_FAILURES as exc:
        failure = failure_words(exc)
    if refused:
        raise UpdateError("The update check was refused: GitHub answered with an address off api.github.com.")
    if failure is not None:
        _LOG.warning("update check failed (%s)", failure)
        raise UpdateError(f"The update check failed ({failure}).")
    return body


#: GitHub lists tags by NAME, not by version, 100 to a page: every page is read (up to this many), so a ``v0.10.0`` on page two is never missed.
_TAG_PAGES_MAX = 10


def _all_tags(fetch: Any) -> Any:
    """Every tag row, page after page until a short page (``TAGS_URL`` itself is page one). A page that is not a list ends the walk; when the
    FIRST one is not, that answer goes to :func:`pick_newest_tag` unchanged (which reads it as no tags)."""
    rows: list[Any] = []
    for page in range(1, _TAG_PAGES_MAX + 1):
        body = fetch(TAGS_URL if page == 1 else f"{TAGS_URL}&page={page}")
        if not isinstance(body, list):
            return body if page == 1 else rows
        rows.extend(body)
        if len(body) < 100:
            break
    return rows


def check(get_json: Any = None, *, root: Path | None = None, now: float | None = None) -> dict[str, Any]:
    """Ask GitHub what is newest and compare it to the running version. Raises :class:`UpdateError` (fixed words) on a refusal or failure and
    ``NetworkBlocked`` while airplane mode is engaged (the caller names that one). Remembers the answer for :func:`validate_apply`."""
    fetch = get_json or _get_json
    cur = current_version()
    cur_t = _vtuple(cur) or (0, 0, 0)
    newest = pick_newest_tag(_all_tags(fetch))
    kind = "tag"
    if newest is None:
        kind = "main"
        row = fetch(MAIN_URL)
        sha = row.get("sha") if isinstance(row, dict) else None
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            raise UpdateError("The update check could not read a version from GitHub.")
        newest = ("main", sha)
    ref, sha = newest
    if kind == "tag":
        latest_t = _vtuple(ref) or (0, 0, 0)
        # The installed metadata can lag the checkout (a tag cut before its version flip, a pull without a reinstall): the commit we run being
        # the tag's commit is "up to date" whatever the metadata says.
        available = latest_t > cur_t and not _checkout_contains(root, sha)
        latest = ref.lstrip("v")
    else:
        # No release tag exists: main's tip is only "newer" when it is not the commit we run. Without a readable local head, say so.
        head = _local_head(root)
        available = bool(head) and head != sha
        latest = sha[:9]
    status = install_status(root)
    result = {
        "current": cur,
        "latest": latest,
        "update_available": bool(available),
        "kind": kind,
        "ref": ref,
        "sha": sha,
        "checked_at": now if now is not None else time.time(),
        "install": {k: status[k] for k in ("kind", "can_apply", "reason", "manual_steps")},
    }
    _LAST_CHECK.clear()
    _LAST_CHECK.update(result)
    return result


def _checkout_contains(root: Path | None, sha: str) -> bool:
    """True when the commit we run IS ``sha`` or descends from it (a checkout ahead of the tag). A commit not present locally is not contained."""
    from src.paths import repo_root

    if _local_head(root) == sha:
        return True
    try:
        return _git(root or repo_root(), "merge-base", "--is-ancestor", sha, "HEAD").returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _local_head(root: Path | None) -> str:
    from src.paths import repo_root

    try:
        p = _git(root or repo_root(), "rev-parse", "HEAD")
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


# --- the apply ---------------------------------------------------------------- #


_APPLY_LOCK = threading.Lock()
#: When this process last started a helper (monotonic seconds), or None. A second apply is refused until the helper's own wait for this
#: process could have run out, so a shutdown that hung does not refuse updates for the rest of the process's life.
_APPLYING: float | None = None
_APPLY_HOLD_S = 1900


def begin_apply(ref: str, sha: str, *, now: float | None = None, root: Path | None = None, popen: Any = None) -> dict[str, Any]:
    """Validate, then start the helper, ONCE: a second click or a second tab while one apply is under way is refused, and the check it used is
    spent, so the same answer cannot start a second helper either."""
    global _APPLYING
    with _APPLY_LOCK:
        if _APPLYING is not None and time.monotonic() - _APPLYING < _APPLY_HOLD_S:
            raise UpdateError("An update is already starting.")
        refuse_offline_or_protected()
        checked = validate_apply(ref, sha, now=now, root=root)
        if _helper_running(root):
            raise UpdateError("An earlier update is still being applied; try again later.")
        launch_helper(checked["ref"], checked["sha"], checked["kind"], root=root, popen=popen)
        _APPLYING = time.monotonic()
        _LAST_CHECK.clear()
        return checked


#: The two refusals ``refuse_offline_or_protected`` raises, kept as constants so the endpoint test and the UI read the same words.
AIRPLANE_REFUSAL = "Airplane mode is on: the update did not start. Go online first (the update downloads from GitHub and PyPI)."
PROTECTED_REFUSAL = (
    "Protected mode is on: the update did not start. It would download from GitHub and PyPI over a direct connection, not through your "
    "proxy, which would reveal this machine's address. Switch to standard mode to update, or update by hand through your proxy."
)


def protected_mode_chosen() -> bool:
    """True when protected mode is chosen, or the settings cannot be read (the app's own rule, R117: then it is protected)."""
    try:
        from src.safety.settings import load_settings

        st = load_settings()
        return bool(st.is_protected or st.read_failed)
    except Exception:  # noqa: BLE001 - unreadable settings: protected, never assume a direct connection is allowed
        return True


def refuse_offline_or_protected() -> None:
    """Refuse an apply while airplane mode is on or protected mode is chosen. The helper's ``git fetch`` and ``pip install`` run in a separate
    process after this app has exited, where neither the socket guard nor the proxy settings reach, so the gate has to be HERE, before anything
    stops: an apply in airplane mode would egress while the app shows offline, and one in protected mode would silently drop the proxy (a
    deanonymisation, never a retry). Settings that cannot be read count as protected (the app's own rule, R117)."""
    from src.ingest import kill_switch_active

    if kill_switch_active():
        raise AirplaneRefused(AIRPLANE_REFUSAL)
    if protected_mode_chosen():
        raise ProtectedRefused(PROTECTED_REFUSAL)


def _lock_reading(lock: Path) -> tuple[int, int, float] | None:
    """``(app pid, helper pid, mtime)`` of the helper's lock file, or None when it cannot be read (same format as ``scripts/apply_update.py``)."""
    try:
        app, helper = (int(x) for x in lock.read_text(encoding="utf-8").split())
        return (app, helper, lock.stat().st_mtime)
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        import psutil

        return bool(psutil.pid_exists(pid))
    except ImportError:
        pass
    if os.name == "nt":
        return True  # cannot tell without psutil: count it as running, so the click is refused rather than racing a live helper
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


#: Same as ``scripts/apply_update.py:LOCK_STALE_S`` (a test pins the two equal).
LOCK_STALE_S = 8 * 3600


def _helper_running(root: Path | None = None, *, alive: Any = None, now: Any = None) -> bool:
    """True while an update helper holds a fresh lock and is still running (checked BEFORE this app stops, so it is never stopped for an
    update that would then wait behind another). Read here, in-process, with the helper's own rule (fresh and its helper alive); the script is
    never imported into the server. A lock that cannot be read is no holder: the helper's own exclusive lock still refuses a duplicate."""
    from src.paths import data_dir

    del root  # the lock lives in the data directory whatever the checkout
    reading = _lock_reading(data_dir() / "update.lock")
    if reading is None:
        return False
    _app, helper, mtime = reading
    t = (now or time.time)()
    return bool(helper) and helper != os.getpid() and t - mtime < LOCK_STALE_S and (alive or _pid_alive)(helper)


def validate_apply(ref: str, sha: str, *, now: float | None = None, root: Path | None = None) -> dict[str, Any]:
    """Refuse unless ``ref``/``sha`` are exactly what this process's last check read, recently, and this install can be updated in place."""
    last = dict(_LAST_CHECK)
    t = now if now is not None else time.time()
    if not last or not last.get("update_available"):
        raise UpdateError("Check for an update first.")
    if t - float(last.get("checked_at", 0)) > CHECK_TTL_S:
        raise UpdateError("That check is more than an hour old: check again.")
    if ref != last["ref"] or sha != last["sha"] or not SHA_RE.match(sha):
        raise UpdateError("The version to install is not the one that was checked: check again.")
    if last["kind"] == "tag" and not TAG_RE.match(ref):
        raise UpdateError("The version to install is not a release tag.")
    st = install_status(root)
    if not st["can_apply"]:
        raise UpdateError(f"This install cannot be updated in place ({st['reason']}); the steps are shown instead.")
    return last


def launch_helper(ref: str, sha: str, kind: str, *, root: Path | None = None, popen: Any = None) -> None:
    """Start :mod:`scripts.apply_update` detached, naming this process so it waits for it to exit. It does nothing until then."""
    from src.paths import data_dir, repo_root

    root = root or repo_root()
    script = root / "scripts" / "apply_update.py"
    if not script.is_file():
        raise UpdateError("The updater script is missing from this install.")
    plan = {"ref": ref, "sha": sha, "kind": kind, "pid": os.getpid(), "root": str(root), "python": sys.executable, "port": os.environ.get("OO_PORT", "8000")}
    plan_path = data_dir() / PLAN_FILE
    from src.safety.file_lock import atomic_replace

    atomic_replace(plan_path, json.dumps(plan))
    argv = [sys.executable, "-I", str(script), str(plan_path)]
    spawn = popen or subprocess.Popen
    quiet = subprocess.DEVNULL
    # WITHOUT the passphrases: the helper runs git, pip and the fetched release's build step, none of which may hold the key that opens the
    # corpus (the passphrase rule). The app it starts again opens locked, as any start without OO_DB_PASSPHRASE does.
    from src.llm.model_store import child_env

    env = child_env()
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        try:  # break away from a job object that would kill the helper together with this process; not every job allows it
            spawn(argv, stdin=quiet, stdout=quiet, stderr=quiet, cwd=str(root), env=env, creationflags=flags | 0x01000000)  # noqa: S603 - fixed argv
        except OSError:
            spawn(argv, stdin=quiet, stdout=quiet, stderr=quiet, cwd=str(root), env=env, creationflags=flags)  # noqa: S603 - fixed argv, no shell
    else:
        spawn(argv, stdin=quiet, stdout=quiet, stderr=quiet, cwd=str(root), env=env, start_new_session=True)  # noqa: S603 - fixed argv, no shell


def last_result() -> dict[str, Any] | None:
    """What the helper recorded about the last attempt (read once after a restart), or None."""
    from src.paths import data_dir

    p = data_dir() / RESULT_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
