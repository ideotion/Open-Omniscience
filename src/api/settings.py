"""
Application preferences API (theme, default result limit).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Backs the Settings tab. Preferences persist to a small JSON file under the data
dir (see ``src.config.app_settings``); validation happens there so an invalid
value is rejected with an explicit 400 rather than silently coerced.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config.app_settings import (
    VALID_THEMES,
    AppSettingsError,
    load_settings,
    save_settings,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    theme: str | None = None
    default_result_limit: int | None = None
    # Investigation-recipe producers to switch off (0.0.8 WP8 / RM-20).
    recipes_disabled: list[str] | None = None
    # Settings restructure PR-7: the same switch, widened to every Lead producer,
    # plus their per-producer tunables ({producer: {key: value}}).
    cards_disabled: list[str] | None = None
    card_settings: dict | None = None
    # Active local LLM model tag (maintainer Q10): "" / null clears the override.
    llm_model: str | None = None
    # Local-LLM behaviour (maintainer 2026-06-17): how long Ollama keeps the model
    # loaded, and operator-editable system prompts ("" = built-in default).
    llm_keep_alive: str | None = None
    llm_prompt_summary: str | None = None
    llm_prompt_translate: str | None = None
    llm_prompt_synthesis: str | None = None
    llm_prompt_ai_keywords: str | None = None  # the built-in keyword-extraction prompt (Part B)
    # Auto-start language detection (2026-07-24 Session A §1): opt out of the
    # scheduler ride-along that (re)starts the AI language-detection job.
    ai_langdetect_auto: bool | None = None
    # DUAL BACKEND (2026-07-24 Session B, B1, RULED A12): "auto" | "ollama" | "vllm".
    llm_backend: str | None = None
    # The active model id for the vLLM backend (a HF repo id). "" / null clears it.
    llm_model_vllm: str | None = None
    # HARDWARE SUITABILITY OVERRIDE (2026-07-30): run local inference even on
    # hardware the gate calls impractical (no dedicated GPU / below the Apple
    # Silicon unified-memory floor). Never a hard block -- this is the operator's
    # explicit "anyway", and the verdict then discloses overridden=True.
    llm_allow_impractical_hw: bool | None = None
    # BACKGROUND-AI COORDINATOR (2026-08-01 ruling 12a): the master switch plus the
    # per-sweep membership flags it coordinates (the master never hides them).
    ai_background_enabled: bool | None = None
    ai_sweep_keyword_triage: bool | None = None
    ai_sweep_source_tags: bool | None = None
    ai_sweep_perception_extract: bool | None = None


def _payload() -> dict:
    s = load_settings()
    return {**s.to_dict(), "valid_themes": list(VALID_THEMES)}


@router.get("")
def get_settings() -> dict:
    """Return current UI preferences plus the set of valid theme values."""
    return _payload()


@router.put("")
def update_settings(update: SettingsUpdate) -> dict:
    """Apply a partial preferences update (only provided fields change)."""
    try:
        saved = save_settings(update.model_dump(exclude_unset=True))
    except AppSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    payload = _payload()
    # Any value that had to be pulled back into a producer's safe range is
    # REPORTED, never applied in silence (ruling 3, 2026-07-31). An empty list
    # means nothing was adjusted -- the caller can rely on that distinction.
    payload["clamped"] = list(getattr(saved, "last_clamp_notes", []) or [])
    return payload


@router.get("/cards")
def cards_catalog() -> dict:
    """Every Lead producer, grouped by family, with its tunables and their SAFE RANGES.

    This is what the Settings -> Cards surface renders. Each tunable carries its
    default, its ``lo``/``hi`` bounds, the plain-language ``impact`` of moving it
    and -- where a bound exists to stop an underpowered claim rather than merely
    to be sensible -- the ``floor_reason`` for it, so a limit is never presented
    as an arbitrary restriction.

    Read-only and local: no network, no scores, no ranking of producers.
    """
    from src.briefing.catalog import by_family, defaults_for, settings_for
    from src.briefing.card import BUCKET_LABELS

    s = load_settings()
    off = set(s.cards_disabled or []) | set(s.recipes_disabled or [])
    families = []
    for family, specs in by_family():
        if not specs:
            continue
        families.append({
            "family": family,
            "label": BUCKET_LABELS.get(family, family),
            "producers": [
                {
                    "name": spec.name,
                    "label": spec.label,
                    "description": spec.description,
                    "enabled": spec.name not in off,
                    "tunables": [
                        {
                            "key": t.key,
                            "label": t.label,
                            "kind": t.kind,
                            "unit": t.unit,
                            "default": defaults_for(spec.name)[t.key],
                            "value": settings_for(spec.name)[t.key],
                            "lo": t.lo,
                            "hi": t.hi,
                            "impact": t.impact,
                            "floor_reason": t.floor_reason,
                        }
                        for t in spec.tunables
                    ],
                }
                for spec in specs
            ],
        })
    return {
        "families": families,
        "method": (
            "Every Lead producer registered in this app, with the thresholds it "
            "already applied — now visible and adjustable. Turning one off stops it "
            "producing Leads; it changes nothing about the articles themselves."
        ),
        "caveat": (
            "Each range has a safe minimum and maximum. You can always make a Lead "
            "stricter; the lower bounds exist so a Lead can never claim more than "
            "the evidence behind it supports."
        ),
    }
