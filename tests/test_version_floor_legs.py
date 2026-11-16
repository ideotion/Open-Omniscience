"""The version floors this app names are each backed by something that can fail: a behaviour test, a pinned list of exposed sites, a CI leg.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Why it exists. A floor in ``pyproject.toml`` is a claim about a release ("1.8.0 is the first Starlette that stops a backup when the client
leaves"), and the only thing that kept the claim true was a hand run recorded in a registry entry. This file gives three of those claims
a test of their own (R412, the version-coupling bundle):

* STARLETTE 1.8.0, the behaviour. ``_SnapshotResponse`` (the database backup) is a ``FileResponse``. From 1.8.0 on a FileResponse races its
  file against ``receive()`` and stops at an ``http.disconnect`` when the server speaks an ASGI spec older than 2.4 (uvicorn speaks 2.3);
  1.5.0 to 1.7.0 read the whole snapshot to its end after the client had gone. The test below drives the real class with a client that
  leaves after the first chunk and asserts the rest of the file was not sent. It was run on the 1.7.0 wheel and FAILED there (all of the
  file sent); it is the only thing that ties the floor to its reason.
* STARLETTE 1.8.0, the exposed sites. A test that hands a response an ``http.disconnect`` is a test of what the installed Starlette does with
  it. Every file that names ``http.disconnect`` is listed here, with what it does with it; a new one fails by name until it is listed and
  named in the registry entry ``starlette-gzip-flush``, which is when someone looks at it on the floor release.
* DUCKDB 1.x. The ``columnar`` job installs the newest DuckDB, so the 1.x line that ``duckdb>=1.4`` admits ran in no lane. The same job
  then installs ``duckdb<2`` into a second venv and runs the same files (a job of its own, ``columnar-duckdb1``, until 2026-11-14, PR
  #1988); the checks below fail if it stops pinning the 1.x line, if it stops checking what it got, or if its file list drifts from the
  first environment's.

What it does not see. The behaviour test drives the response class through the ASGI interface, not the whole app with its middleware around it. The exposed-sites list is a grep for the literal ``http.disconnect``: a stub that builds the message type some other
way, or that is written in a helper under another name, is not found. The 1.x environment runs on whatever 1.x release pip resolves, not on the
floor (1.4.0), so a defect that exists only on 1.4 is still unseen; the registry says so.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
import yaml

import src.api.database as dbapi
from src.maintenance import registry as R

_ROOT = Path(__file__).resolve().parents[1]
_CI = _ROOT / ".github" / "workflows" / "ci.yml"
_PYPROJECT = _ROOT / "pyproject.toml"


# ----------------------------------------------------------------------------------- the backup stream
def _backup_stream_sent_before_the_client_left(tmp_path: Path, monkeypatch, spec_version: str) -> tuple[int, int, Path]:
    """Run the real backup response through the ASGI interface; the client leaves when the first body chunk has been sent.

    Returns ``(bytes of the file sent, the file's size, the snapshot directory)``. ``send`` takes a few milliseconds per chunk, as a client
    that reads slower than the disk does, so a response that does not stop is still reading when the disconnect arrives."""
    monkeypatch.setattr(dbapi, "_backup_flight", None)
    workdir = tmp_path / ".oo-backup-floor"
    workdir.mkdir()
    snapshot = workdir / "snapshot.db"
    token = dbapi._claim_backup_slot()
    resp = dbapi._SnapshotResponse(snapshot, workdir, token, media_type="application/x-sqlite3")
    size = int(resp.chunk_size) * 64
    snapshot.write_bytes(b"x" * size)
    # the response stats its file when it is made on some releases and when it is called on others: build it after the file exists
    resp = dbapi._SnapshotResponse(snapshot, workdir, token, media_type="application/x-sqlite3")

    async def run() -> int:
        first_chunk_sent = asyncio.Event()
        sent = 0

        async def receive() -> dict:
            await first_chunk_sent.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            nonlocal sent
            if message["type"] == "http.response.body":
                sent += len(message.get("body", b""))
                first_chunk_sent.set()
                await asyncio.sleep(0.005)

        scope = {
            "type": "http",
            "method": "GET",
            "headers": [],
            "extensions": {},
            "asgi": {"version": "3.0", "spec_version": spec_version},
        }
        await resp(scope, receive, send)
        return sent

    return asyncio.run(run()), size, workdir


def test_a_client_that_leaves_stops_the_backup_stream_on_a_server_older_than_asgi_2_4(tmp_path, monkeypatch):
    """The reason for ``starlette>=1.8.0``. On 1.5.0 to 1.7.0 this response reads the whole snapshot to its end (measured on the 1.7.0 wheel:
    40 MiB sent of 40 MiB, 7.1 s, where 1.8.0 sent 1.1 MiB in 0.3 s), holding the one backup slot and the snapshot's disk space until it
    finishes. uvicorn's HTTP protocols speak spec 2.3, so this is the server the app ships under."""
    sent, size, workdir = _backup_stream_sent_before_the_client_left(tmp_path, monkeypatch, "2.3")
    assert sent < size // 2, (
        f"the backup response sent {sent:,} of {size:,} bytes after the client had gone: this Starlette does not stop a FileResponse "
        "on http.disconnect (the floor in pyproject.toml is 1.8.0 for this, registry entry starlette-gzip-flush)"
    )
    assert not workdir.exists(), "the snapshot directory was not removed when the response ended"
    assert dbapi._backup_flight is None, "the backup slot was not freed when the response ended"


