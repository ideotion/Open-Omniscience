"""
Persistence for the B6 (2026-07-24 Session B) LIVE perception-eval-against-model
run -- the gate evidence the standing ruling requires BEFORE any who/where/when
extraction feature ships.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Mirrors ``src.ai_layer.triage_job``'s dated-JSONL-log + ``last_*_report()``
convention, but this artifact is a single JSON document (the harness result is
already one bounded dict, not a stream of per-batch records) -- so it is a
dated ``.json`` file, one per run, newest-wins on read.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PERCEPTION_LIVE_SCHEMA = "oo-perception-eval-live-1"


def _dir() -> Path:
    from src.paths import data_dir

    d = data_dir() / "triage"  # same log home as triage/source-tags -- one AI-run archive
    d.mkdir(parents=True, exist_ok=True)
    return d


def _export_path() -> Path:
    return _dir() / f"oo-perception-eval-live-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"


def run_and_persist_perception_eval(client=None, *, model: str | None = None) -> dict:
    """Resolve the active backend (unless a client/model are injected for
    tests), run the harness against it, persist the dated JSON artifact, and
    return it. NEVER writes the trusted index -- this is a read-only eval over
    a synthetic gold set + one JSON log file."""
    from src.ai_layer.perception import run_perception_eval_against_model

    if client is None or model is None:
        from src.api.llm import active_model
        from src.llm.backend import get_client_with_name

        backend_name, resolved_client = get_client_with_name()
        client = client or resolved_client
        model = model or active_model()
    else:
        backend_name = None

    out = run_perception_eval_against_model(client, model=model, backend_name=backend_name)
    out["schema"] = PERCEPTION_LIVE_SCHEMA
    out["run_at"] = datetime.now().isoformat(timespec="seconds")
    path = _export_path()
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    out["path"] = str(path)
    out["filename"] = path.name
    return out


def last_perception_eval_live_report() -> dict:
    """The newest saved live-eval artifact (read-only; never runs an eval).
    Honest ``{available: false}`` stub when none has ever been produced."""
    try:
        files = sorted(_dir().glob("oo-perception-eval-live-*.json"))
        if not files:
            return {
                "schema": PERCEPTION_LIVE_SCHEMA,
                "available": False,
                "note": (
                    "no live perception-eval run has been made yet -- run it from "
                    "Settings -> AI, or POST /api/diagnostics/perception-eval-live."
                ),
            }
        path = files[-1]
        data = json.loads(path.read_text(encoding="utf-8"))
        data["available"] = True
        data["filename"] = path.name
        return data
    except Exception as exc:  # noqa: BLE001 - a diagnostic must degrade, never 500
        return {"schema": PERCEPTION_LIVE_SCHEMA, "available": False, "error": str(exc)[:300]}


__all__ = [
    "PERCEPTION_LIVE_SCHEMA",
    "last_perception_eval_live_report",
    "run_and_persist_perception_eval",
]
