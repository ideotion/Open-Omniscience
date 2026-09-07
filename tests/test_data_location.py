"""Choosing where the corpus lives, once, before anything is written.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The dangerous shape here is not a wrong path -- it is a HALF-APPLIED one. ``data_dir()``
re-reads the environment on every call while ``DATABASE_URL``/``engine``/``SessionLocal``
are frozen at module import, so anything that "switches" the data location while the app is
running moves the keys, the custody log and the model store to the new folder and leaves the
corpus in the old one. That is why the offer exists only while the state is ``fresh`` and
why the answer is persist-and-restart. Both of those are pinned below.

The rest is the ordinary honesty discipline: a fact that could not be read is unknown and
never a problem, a concern is stated and never a hard block, and a preflight is a question
rather than something that leaves folders behind.
"""

from __future__ import annotations

import os
import pathlib
import shlex
import stat
from pathlib import Path

import pytest

from src.safety import data_location as dl
from src.safety.data_location import DATA_SUBDIR
from tests.js_source_helper import function_body, read_static, strip_comments


@pytest.fixture()
def env_file(tmp_path, monkeypatch) -> Path:
    """Point oo.env at a scratch file -- the real one is the install tree's."""
    p = tmp_path / "oo.env"
    monkeypatch.setattr(dl, "env_file_path", lambda: p)
    return p


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #
def test_a_usable_folder_names_the_subdir_it_would_create(tmp_path) -> None:
    out = dl.preflight(str(tmp_path))
    assert out["usable"] is True
    assert out["path"] == str(tmp_path / dl.DATA_SUBDIR)
    assert out["subdir"] == "OOS data", "the maintainer named this folder; do not rename it"
    assert out["warnings"] == []


def test_the_preflight_leaves_no_folder_behind(tmp_path) -> None:
    """A question must not have a side effect: an operator told "no" should not then find
    an empty folder sitting in the directory they typed."""
    dl.preflight(str(tmp_path))
    assert not (tmp_path / dl.DATA_SUBDIR).exists()


def test_an_existing_folder_is_not_removed_by_the_probe(tmp_path) -> None:
    """Only a directory the probe itself made is cleaned up -- never the operator's."""
    keep = tmp_path / dl.DATA_SUBDIR
    keep.mkdir()
    (keep / "theirs.txt").write_text("x", encoding="utf-8")
    assert dl.preflight(str(tmp_path))["usable"] is True
    assert (keep / "theirs.txt").exists()


def test_a_relative_path_is_refused(tmp_path) -> None:
    out = dl.preflight("some/where")
    assert out["usable"] is False
    assert out["reason_code"] == "not_absolute" and "absolute" in out["reason"]


def test_an_empty_path_is_refused(tmp_path) -> None:
    assert dl.preflight("   ")["usable"] is False


def test_an_unwritable_folder_is_refused(tmp_path) -> None:
    if os.geteuid() == 0:  # root ignores the mode bits; the check is real for a user
        pytest.skip("running as root: the write permission cannot be withheld")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        out = dl.preflight(str(locked))
        assert out["usable"] is False
        assert out["reason_code"] in ("not_writable", "cannot_create")
    finally:
        locked.chmod(0o700)


def test_a_folder_that_already_holds_a_corpus_warns_and_does_not_block(tmp_path) -> None:
    """A silent adoption would hand the operator someone else's encrypted store and then
    ask them to choose a passphrase for it. Stated, not blocked: it may be their own."""
    existing = tmp_path / dl.DATA_SUBDIR
    existing.mkdir()
    (existing / "open_omniscience.db").write_bytes(b"SQLite format 3\x00")

    out = dl.preflight(str(tmp_path))
    assert out["usable"] is True, "the operator may be pointing at their own corpus"
    assert out["already_has_a_corpus"] is True
    assert [w["code"] for w in out["warnings"]] == ["already_has_a_corpus"]