# ------------------------------------------------------------------------------ the sites that name a disconnect
#: Every file that names ``http.disconnect``, with what it does with one. The registry entry ``starlette-gzip-flush`` names the same files.
_DISCONNECT_SITES = {
    "src/monitoring/diagnostics_runs.py": "RecordedFileResponse listens to receive() beside the response, for the one disconnect it must record",
    "tests/test_backup_download_route.py": "_receive_gone hands the backup response an immediate disconnect and asserts only the cleanup, on both spec versions",
    "tests/test_diagnostics_runs.py": "the fake server's receive() waits on an event the test sets, then disconnects: not immediate",
    "tests/test_keyword_export_bounded.py": "two stubs disconnect AT ONCE and assert only that the scratch archive is deleted, so they pass whether the body was sent or not",
    "tests/test_sources_route_and_compression.py": "receive() answers http.request once, then waits for the response to end: not immediate",
}


def _files_naming_http_disconnect() -> set[str]:
    found: set[str] = set()
    for top in ("src", "tests", "scripts"):
        for f in (_ROOT / top).rglob("*.py"):
            if "__pycache__" in f.parts or f.resolve() == Path(__file__).resolve():
                continue
            if "http.disconnect" in f.read_text(encoding="utf-8", errors="replace"):
                found.add(f.relative_to(_ROOT).as_posix())
    return found


def test_every_file_that_names_http_disconnect_is_listed_and_in_the_registry():
    found = _files_naming_http_disconnect()
    assert found == set(_DISCONNECT_SITES), (
        "the files that name http.disconnect changed. New: "
        f"{sorted(found - set(_DISCONNECT_SITES))}; gone: {sorted(set(_DISCONNECT_SITES) - found)}. Starlette 1.8.0 and later race a streamed "
        "FileResponse against receive() and stop at a disconnect when the server speaks ASGI spec < 2.4, so a stub that disconnects at once is a "
        "test of what the installed release does: run the new site on the 1.8.0 wheel (first on PYTHONPATH) and on the newest release, say which "
        "it is in _DISCONNECT_SITES, and name the file in the couplings of registry entry starlette-gzip-flush"
    )
    entry = next(a for a in R.load_registry() if a["id"] == "starlette-gzip-flush")
    couplings = " ".join(str(c) for c in entry["couplings"])
    unnamed = sorted(site for site in _DISCONNECT_SITES if site not in couplings)
    assert not unnamed, f"registry entry starlette-gzip-flush does not name these sites in its couplings: {unnamed}"


