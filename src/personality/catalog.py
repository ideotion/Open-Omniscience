"""Loader for the bundled personality catalog (configs/personality.yml).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Tiny, dependency-light, offline. Two kinds: ``quotes`` (attributed; disputed
attributions flagged) and ``fun_facts`` (each carrying a ``source``). Malformed
entries are skipped rather than crashing, mirroring the other catalog loaders.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

import yaml

CATALOG_PATH = Path(__file__).resolve().parents[2] / "configs" / "personality.yml"


@lru_cache(maxsize=1)
def load_catalog(path: Path | None = None) -> dict[str, list[dict]]:
    """Return ``{"quotes": [...], "fun_facts": [...]}`` from the YAML catalog."""
    p = path or CATALOG_PATH
    if not p.exists():
        return {"quotes": [], "fun_facts": []}
    data = yaml.safe_load(p.read_text("utf-8")) or {}
    quotes = [
        {
            "text": str(q["text"]),
            "author": q.get("author"),
            "source": q.get("source"),
            "attribution": q.get("attribution", "confirmed"),
        }
        for q in (data.get("quotes") or [])
        if isinstance(q, dict) and q.get("text")
    ]
    facts = [
        {"text": str(f["text"]), "source": f.get("source")}
        for f in (data.get("fun_facts") or [])
        if isinstance(f, dict) and f.get("text")
    ]
    return {"quotes": quotes, "fun_facts": facts}


def random_item(kind: str = "quote") -> dict | None:
    """One random quote (``kind='quote'``) or fun fact (``kind='fact'``), or None if empty."""
    cat = load_catalog()
    pool = cat["fun_facts"] if kind == "fact" else cat["quotes"]
    if not pool:
        return None
    return {**pool[secrets.randbelow(len(pool))], "kind": "fact" if kind == "fact" else "quote"}
