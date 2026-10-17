"""External-artifact registry: protocol guard + freshness + compatibility couplings.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The single gate that replaces the scattered per-file freshness tests:
  * PROTOCOL GUARD — every ``*_AS_OF`` constant in the tree is registered (you cannot
    ship a dated artifact unwatched);
  * FRESHNESS — nothing is past its declared window;
  * COMPATIBILITY — the version COUPLINGS hold (DuckDB floor ↔ pyproject ↔ installed;
    the bundled data is parseable at its declared vintage).
"""

from __future__ import annotations

import re

from src.maintenance import registry as R

_ROOT = R.repo_root()


def _scan_as_of_constants() -> set[tuple[str, str]]:
    """Every module-level ``*_AS_OF = "..."`` (Python) / ``*_AS_OF="..."`` (shell) in the
    tree — the things that MUST be registered."""
    found: set[tuple[str, str]] = set()
    files = list((_ROOT / "src").rglob("*.py")) + [_ROOT / "install.sh"]
    for f in files:
        if not f.exists() or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(_ROOT).as_posix()
        for m in re.finditer(r'^([A-Z][A-Z0-9_]*_AS_OF)\s*(?::[^=]*)?=\s*["\']', f.read_text(
            encoding="utf-8"
        ), re.M):
            found.add((rel, m.group(1)))
    return found


def test_every_as_of_constant_is_registered():
    """THE PROTOCOL, mechanised: a new dated artifact cannot ship without a registry entry."""
    in_code = _scan_as_of_constants()
    registered = R.registered_pins()
    missing = in_code - registered
    assert not missing, (
        "these *_AS_OF constants are NOT in configs/external_artifacts.yml "
        f"(add an entry in the same commit): {sorted(missing)}"
    )


def test_registered_pins_resolve_to_a_value():
    for file_rel, const in R.registered_pins():
        assert R.read_const(file_rel, const), f"registry pin {file_rel}:{const} did not resolve"


def test_nothing_is_stale():
    """Consolidated freshness — fails when any artifact is past its window OR a coupling
    breaks (replaces the scattered per-file freshness tests)."""
    stale = R.summary()["stale"]
    assert not stale, f"stale external artifacts (refresh them): {stale}"


def test_reviewed_through_is_only_available_to_on_security_entries():
    """`reviewed_through` silences the upstream watch until the NEXT release, which is the
    right behaviour for an `on-security` artifact (lagging upstream is its normal, correct
    state) and the WRONG behaviour for every other policy, where being behind is real work
    somebody owes. Without this guard the field is a universal mute button: any entry could
    go quiet by declaring itself reviewed, and the watch would stop being a watch.

    A `track-duckdb-version` entry moves its `current` when the coupling is actually
    re-verified — a different motion, deliberately not automatable away.
    """
    offenders = []
    for a in R.load_registry():
        uc = a.get("upstream_check") or {}
        if not str(uc.get("reviewed_through") or "").strip():
            continue
        policy = (a.get("freshness") or {}).get("policy")
        if policy != "on-security":
            offenders.append(f"{a['id']} (policy={policy!r})")
    assert not offenders, (
        "reviewed_through is only meaningful under freshness.policy == 'on-security'; "
        f"remove it from: {offenders}"
    )


def test_reviewed_through_never_understates_what_we_ship():
    """A review baseline must be at or ahead of the shipped version. `reviewed_through`
    BEHIND `current` would be incoherent (we shipped something nobody cleared) and would
    also silently re-flag forever, which is the noise this field exists to remove."""
    for a in R.load_registry():
        uc = a.get("upstream_check") or {}
        reviewed = str(uc.get("reviewed_through") or "").strip()
        current = str(uc.get("current") or "").strip()
        if not reviewed or not current:
            continue
        norm = lambda t: tuple(  # noqa: E731 - local, single use
            int(p) if p.isdigit() else p for p in re.split(r"[.\-+]", t.lstrip("vV"))
        )
        assert norm(reviewed) >= norm(current), (
            f"{a['id']}: reviewed_through={reviewed} is behind current={current}"
        )


def test_duckdb_floor_matches_pyproject():
    """COMPATIBILITY coupling: the registry's DuckDB floor MUST equal the pyproject
    [columnar] floor, so the bundled crypto-extension version stays in lockstep."""
    entry = next(a for a in R.load_registry() if a["id"] == "duckdb-crypto-extension")
    floor = str(entry["pin"]["floor"])
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'"duckdb>=([0-9.]+)"', pyproject)
    assert m, "could not find the duckdb floor in pyproject.toml [columnar]"
    assert m.group(1) == floor, (
        f"DuckDB coupling drift: pyproject duckdb>={m.group(1)} but registry floor={floor}. "
        "Bump both together + re-bundle the per-OS crypto extension."
    )