def test_pointing_at_an_existing_data_folder_warns_that_a_new_one_goes_inside(tmp_path) -> None:
    """The other way an operator arrives here, and the one that reads as data loss.

    They point at a folder that IS a data directory, meaning "use this one". We would
    create ``OOS data`` INSIDE it, so their corpus sits unused one level up and the app
    starts on an empty one -- which looks exactly like it lost the old corpus. Told, not
    blocked: pointing OO_DATA_DIR at the folder itself is how you reuse a corpus, and that
    is a different action from choosing where a new one goes.
    """
    (tmp_path / "open_omniscience.db").write_bytes(b"SQLite format 3\x00")

    out = dl.preflight(str(tmp_path))
    assert out["usable"] is True
    codes = [w["code"] for w in out["warnings"]]
    assert codes == ["parent_is_already_a_corpus"]
    assert out["already_has_a_corpus"] is False, (
        "the corpus is beside the target, not in it -- these are different facts"
    )


def test_the_two_corpus_warnings_are_never_both_claimed(tmp_path) -> None:
    """The negative space of the pair. A corpus in the SUBDIR is the adoption case and says
    so alone; an ordinary empty folder says neither. A preflight that fired both would be
    telling the operator two contradictory things about one folder."""
    inside = tmp_path / "with-subdir"
    (inside / dl.DATA_SUBDIR).mkdir(parents=True)
    (inside / dl.DATA_SUBDIR / "open_omniscience.db").write_bytes(b"x")
    assert [w["code"] for w in dl.preflight(str(inside))["warnings"]] == [
        "already_has_a_corpus"
    ]

    plain = tmp_path / "plain"
    plain.mkdir()
    assert dl.preflight(str(plain))["warnings"] == [], (
        "an ordinary empty folder is the common case and must say nothing"
    )


def test_a_volatile_filesystem_is_a_warning_not_a_refusal(tmp_path, monkeypatch) -> None:
    """The 2026-07-09 field event (a disposable VM vaporised a 60K-article corpus) is the
    reason this is said at all. It is never a hard block -- the project does not do those."""
    monkeypatch.setattr(dl, "_filesystem_type", lambda p: "tmpfs")
    out = dl.preflight(str(tmp_path))
    assert out["usable"] is True
    assert out["filesystem"] == "tmpfs"
    assert [w["code"] for w in out["warnings"]] == ["volatile_filesystem"]


def test_an_unreadable_filesystem_is_unknown_and_not_a_warning(tmp_path, monkeypatch) -> None:
    """"We could not tell" and "this is volatile" are opposite findings."""
    monkeypatch.setattr(dl, "_filesystem_type", lambda p: None)
    out = dl.preflight(str(tmp_path))
    assert out["usable"] is True
    assert out["filesystem"] is None
    assert not any(w["code"] == "volatile_filesystem" for w in out["warnings"])


