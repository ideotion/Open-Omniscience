"""
Annotation storage — your authored set, imported bundles, web-of-trust, aggregation.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Local-first, no server, no accounts. Your own annotations live in ``mine.json``; each
imported bundle lives under ``imported/<author_id>.json`` with a per-author **trusted**
flag (opt-in web-of-trust). Aggregation is **transparent**: it returns *who asserted
what*, grouping by claim and surfacing dissent — it never averages assertions into a
hidden number, and it never emits a composite score.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from src.annotations.bundle import (
    Annotation,
    annotation_signer,
    author_id,
    build_signed_bundle,
    verify_bundle,
)

_LOG = logging.getLogger(__name__)
STORE_VERSION = "oo-annotations-store-1"
_MINE_AUTHOR = "me"


def _dir():
    from src.paths import data_dir

    d = data_dir() / "annotations"
    (d / "imported").mkdir(parents=True, exist_ok=True)
    return d


def _mine_path():
    return _dir() / "mine.json"


def _imported_dir():
    return _dir() / "imported"


# --------------------------------------------------------------------------- #
#  Your authored annotations
# --------------------------------------------------------------------------- #
def load_mine() -> dict:
    path = _mine_path()
    if not path.exists():
        return {"author_name": _MINE_AUTHOR, "annotations": []}
    try:
        d = json.loads(path.read_text("utf-8"))
        d.setdefault("author_name", _MINE_AUTHOR)
        d.setdefault("annotations", [])
        return d
    except Exception:  # noqa: BLE001 - a bad file must not break the surface
        _LOG.warning("annotations/mine.json unreadable; starting fresh", exc_info=True)
        return {"author_name": _MINE_AUTHOR, "annotations": []}


def _save_mine(d: dict) -> dict:
    path = _mine_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)
    return d


def set_author_name(name: str) -> dict:
    d = load_mine()
    d["author_name"] = name.strip() or _MINE_AUTHOR
    return _save_mine(d)


def add_annotation(target: str, kind: str, value: str, note: str = "") -> dict:
    """Add an annotation to your authored set (validated)."""
    ann = Annotation(target=target, kind=kind, value=value, note=note)
    d = load_mine()
    d["annotations"].append(ann.to_dict())
    return _save_mine(d)


def remove_annotation(index: int) -> dict:
    d = load_mine()
    if 0 <= index < len(d["annotations"]):
        d["annotations"].pop(index)
    return _save_mine(d)


def export_bundle() -> dict:
    """Sign your authored annotations into a portable bundle."""
    d = load_mine()
    annotations = [Annotation.from_dict(a) for a in d["annotations"]]
    return build_signed_bundle(d.get("author_name", _MINE_AUTHOR), annotations, annotation_signer())


# --------------------------------------------------------------------------- #
#  Imported bundles + web-of-trust
# --------------------------------------------------------------------------- #
def import_bundle(bundle: dict, *, trusted: bool = True) -> dict:
    """Verify and store an imported bundle. Returns a summary; refuses an invalid one."""
    ok, reason, identity = verify_bundle(bundle)
    if not ok:
        raise ValueError(f"bundle failed verification, not imported: {reason}")
    aid = author_id(identity)
    record = {
        "version": STORE_VERSION,
        "author_id": aid,
        "author_name": bundle["manifest"].get("author_name", aid[:12]),
        "identity": identity,
        "annotations": bundle["manifest"].get("annotations", []),
        "trusted": trusted,
        "imported_at": datetime.now(UTC).isoformat(),
        "verify_reason": reason,
    }
    path = _imported_dir() / f"{aid[:32]}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)
    return {
        "author_id": aid,
        "author_name": record["author_name"],
        "annotations": len(record["annotations"]),
        "trusted": trusted,
    }


def adopt_imported_record(record: dict) -> dict:
    """Adopt an already-verified imported-author RECORD directly (no re-verification).

    An imported record is written by :func:`import_bundle` AFTER a signed bundle has
    been verified: the manifest + signature are stripped and only the verified content
    (plus a ``verify_reason`` provenance note) is kept. When such a record travels
    inside a backup artifact (which is itself signature-verified as a whole), its
    original bundle is gone, so it CANNOT be re-verified. This adopts the record as-is
    — mirroring how ``mine.json`` restores — instead of re-running :func:`import_bundle`
    (which correctly rejects a bundle-less record). Never used for untrusted input:
    the caller is the additive restore over a verified artifact.

    Local always wins: if a record for this author already exists locally it is kept
    and nothing is overwritten (idempotent — re-running converges). The record is
    validated structurally (a garbage/tampered non-record is refused, never adopted).
    """
    if not isinstance(record, dict):
        raise ValueError("imported record is not an object")
    if record.get("version") != STORE_VERSION:
        raise ValueError(
            f"not an imported-author record (version {record.get('version')!r}, "
            f"expected {STORE_VERSION!r})"
        )
    aid = record.get("author_id")
    if not isinstance(aid, str) or not aid:
        raise ValueError("imported record has no author_id")
    if not isinstance(record.get("annotations"), list):
        raise ValueError("imported record has no annotations list")

    path = _imported_dir() / f"{aid[:32]}.json"
    if path.exists():
        # The existing local identity/trust decision ALWAYS wins over an incoming copy.
        return {
            "author_id": aid,
            "author_name": record.get("author_name"),
            "annotations": len(record["annotations"]),
            "trusted": bool(record.get("trusted")),
            "adopted": False,
            "reason": "an imported record for this author already exists locally",
        }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)
    return {
        "author_id": aid,
        "author_name": record.get("author_name"),
        "annotations": len(record["annotations"]),
        "trusted": bool(record.get("trusted")),
        "adopted": True,
    }


def _imported_records() -> list[dict]:
    out = []
    for p in sorted(_imported_dir().glob("*.json")):
        try:
            out.append(json.loads(p.read_text("utf-8")))
        except Exception:  # noqa: BLE001 - skip a corrupt record, never crash
            _LOG.warning("imported annotation file %s unreadable; skipping", p, exc_info=True)
    return out


def list_authors() -> list[dict]:
    """All imported authors with their trust flag and counts (transparent web-of-trust)."""
    return [
        {
            "author_id": r["author_id"],
            "author_name": r.get("author_name"),
            "annotations": len(r.get("annotations", [])),
            "trusted": bool(r.get("trusted")),
            "imported_at": r.get("imported_at"),
        }
        for r in _imported_records()
    ]


def set_trusted(author_id_value: str, trusted: bool) -> bool:
    """Trust or untrust an imported author (their annotations are included only if trusted)."""
    for p in _imported_dir().glob("*.json"):
        try:
            r = json.loads(p.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if r.get("author_id") == author_id_value:
            r["trusted"] = trusted
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(r, ensure_ascii=False, indent=2), "utf-8")
            tmp.replace(p)
            return True
    return False


def remove_author(author_id_value: str) -> bool:
    """Remove an imported author entirely — their annotations cleanly disappear."""
    for p in _imported_dir().glob("*.json"):
        try:
            r = json.loads(p.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if r.get("author_id") == author_id_value:
            p.unlink()
            return True
    return False


# --------------------------------------------------------------------------- #
#  Transparent aggregation — who asserted what, dissent shown not averaged
# --------------------------------------------------------------------------- #
def aggregate_for_target(target: str) -> dict:
    """Every annotation about ``target`` from you + trusted authors, attributed.

    Groups by (kind, value) and lists *who* asserted each — so agreement and dissent
    are both visible. There is deliberately **no** consensus number and **no** score:
    the user reads the attributions and decides.
    """
    norm = (target or "").strip().lower()
    contributions: list[dict] = []

    mine = load_mine()
    for a in mine.get("annotations", []):
        if a.get("target", "").strip().lower() == norm:
            contributions.append(
                {
                    "author": mine.get("author_name", _MINE_AUTHOR),
                    "author_id": "me",
                    "trusted": True,
                    **a,
                }
            )
    for r in _imported_records():
        if not r.get("trusted"):
            continue
        for a in r.get("annotations", []):
            if a.get("target", "").strip().lower() == norm:
                contributions.append(
                    {
                        "author": r.get("author_name"),
                        "author_id": r.get("author_id"),
                        "trusted": True,
                        **a,
                    }
                )

    # Group by (kind, value): each claim lists its asserters; differing values = dissent.
    claims: dict[tuple, list[dict]] = {}
    for c in contributions:
        claims.setdefault((c["kind"], c["value"]), []).append(
            {"author": c["author"], "author_id": c["author_id"], "note": c.get("note", "")}
        )
    grouped = [
        {"kind": k, "value": v, "asserted_by": who, "count": len(who)}
        for (k, v), who in sorted(claims.items())
    ]
    # Dissent = a kind that carries more than one distinct value.
    kinds: dict[str, set] = {}
    for k, v in claims:
        kinds.setdefault(k, set()).add(v)
    dissent = sorted(k for k, vals in kinds.items() if len(vals) > 1)

    return {
        "target": target,
        "total_assertions": len(contributions),
        "claims": grouped,
        "dissent_kinds": dissent,
        "caveat": (
            "These are attributed assertions from you and the authors you chose to trust — "
            "not a consensus, not a verdict, and never averaged into a score. Differing values "
            "for the same kind are shown as dissent, not resolved for you."
        ),
    }