def test_sqlcipher3_range_in_pyproject_matches_the_registry_and_keeps_its_ceiling():
    """The damage lane (src/database/damage.py, the page pass) is built on how SQLCipher 4.12 reports page damage; sqlcipher3 0.6.4
    (SQLCipher 4.19) reports it differently and reddened tests/test_poisoned_connection.py and tests/test_database_verify_pages.py
    (2026-10-13). pyproject carries a ceiling below the first unqualified release and the registry carries the same floor: lifting
    the ceiling is the qualification's last step (docs/ledger/OPEN_QUEUE.md), never a way to get the lane green."""
    entry = next(a for a in R.load_registry() if a["id"] == "sqlcipher3-driver")
    pyproject = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'"sqlcipher3>=([0-9.]+),<([0-9.]+)"', pyproject)
    assert m, "pyproject.toml's sqlcipher3 requirement lost its ceiling (see the comment above it and OPEN_QUEUE)"
    assert m.group(1) == str(entry["pin"]["floor"]), "pyproject and the registry disagree on the sqlcipher3 floor"
    assert R._ver_ge(str(entry["pin"]["verified"]), m.group(1)), "the verified version is below the floor"
    assert not R._ver_ge(str(entry["pin"]["verified"]), m.group(2)), "the verified version is not below the ceiling"
    assert m.group(2) == str(entry["pin"]["ceiling"]), (
        "pyproject and the registry disagree on the sqlcipher3 ceiling; lifting it is the qualification's last step, in both places"
    )


def test_urllib3_range_in_pyproject_matches_the_registry_and_keeps_its_ceiling():
    """src/ingest/urllib3_log.py is built on the log calls of the urllib3 releases it was read from (2.7.0 and 2.8.0).
    pyproject carries the range with a ceiling at the first release NOT read, and the registry carries the same floor and ceiling:
    lifting the ceiling is the qualification's last step (docs/maintenance/EXTERNAL_DEPENDENCIES.md), never a way to get a lane green."""
    entry = next(a for a in R.load_registry() if a["id"] == "urllib3-log-shapes")
    pyproject = (R.repo_root() / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'"urllib3>=([0-9.]+),<([0-9.]+)"', pyproject)
    assert m, "pyproject.toml's urllib3 requirement lost its floor or its ceiling (see the comment above it)"
    assert m.group(1) == str(entry["pin"]["floor"]), "pyproject and the registry disagree on the urllib3 floor"
    assert m.group(2) == str(entry["pin"]["ceiling"]), "pyproject and the registry disagree on the urllib3 ceiling"
    assert not R._ver_ge(str(entry["pin"]["verified"]), m.group(2)), "the verified version is not below the ceiling"
    assert R._ver_ge(str(entry["pin"]["verified"]), m.group(1)), "the verified version is not inside the range"
    assert entry["upstream_check"]["current"] == str(entry["pin"]["verified"]), "the release the watch compares with is the newest one read"


def test_the_lockfile_pins_urllib3_inside_the_range_the_filter_was_read_for():
    """``lockfile-install`` installs ``requirements.lock`` and then the project with ``--no-deps``, so a lock whose urllib3 is outside the
    pyproject range installs green and runs a release nobody read the log calls of (the ``urllib3-floor`` job installs 2.7.0 by name, not
    from the lock). The lock's pin is the third place the range is written, and nothing else ties it to the other two."""
    entry = next(a for a in R.load_registry() if a["id"] == "urllib3-log-shapes")
    lock = (R.repo_root() / "requirements.lock").read_text(encoding="utf-8")
    pins = re.findall(r"^urllib3==([0-9][0-9.]*)\b", lock, flags=re.MULTILINE)
    assert len(pins) == 1, f"requirements.lock must pin urllib3 exactly once, found {pins}"
    assert R._ver_ge(pins[0], str(entry["pin"]["floor"])), f"the lock pins urllib3 {pins[0]}, below the floor the filter was read for"
    assert not R._ver_ge(pins[0], str(entry["pin"]["ceiling"])), f"the lock pins urllib3 {pins[0]}, at or above the ceiling (the first release not read)"