def test_low_free_space_warns_and_an_unreadable_size_does_not(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(dl, "_free_bytes", lambda p: 1024**3)
    assert any(w["code"] == "low_free_space" for w in dl.preflight(str(tmp_path))["warnings"])

    monkeypatch.setattr(dl, "_free_bytes", lambda p: None)
    out = dl.preflight(str(tmp_path))
    assert out["free_bytes"] is None
    assert not any(w["code"] == "low_free_space" for w in out["warnings"]), (
        "an unmeasured size must never render as a shortage"
    )


# --------------------------------------------------------------------------- #
# Persisting the choice
# --------------------------------------------------------------------------- #
def test_persist_writes_the_line_launch_sh_sources(tmp_path, env_file) -> None:
    out = dl.persist(str(tmp_path))
    assert out["saved"] is True and out["restart_required"] is True

    body = env_file.read_text(encoding="utf-8")
    assert body.endswith("\n"), "a shell env file without a trailing newline is a trap"
    lines = [ln for ln in body.splitlines() if ln.startswith("export OO_DATA_DIR=")]
    assert len(lines) == 1, body
    # launch.sh does `. oo.env`, so the value must survive the shell, spaces and all --
    # and the subfolder the maintainer named HAS a space in it.
    assert shlex.split(lines[0].removeprefix("export "))[0] == (
        f"OO_DATA_DIR={tmp_path / dl.DATA_SUBDIR}"
    )
    assert (tmp_path / dl.DATA_SUBDIR).is_dir(), "the folder is created when the choice is kept"


def test_persist_replaces_rather_than_appends(tmp_path, env_file) -> None:
    """launch.sh sources the file, so a second line for the same variable silently wins
    over the first -- an append would leave the app using a location nobody chose."""
    env_file.write_text(
        "export OO_PORT=8123\nexport OO_DATA_DIR=/old/place\n", encoding="utf-8"
    )
    dl.persist(str(tmp_path))
    body = env_file.read_text(encoding="utf-8")
    assert body.count("export OO_DATA_DIR=") == 1
    assert "/old/place" not in body
    assert "export OO_PORT=8123" in body, "an unrelated setting must survive"


def test_persist_is_idempotent(tmp_path, env_file) -> None:
    dl.persist(str(tmp_path))
    first = env_file.read_text(encoding="utf-8")
    dl.persist(str(tmp_path))
    assert env_file.read_text(encoding="utf-8") == first


def test_the_env_file_is_owner_only(tmp_path, env_file) -> None:
    """It sits in the install tree and names where the corpus and its keys live.

    NOT root-skipped, deliberately. A first draft was, by analogy with the unwritable-folder
    test above -- but those are different claims: root ignores mode bits when it WRITES,
    while the mode a file CARRIES is set and read back the same as any user. The skip made
    a real assertion unreachable in every root sandbox, which a mutation matrix found by
    surviving.
    """
    dl.persist(str(tmp_path))
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_a_refused_folder_is_never_written(tmp_path, env_file) -> None:
    out = dl.persist("relative/path")
    assert out["saved"] is False
    assert not env_file.exists(), "a refusal must not leave a half-applied choice"


def test_a_previous_choice_survives_a_failed_write(tmp_path, env_file, monkeypatch) -> None:
    """Atomic replace: a crash mid-write must leave the old choice intact rather than a
    truncated env file the next launch sources into a broken shell."""
    env_file.write_text("export OO_DATA_DIR=/kept\n", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(dl.os, "replace", boom)
    out = dl.persist(str(tmp_path))
    assert out["saved"] is False
    assert env_file.read_text(encoding="utf-8") == "export OO_DATA_DIR=/kept\n"
    leftovers = list(env_file.parent.glob(".oo-env-*"))
    assert leftovers == [], f"the temp file was orphaned: {leftovers}"


def test_the_env_file_lives_at_the_install_root() -> None:
    """Derived from the source tree, not the working directory: the app is launched from
    the launcher, from systemd and from a test runner, and only the tree is the same."""
    root = Path(__file__).resolve().parents[1]
    assert dl.env_file_path() == root / "oo.env"
    assert (root / "scripts" / "launch.sh").exists(), (
        "oo.env is only meaningful because launch.sh sources it"
    )
    assert "oo.env" in (root / "scripts" / "launch.sh").read_text(encoding="utf-8")


def test_every_warning_and_refusal_is_machine_readable(tmp_path, monkeypatch) -> None:
    """The first-launch page has to say these in twelve languages, and a sentence with a
    path or a number interpolated into it can never be a translation key. So each carries a
    ``code`` the page maps onto its own keyed template -- and the module's English ``text``
    stays for the readers that are not the page (the API, a log line, a diagnostic)."""
    monkeypatch.setattr(dl, "_filesystem_type", lambda p: "tmpfs")
    monkeypatch.setattr(dl, "_free_bytes", lambda p: 1024**3)
    (tmp_path / dl.DATA_SUBDIR).mkdir()
    (tmp_path / dl.DATA_SUBDIR / "open_omniscience.db").write_bytes(b"x")

    out = dl.preflight(str(tmp_path))
    codes = {w["code"] for w in out["warnings"]}
    assert codes == {"already_has_a_corpus", "volatile_filesystem", "low_free_space"}
    for w in out["warnings"]:
        assert w["text"].strip(), "the English rendering stays for non-UI readers"
    low = next(w for w in out["warnings"] if w["code"] == "low_free_space")
    assert low["free_gb"] == 1, "the VALUE travels as data, not baked into a sentence"

    for bad, code in (("", "empty"), ("rel/ative", "not_absolute")):
        assert dl.preflight(bad)["reason_code"] == code


# --------------------------------------------------------------------------- #
# The endpoints: the refusal is the data-safety half
# --------------------------------------------------------------------------- #
def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api.unlock import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_the_choice_is_offered_only_while_nothing_has_been_written(monkeypatch, tmp_path):
    """`fresh` is not a convenience gate. `data_dir()` re-reads the environment on every
    call while `DATABASE_URL`/`engine`/`SessionLocal` freeze at import, so a switch made
    after a store exists moves the keys, the custody log and the model store to the new
    folder and leaves the corpus in the old one -- and the next start follows the
    environment to the new, empty folder and reports `fresh`, with the corpus orphaned."""
    import src.api.unlock as unlock_mod

    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "fresh")
    body = _client().get("/api/system/data-location").json()
    assert body["offerable"] is True
    assert body["why_not_offerable"] is None
    assert body["subdir"] == DATA_SUBDIR

    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "locked")
    body = _client().get("/api/system/data-location").json()
    assert body["offerable"] is False
    assert "already exists" in body["why_not_offerable"]
    # ...and it says where the honest path is, rather than nothing.
    assert "copy" in body["why_not_offerable"].lower()