# ----------------------------------------------------------------------------------------- the DuckDB 1.x leg
def _jobs() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))["jobs"]


#: The step that starts the columnar job's second environment, the DuckDB 1.x one; every step before it is the newest DuckDB's.
_ONE_X_INSTALL = "Install (core + analysis + dev + columnar), with DuckDB held to the 1.x line"


def _columnar_halves() -> tuple[list[dict], list[dict]]:
    """The ``columnar`` job's steps before the DuckDB 1.x install (the newest DuckDB) and from it on (the 1.x environment)."""
    steps = _jobs()["columnar"]["steps"]
    names = [str(s.get("name") or "") for s in steps]
    assert names.count(_ONE_X_INSTALL) == 1, f"the columnar job must install the DuckDB 1.x environment in one step named {_ONE_X_INSTALL!r}"
    at = names.index(_ONE_X_INSTALL)
    return steps[:at], steps[at:]


def _first_pytest_step_files(steps: list[dict]) -> list[str]:
    """The test files named by the FIRST pytest step of ``steps``, in order, with the line continuations of a ``run: |`` block joined.

    The first pytest step of each environment is the rollup + loader list. The newest environment has a second pytest step (the CI-only
    httpfs round trip) that names one of the same files again; comparing a prefix of all of its files would let a new file appended to its
    first list slip past."""
    for step in steps:
        run = str(step.get("run", ""))
        if "-m pytest" in run:
            return re.findall(r"tests/test_[A-Za-z0-9_]+\.py", run.replace("\\\n", " "))
    return []


def test_the_duckdb_1x_environment_runs_the_files_of_the_newest_one_and_pins_the_1x_line():
    jobs = _jobs()
    assert "columnar" in jobs, "ci.yml lost the columnar job"
    job = jobs["columnar"]
    newest, one_x = _columnar_halves()
    install = " ".join(str(s.get("run", "")) for s in one_x)
    assert '"duckdb<2"' in install and "[analysis,dev,columnar]" in install, "the 1.x environment must install the columnar extra and hold duckdb to <2"
    assert 'python -m venv "$RUNNER_TEMP/duckdb1"' in install, "the 1.x environment must be a venv of its own, not an upgrade of the newest one"
    assert "startswith('1.')" in install, "the 1.x environment must check that it got a 1.x release, or a resolver change would turn it into a second copy of the 2.x run"
    assert job.get("if") in ("github.event_name != 'schedule'", "github.event_name != 'schedule' && needs.changes.outputs.docs_only != 'true'"), (
        "the columnar job must run on every PR but a docs-only one (R462; the skip guard counts only that condition)"
    )
    assert not job.get("continue-on-error"), "the columnar job is a blocking job"
    assert not any(s.get("continue-on-error") or s.get("if") for s in one_x), "the 1.x steps are blocking, unconditional steps"
    pytest_steps = [s for s in one_x if "-m pytest" in str(s.get("run", ""))]
    assert pytest_steps and all('. "$RUNNER_TEMP/duckdb1/bin/activate"' in str(s["run"]) for s in pytest_steps), (
        "every 1.x pytest step must run in the 1.x venv (activated in the step: each step is a new shell)"
    )
    mine = _first_pytest_step_files(one_x)
    theirs = _first_pytest_step_files(newest)
    assert mine, "the 1.x environment names no test files"
    assert len(set(mine)) == len(mine) and len(set(theirs)) == len(theirs), "a file is named twice in one list"
    assert set(mine) == set(theirs), (
        "the DuckDB 1.x environment and the newest one run different files: "
        f"only in 1.x: {sorted(set(mine) - set(theirs))}; only in the newest: {sorted(set(theirs) - set(mine))}"
    )


