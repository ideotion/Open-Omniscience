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
        save_settings(update.model_dump(exclude_unset=True))
    except AppSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _payload()
