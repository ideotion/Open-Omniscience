"""
The external-artifact registry — loader + freshness/coupling evaluation.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Reads ``configs/external_artifacts.yml`` (the single source of truth for everything we
pin / vendor / bundle from upstream) and answers three questions, NETWORK-FREE:

  * which ``*_AS_OF`` (or version) pins exist, so a guard test can prove EVERY dated
    constant in the tree is registered (no dated artifact ships unwatched);
  * how STALE each artifact is vs its own freshness policy (the consolidated check that
    replaces the scattered per-file freshness tests);
  * whether each version COUPLING holds (e.g. the DuckDB floor ↔ the bundled crypto
    extension ↔ the installed DuckDB) — the gotcha a date-only check can't see.

It NEVER touches the network: pins are read from local source files; the proactive
"is upstream newer?" watch is a separate, explicitly-consented scheduled job.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _ROOT / "configs" / "external_artifacts.yml"


def repo_root() -> Path:
    return _ROOT


def load_registry(path: Path | None = None) -> list[dict[str, Any]]:
    """Parse the registry YAML into a list of artifact entries."""
    import yaml

    data = yaml.safe_load((path or _REGISTRY_PATH).read_text(encoding="utf-8")) or {}
    return list(data.get("artifacts", []))


def read_const(file_rel: str, const: str) -> str | None:
    """Read a ``CONST = "value"`` (Python) or ``CONST="value"`` (shell) literal from a
    source file WITHOUT importing it. Returns the string value, or None if not found."""
    p = _ROOT / file_rel
    if not p.exists():
        return None
    pat = re.compile(rf'^\s*{re.escape(const)}\s*(?::[^=]*)?=\s*["\']([^"\']+)["\']', re.M)
    m = pat.search(p.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def registered_pins() -> set[tuple[str, str]]:
    """The set of ``(file, const)`` pins the registry declares — the protocol guard
    asserts every ``*_AS_OF`` constant in the tree is in this set."""
    out: set[tuple[str, str]] = set()
    for a in load_registry():
        pin = a.get("pin") or {}
        if pin.get("file") and pin.get("const") and pin.get("const") != "NONE":
            out.add((pin["file"], pin["const"]))
    return out


def age_months(as_of: str, *, today: date | None = None) -> int | None:
    """Whole months between an ``YYYY-MM`` / ``YYYY-MM-DD`` stamp and today. None if the
    stamp is not a real date (e.g. the honest ``"unbundled"`` sentinel)."""
    today = today or date.today()
    m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$", str(as_of).strip())
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    return (today.year - y) * 12 + (today.month - mo)


def file_sha256(path_rel: str) -> str | None:
    p = _ROOT / path_rel
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _installed_duckdb_version() -> str | None:
    try:
        import duckdb

        return str(duckdb.__version__)
    except Exception:  # noqa: BLE001 - optional extra
        return None


def evaluate(today: date | None = None) -> list[dict[str, Any]]:
    """Per-artifact freshness/coupling status (network-free).

    ``status`` is one of: ``ok`` (within policy / coupling holds), ``stale`` (past the
    freshness window or a coupling is broken), ``unknown`` (the pin can't be resolved —
    e.g. an unbundled sentinel), or ``info`` (no time policy — security/rarely/Dependabot).
    """
    rows: list[dict[str, Any]] = []
    for a in load_registry():
        fresh = a.get("freshness") or {}
        pin = a.get("pin") or {}
        rec: dict[str, Any] = {
            "id": a["id"],
            "title": a.get("title", a["id"]),
            "kind": a.get("kind"),
            "status": "info",
            "detail": "",
        }
        # 1) dated pins with a max-age window
        if "max_age_months" in fresh and pin.get("file") and pin.get("const"):
            as_of = read_const(pin["file"], pin["const"])
            rec["as_of"] = as_of
            age = age_months(as_of, today=today) if as_of else None
            rec["age_months"] = age
            limit = int(fresh["max_age_months"])
            if as_of is None or age is None:
                rec["status"] = "unknown"
                rec["detail"] = f"pin {pin['file']}:{pin['const']} did not resolve to a date"
            elif age > limit:
                rec["status"] = "stale"
                rec["detail"] = f"{age} months old (limit {limit}); refresh: {a.get('refresh', '')}"
            else:
                rec["status"] = "ok"
                rec["detail"] = f"{age}/{limit} months"
        # 2) the DuckDB version coupling
        elif fresh.get("policy") == "track-duckdb-version":
            floor, verified = pin.get("floor"), pin.get("verified")
            installed = _installed_duckdb_version()
            rec["pin"] = {"floor": floor, "verified": verified, "installed": installed}
            if installed is None:
                rec["status"] = "info"
                rec["detail"] = "duckdb not installed ([columnar] extra absent)"
            else:
                ok = _ver_ge(installed, str(floor))
                rec["status"] = "ok" if ok else "stale"
                rec["detail"] = (
                    f"installed {installed} vs floor {floor} (verified {verified}); "
                    "on a bump, re-bundle the per-OS crypto extension + re-run the gate"
                )
        # 3) vendored checksum (info unless a sha is recorded + drifts)
        elif pin.get("path") and "sha256" in pin:
            actual = file_sha256(pin["path"])
            expected = pin.get("sha256") or ""
            rec["detail"] = "present" if actual else "MISSING FILE"
            if not actual:
                rec["status"] = "stale"
            elif expected and expected != actual:
                rec["status"] = "stale"
                rec["detail"] = "checksum DRIFTED from the registered sha256"
            else:
                rec["status"] = "info" if not expected else "ok"
        else:
            rec["status"] = "info"
            rec["detail"] = str(fresh.get("policy", "tracked (no time window)"))
        rows.append(rec)
    return rows


def _ver_ge(a: str, b: str) -> bool:
    """a >= b for dotted numeric versions (lenient: non-numeric tails ignored)."""
    def parts(v: str) -> list[int]:
        out = []
        for p in str(v).split("."):
            m = re.match(r"\d+", p)
            out.append(int(m.group()) if m else 0)
        return out

    pa, pb = parts(a), parts(b)
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    return pa >= pb


def summary(today: date | None = None) -> dict[str, Any]:
    """A compact roll-up for the diagnostics endpoint + the CLI."""
    rows = evaluate(today=today)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "artifacts": rows,
        "counts": counts,
        "stale": [r["id"] for r in rows if r["status"] == "stale"],
        "method": (
            "Network-free freshness/coupling check over configs/external_artifacts.yml. "
            "'stale' = past its freshness window or a version coupling broke; the proactive "
            "upstream-newer-than-pin watch is a separate consented scheduled job."
        ),
    }