def test_both_write_paths_refuse_once_a_corpus_exists(monkeypatch, tmp_path, env_file):
    """The twin of the flag: a UI that ignored `offerable` must still be refused, and the
    PROBE is gated too -- an ungated one would let anything reaching loopback create
    directories by asking questions.

    It takes `env_file` even though a passing run never writes one, and that is the point:
    the mutation matrix removes this very gate, and without the fixture the mutant wrote a
    real `oo.env` into the repository root -- caught here as an untracked file. A test that
    asserts a side effect does NOT happen must still sandbox it, or proving the guard is
    load-bearing damages the tree."""
    import src.api.unlock as unlock_mod

    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked")
    c = _client()
    target = str(tmp_path / "elsewhere")
    assert c.post("/api/system/data-location/check", json={"path": target}).status_code == 409
    assert c.post("/api/system/data-location", json={"path": target}).status_code == 409
    assert not (tmp_path / "elsewhere").exists(), "a refused probe creates nothing"


def test_a_fresh_instance_can_record_a_choice_and_it_lands_in_oo_env(monkeypatch, tmp_path):
    """The positive twin: the refusals above are only honest if the accepted path works.
    What is asserted is the OUTCOME an operator gets -- a real `export OO_DATA_DIR=` line
    naming the `OOS data` subfolder -- not that the call returned 200."""
    import src.api.unlock as unlock_mod
    import src.safety.data_location as dl

    env = tmp_path / "install" / "oo.env"
    env.parent.mkdir(parents=True)
    monkeypatch.setattr(dl, "env_file_path", lambda: env)
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "fresh")

    drive = tmp_path / "drive"
    drive.mkdir()
    c = _client()

    probe = c.post("/api/system/data-location/check", json={"path": str(drive)}).json()
    assert probe["usable"] is True
    assert probe["path"].endswith(DATA_SUBDIR)

    out = c.post("/api/system/data-location", json={"path": str(drive)})
    assert out.status_code == 200 and out.json()["saved"] is True
    line = env.read_text(encoding="utf-8")
    assert line.startswith("export OO_DATA_DIR=")
    assert DATA_SUBDIR in line
    # And the folder it named is the one that exists, so the next launch finds it.
    assert (drive / DATA_SUBDIR).is_dir()


def test_an_unusable_folder_is_a_400_and_changes_nothing(monkeypatch, tmp_path):
    """A refusal must leave the previous choice standing: the operator's env file is the
    only record of it, and a half-written one is worse than no button."""
    import src.api.unlock as unlock_mod
    import src.safety.data_location as dl

    env = tmp_path / "oo.env"
    env.write_text('export OO_DATA_DIR="/previous/choice"\n', encoding="utf-8")
    monkeypatch.setattr(dl, "env_file_path", lambda: env)
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "fresh")

    r = _client().post("/api/system/data-location", json={"path": "relative/path"})
    assert r.status_code == 400
    assert env.read_text(encoding="utf-8") == 'export OO_DATA_DIR="/previous/choice"\n'


# --------------------------------------------------------------------------- #
# The first-launch step itself
# --------------------------------------------------------------------------- #
def _unlock_script() -> str:
    """The inline script of the first-launch page, comment-stripped.

    Comment-stripped because every assertion below about what the page must NOT do sits
    next to a comment EXPLAINING it, and those comments necessarily quote the thing being
    forbidden -- the recorded trap where a negative guard passes (or fails) on its own
    rationale. Bodies are then taken with the shared slicer rather than a guessed
    delimiter, so this file adds no hand-rolled slice of its own."""
    import re

    html = read_static("unlock.html")
    js = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    return strip_comments(js)


