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