def test_the_columnar_job_installs_the_newest_duckdb_first_so_the_two_environments_are_two_lines():
    newest, _ = _columnar_halves()
    install = " ".join(str(s.get("run", "")) for s in newest)
    assert "[analysis,dev,columnar]" in install
    assert "duckdb<" not in install and "duckdb==" not in install, (
        "the first environment must resolve the newest duckdb the floor admits; pinning it would leave both environments on the same line"
    )
    assert "activate" not in install, "the first environment is the job's own interpreter, not a venv"


def test_pyproject_still_has_no_duckdb_ceiling_for_the_1x_leg_to_matter():
    """The leg exists because ``duckdb>=1.4`` admits both lines. If a ceiling is ever added the leg becomes the whole story and this should
    be read again, not silently satisfied."""
    text = _PYPROJECT.read_text(encoding="utf-8")
    assert re.search(r'^\s*"duckdb>=1\.4"', text, flags=re.MULTILINE), "pyproject.toml's duckdb requirement changed: read the 1.x leg's reason again"


# ----------------------------------------------------------------------------------- the exact tool pins
@pytest.mark.parametrize("tool", ["ruff", "mypy"])
def test_the_count_ratcheted_dev_tools_are_pinned_to_one_release(tool):
    """A ratchet over a tool's count (scripts/ruff_ratchet.py, the mypy baseline) is a number about ONE release of the tool: the same tree reads
    414 on ruff 0.16.9 and 412 on 0.17.3. A range lets CI and a developer's machine measure different releases, so the pin is exact and a new
    release arrives as a Dependabot PR whose own run re-measures the count."""
    text = _PYPROJECT.read_text(encoding="utf-8")
    pins = re.findall(rf'^\s*"{tool}([<>=!~][^"]*)"', text, flags=re.MULTILINE)
    assert len(pins) == 1, f"pyproject.toml must name {tool} exactly once, found {pins}"
    assert re.fullmatch(r"==[0-9]+(\.[0-9]+)+", pins[0]), f"{tool} must be an exact == pin so its count ratchet is true by construction, found {pins[0]!r}"


# ------------------------------------------------------------------------------------- the urllib3 floor run
def test_the_urllib3_floor_run_installs_the_floor_in_its_own_venv_and_tests_there():
    """The floor run lives in the ``crypto`` job's second environment since PR #1988 (it was the ``urllib3-floor`` job). A pytest step that
    lost its ``activate`` line would run on the job's own interpreter, the newest urllib3, and pass while reading nothing on the floor."""
    entry = next(a for a in R.load_registry() if a["id"] == "urllib3-log-shapes")
    floor = str(entry["pin"]["floor"])
    steps = _jobs()["crypto"]["steps"]
    names = [str(s.get("name") or "") for s in steps]
    install_name = "Install (core + dev), then force the urllib3 floor release"
    assert names.count(install_name) == 1, f"the crypto job must install the urllib3 floor environment in one step named {install_name!r}"
    at = names.index(install_name)
    install = str(steps[at].get("run", ""))
    assert 'python -m venv "$RUNNER_TEMP/urllib3-floor"' in install and '. "$RUNNER_TEMP/urllib3-floor/bin/activate"' in install
    assert f'"urllib3=={floor}"' in install, f"the floor environment must force urllib3 {floor}, the registry's floor"
    tests = [s for s in steps[at + 1:] if "-m pytest" in str(s.get("run", ""))]
    assert tests and all('. "$RUNNER_TEMP/urllib3-floor/bin/activate"' in str(s["run"]) for s in tests), (
        "every pytest step after the floor install must run in the floor venv"
    )
    assert any("tests/test_urllib3_log_withholds_the_path.py" in str(s["run"]) for s in tests), "the floor run must run the log-table test"
    assert not any(s.get("continue-on-error") or s.get("if") for s in steps[at:]), "the floor steps are blocking, unconditional steps"