def test_the_step_sits_between_the_legal_accept_and_the_passphrase() -> None:
    """The ORDER is the maintainer's ask and it is also the safety property: after the
    language and legal steps, before anything is written. A step placed after the
    passphrase would be offering a choice about a folder that already holds a corpus."""
    js = _unlock_script()
    # The accept handler is a branch inside the page's one delegated click listener, so
    # it is bounded by the NEXT branch's own guard -- a landmark that provably occurs
    # (asserted) rather than a guessed delimiter.
    assert 'if (id === "lg-decline")' in js
    accept = js.split('if (id === "lg-accept")', 1)[1].split('if (id === "lg-decline")', 1)[0]
    assert "legalToDataLocation()" in accept
    assert "legalToPassphrase()" not in accept, "the accept must no longer jump the step"

    step = function_body(js, "legalToDataLocation")
    assert '$("view-legal").classList.add("hidden")' in step
    assert '$("view-datadir").classList.remove("hidden")' in step


def test_the_step_is_skipped_when_the_backend_says_it_is_not_offerable() -> None:
    """A control that cannot be honoured is worse than no control. `offerable` is false
    for any state but `fresh` -- and the page must then go straight on, not show a
    disabled folder picker."""
    step = function_body(_unlock_script(), "legalToDataLocation")
    assert "!info.offerable" in step
    assert "legalToPassphrase(); return;" in step


def test_a_chosen_folder_ends_the_flow_instead_of_creating_a_corpus_here() -> None:
    """THE defect this whole step exists to prevent, asserted at the one place it could
    still happen. `OO_DATA_DIR` is read by the launcher, so a folder recorded now takes
    effect at the NEXT start: going on to create a corpus in THIS process would put it in
    the OLD folder while the recorded choice pointed elsewhere -- the orphaning the
    backend refuses after the fact and cannot undo."""
    cont = function_body(_unlock_script(), "dlContinue")
    # The default folder continues to the passphrase...
    assert 'if (!$("dl-custom").checked) { dlToPassphrase(); return; }' in cont
    # ...and the custom one does NOT: it hands over to the restart notice.
    after = cont.split('if (!$("dl-custom").checked) { dlToPassphrase(); return; }', 1)[1]
    assert "dlRestartRequired(" in after
    assert "dlToPassphrase" not in after, "a recorded folder must not continue in this process"


def test_the_restart_notice_says_nothing_was_created() -> None:
    """An operator who is told only "saved" will reasonably keep going. The notice has to
    carry the two facts that make the next action obvious: nothing exists yet, and the
    folder applies at the next start."""
    notice = function_body(_unlock_script(), "dlRestartRequired")
    assert "Nothing has been created yet" in notice
    assert "next time it starts" in notice
    assert 'b.id = "dl-stop"' in notice


def test_every_rendered_string_of_the_step_has_a_key_in_all_twelve_locales() -> None:
    """This page is where informed consent begins, so its strings ship x12 -- and the two
    ratchets cannot see them all: `--max-untranslatable` reads the MARKUP of unlock.html
    while `--max-unkeyed-t-calls` reads the app modules and reader.js, so a `t()` literal
    inside this page's inline script is invisible to both. Asserted here instead."""
    import json as _json
    import re

    js = _unlock_script()
    body = "\n".join(
        function_body(js, name)
        for name in ("dlWarningText", "dlRefusalText", "dlCheck", "dlRestartRequired")
    )
    # The boundary is load-bearing: a bare `t\(` also matches the tail of
    # `createElement("button")`, which harvested "button" as a chrome string.
    literals = sorted(
        {m.group(1) for m in re.finditer(r'(?<![A-Za-z0-9_$.])t\("([^"]{3,})"\)', body)}
    )
    assert len(literals) >= 12, f"the harvest found too few strings: {literals}"

    locdir = pathlib.Path("src/static/locales")
    for f in sorted(locdir.glob("*.json")):
        if f.stem == "_meta":
            continue
        catalog = _json.loads(f.read_text(encoding="utf-8"))
        missing = [s for s in literals if s not in catalog]
        assert not missing, f"{f.stem}: {missing}"
