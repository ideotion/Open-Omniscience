"""
The draft accumulator — from card to newsletter (the payoff loop).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A card carries a "→ Add to draft" action into this simple accumulator (pinned cards
+ the user's notes). It exports **Markdown** in which *each claim already carries its
source links* and its method + caveat — the differentiator is reproducible
journalism: the evidence ships with the issue. Persisted as a small JSON file under
the data dir (single-user, local-first), the same pattern as the other settings.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

_LOG = logging.getLogger(__name__)

DRAFT_VERSION = "oo-briefing-draft-1"
_DEFAULT_TITLE = "Open Omniscience briefing"


def _draft_path():
    from src.paths import data_dir

    return data_dir() / "briefing_draft.json"


def load_draft() -> dict:
    path = _draft_path()
    if not path.exists():
        return {"version": DRAFT_VERSION, "title": _DEFAULT_TITLE, "items": []}
    try:
        data = json.loads(path.read_text("utf-8"))
        data.setdefault("title", _DEFAULT_TITLE)
        data.setdefault("items", [])
        return data
    except Exception:  # noqa: BLE001 - a bad file must not break the draft surface
        _LOG.warning("briefing_draft.json unreadable; starting a fresh draft", exc_info=True)
        return {"version": DRAFT_VERSION, "title": _DEFAULT_TITLE, "items": []}


def _save(draft: dict) -> dict:
    draft["version"] = DRAFT_VERSION
    path = _draft_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(draft, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)
    return draft


def add_card(card: dict, *, note: str = "") -> dict:
    """Pin a card into the draft (idempotent by card id). Updates the note if re-added."""
    if not isinstance(card, dict) or not card.get("id"):
        raise ValueError("a card with an 'id' is required")
    draft = load_draft()
    for item in draft["items"]:
        if item["card"].get("id") == card["id"]:
            if note:
                item["note"] = note
            return _save(draft)
    draft["items"].append({"card": card, "note": note, "added_at": datetime.now(UTC).isoformat()})
    return _save(draft)


def remove_card(card_id: str) -> dict:
    draft = load_draft()
    draft["items"] = [it for it in draft["items"] if it["card"].get("id") != card_id]
    return _save(draft)


def set_note(card_id: str, note: str) -> dict:
    draft = load_draft()
    for item in draft["items"]:
        if item["card"].get("id") == card_id:
            item["note"] = note
    return _save(draft)


def set_title(title: str) -> dict:
    draft = load_draft()
    draft["title"] = title.strip() or _DEFAULT_TITLE
    return _save(draft)


def clear_draft() -> dict:
    return _save({"version": DRAFT_VERSION, "title": _DEFAULT_TITLE, "items": []})


def _evidence_md(evidence: list[dict]) -> list[str]:
    lines: list[str] = []
    for ev in evidence or []:
        title = ev.get("title") or ev.get("url") or "source"
        url = ev.get("url")
        source = ev.get("source")
        when = ev.get("published_at")
        bits = []
        if url:
            bits.append(f"[{title}]({url})")
        else:
            bits.append(str(title))
        tail = " · ".join(filter(None, [source, (when or "")[:10] if when else None]))
        if tail:
            bits.append(f"*{tail}*")
        lines.append("  - " + " — ".join(bits))
    return lines


def export_markdown(draft: dict | None = None) -> str:
    """Render the draft as Markdown — every claim carrying its evidence + method + caveat."""
    draft = draft or load_draft()
    title = draft.get("title") or _DEFAULT_TITLE
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [f"# {title}", "", f"*Compiled {generated} with Open Omniscience.*", ""]

    if not draft.get("items"):
        lines += ["_No Leads pinned yet. Add Leads from the Home briefing to build an issue._", ""]
        return "\n".join(lines)

    for item in draft["items"]:
        card = item["card"]
        lines.append(f"## {card.get('title', 'Untitled')}")
        lines.append("")
        if card.get("summary"):
            lines.append(card["summary"])
            lines.append("")
        if item.get("note"):
            lines.append(f"> {item['note']}")
            lines.append("")
        signal = card.get("signal") or {}
        if signal:
            metric = signal.get("metric")
            value = signal.get("value")
            if metric is not None and value is not None:
                lines.append(
                    f"**Signal:** `{metric}` = {value}"
                    + (f" (n={card['n']})" if card.get("n") is not None else "")
                )
                lines.append("")
        evidence = _evidence_md(card.get("evidence"))
        if evidence:
            lines.append("**Evidence:**")
            lines += evidence
            lines.append("")
        if card.get("method"):
            lines.append(f"*Method: {card['method']}*")
        if card.get("caveat"):
            lines.append(f"*Caveat: {card['caveat']}*")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines += [
        "_Every figure above is a measured signal with a stated method and caveat, not a "
        "verdict. Open the linked sources and judge for yourself. For a tamper-evident, "
        "signed copy of the underlying articles, export an evidence bundle from "
        "Evidence & custody._",
        "",
    ]
    return "\n".join(lines)