def test_trafilatura_floor_in_pyproject_matches_the_registry_and_the_lock_is_not_below_it():
    """``src/ingest/extract.py`` runs every parse of the app's article HTML under one lock because libxml2 aborted the collector (2026-10-14).
    ``trafilatura>=1.12`` admitted 2.0.x, whose ``Document`` shared one mutable lxml ``Element`` between threads (issue #840, fixed in
    2.1.0). The floor is written in three places (pyproject, the registry, the lock file) and nothing else ties them."""
    entry = next(a for a in R.load_registry() if a["id"] == "trafilatura-floor")
    pyproject = (R.repo_root() / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^\s*"trafilatura>=([0-9][0-9.]*)[",]', pyproject, flags=re.MULTILINE)
    assert m, "pyproject.toml's trafilatura requirement lost its floor (see the comment above it)"
    assert m.group(1) == str(entry["pin"]["floor"]), "pyproject and the registry disagree on the trafilatura floor"
    assert R._ver_ge(str(entry["pin"]["verified"]), m.group(1)), "the verified release is below the floor"
    assert entry["upstream_check"]["current"] == str(entry["pin"]["verified"]), "the release the watch compares with is the newest one run"
    lock = (R.repo_root() / "requirements.lock").read_text(encoding="utf-8")
    pins = re.findall(r"^trafilatura==([0-9][0-9.]*)\b", lock, flags=re.MULTILINE)
    assert len(pins) == 1, f"requirements.lock must pin trafilatura exactly once, found {pins}"
    assert R._ver_ge(pins[0], str(entry["pin"]["floor"])), f"the lock pins trafilatura {pins[0]}, below the floor"


def test_starlette_floor_in_pyproject_matches_the_registry_and_the_lock_is_not_below_it():
    """The API is gzip-compressed and the AI token streams are ``application/x-ndjson``: a Starlette that does not flush the deflate stream
    per chunk (anything below 1.5.0) holds a streamed reply back until several kilobytes pile up. ``fastapi`` itself only asks for
    ``starlette>=0.46.0``, and ``requirements.lock`` pinned 1.3.1. The floor is written in three places (pyproject, the registry, the lock
    file) and nothing else ties them."""
    entry = next(a for a in R.load_registry() if a["id"] == "starlette-gzip-flush")
    pyproject = (R.repo_root() / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^\s*"starlette>=([0-9][0-9.]*)[",]', pyproject, flags=re.MULTILINE)
    assert m, "pyproject.toml's starlette requirement lost its floor (see the comment above it)"
    assert m.group(1) == str(entry["pin"]["floor"]), "pyproject and the registry disagree on the starlette floor"
    assert R._ver_ge(str(entry["pin"]["verified"]), m.group(1)), "the verified release is below the floor"
    assert entry["upstream_check"]["current"] == str(entry["pin"]["verified"]), "the release the watch compares with is the newest one run"
    lock = (R.repo_root() / "requirements.lock").read_text(encoding="utf-8")
    pins = re.findall(r"^starlette==([0-9][0-9.]*)\b", lock, flags=re.MULTILINE)
    assert len(pins) == 1, f"requirements.lock must pin starlette exactly once, found {pins}"
    assert R._ver_ge(pins[0], str(entry["pin"]["floor"])), f"the lock pins starlette {pins[0]}, below the floor"


def test_duckdb_version_coupling_holds_when_installed():
    """When duckdb is installed, it must satisfy the registered floor (else the bundled
    extension + storage format would mismatch)."""
    try:
        import duckdb
    except Exception:  # noqa: BLE001 - optional [columnar] extra absent -> nothing to check
        return
    entry = next(a for a in R.load_registry() if a["id"] == "duckdb-crypto-extension")
    assert R._ver_ge(str(duckdb.__version__), str(entry["pin"]["floor"]))


def test_bundled_geo_db_is_parseable_at_its_vintage():
    """DATA COMPATIBILITY: the bundled IP-geo table loads + a known lookup works, and the
    file vintage matches the registered pin."""
    from src.geo import ip_geo

    entry = next(a for a in R.load_registry() if a["id"] == "ip-geo-country")
    assert R.read_const(entry["pin"]["file"], entry["pin"]["const"]) == ip_geo.IP_GEO_AS_OF
    fr = ip_geo.freshness()
    if fr["bundled"]:  # the real table is present in-repo
        ip_geo._country_ranges.cache_clear()
        r = ip_geo.lookup("8.8.8.8")
        assert r["level"] == "country" and isinstance(r["country"], str) and len(r["country"]) == 2
        ip_geo._country_ranges.cache_clear()


def test_freshness_windows_are_sane():
    for a in R.load_registry():
        fresh = a.get("freshness") or {}
        if "max_age_months" in fresh:
            assert 1 <= int(fresh["max_age_months"]) <= 36, f"odd window on {a['id']}"
