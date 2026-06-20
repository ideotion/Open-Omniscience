#!/usr/bin/env python3
"""
Open / update / close the ONE freshness tracking issue from the watch results.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Reads ``freshness.json`` (our pins, network-free) + ``upstream.json`` (is upstream newer)
produced by the freshness workflow, and keeps a SINGLE rolling GitHub issue (label
``freshness``) in sync: created/edited when something needs a refresh, closed when
everything is back within policy. Idempotent — never spams a new issue each week. The
issue body is a pure function (testable); the ``gh`` calls are guarded so a CLI/permission
hiccup is reported, never a hard crash.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

_LABEL = "freshness"
_TITLE = "🔄 External artifacts: refresh needed"


def _load(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def build_issue_body(freshness: dict[str, Any], upstream: dict[str, Any]) -> tuple[bool, str]:
    """Return ``(actionable, markdown_body)``. ``actionable`` is True when anything is past
    its window / a coupling broke / upstream is newer — i.e. the issue should be OPEN."""
    fa = {r["id"]: r for r in freshness.get("artifacts", [])}
    stale = freshness.get("stale", [])
    behind = upstream.get("behind", [])
    up = {r["id"]: r for r in upstream.get("upstream", [])}
    actionable = bool(stale or behind)

    lines = ["_Automated by `.github/workflows/freshness.yml`. One rolling issue; it closes "
             "itself when everything is back within policy._", ""]
    if stale:
        lines.append("### Past our freshness window / coupling broken")
        for i in stale:
            lines.append(f"- **{i}** — {fa.get(i, {}).get('detail', '')}")
        lines.append("")
    if behind:
        lines.append("### Upstream is newer than our pin")
        for i in behind:
            lines.append(f"- **{i}** — {up.get(i, {}).get('detail', '')}")
        lines.append("")
    failed = [r["id"] for r in upstream.get("upstream", []) if r.get("status") == "check-failed"]
    if failed:
        lines.append(f"<sub>upstream check could not run for: {', '.join(failed)} "
                     "(transient; not blocking)</sub>")
        lines.append("")
    lines.append("Refresh steps + the per-bump checklist: "
                 "`docs/maintenance/EXTERNAL_DEPENDENCIES.md`. "
                 "On a DuckDB bump, re-bundle the per-OS `httpfs` extension + keep the "
                 "`pyproject [columnar]` floor == the registry floor.")
    return actionable, "\n".join(lines)


def _gh(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
        return p.returncode, (p.stdout or p.stderr).strip()
    except Exception as e:  # noqa: BLE001 - gh missing / not authed (e.g. local run)
        return 127, f"gh unavailable: {e}"


def _existing_issue() -> int | None:
    _gh(["label", "create", _LABEL, "--color", "FBCA04",
         "--description", "External artifact needs a refresh", "--force"])
    rc, out = _gh(["issue", "list", "--label", _LABEL, "--state", "open",
                   "--json", "number", "--jq", ".[0].number"])
    if rc == 0 and out.strip().isdigit():
        return int(out.strip())
    return None


def main() -> int:
    actionable, body = build_issue_body(_load("freshness.json"), _load("upstream.json"))
    existing = _existing_issue()
    body_file = Path("freshness_issue_body.md")
    body_file.write_text(body, encoding="utf-8")

    if actionable:
        if existing:
            rc, out = _gh(["issue", "edit", str(existing), "--body-file", str(body_file)])
            print(f"updated issue #{existing}: {out}")
        else:
            rc, out = _gh(["issue", "create", "--title", _TITLE, "--label", _LABEL,
                           "--body-file", str(body_file)])
            print(f"created issue: {out}")
    elif existing:
        rc, out = _gh(["issue", "close", str(existing), "--comment",
                       "All external artifacts are within policy again. ✅"])
        print(f"closed issue #{existing}: {out}")
    else:
        print("nothing actionable; no open freshness issue. ✅")
    return 0  # a watch must not fail the workflow


if __name__ == "__main__":
    raise SystemExit(main())
