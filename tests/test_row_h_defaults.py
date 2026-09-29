"""Row H's second PR: the bulletin's opening default (D2) and per-language perception (S6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

D2 (register, placed beside row H by RC08.2 = a): every edition OPENS on the
deterministic introduction; the model-written one is opt-in. S6 (Q1144 = a / D10):
perception extraction runs per language only where the measured gate passes, the
operator may switch a cleared language off, and NOTHING the operator does can switch a
failed or unmeasured language on -- the negation fixture below.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.ai_layer import perception_extract as PE
from src.bulletin import introduction as I
from src.database.models import Base


# --------------------------------------------------------------------------- #
#  D2 -- the opening
# --------------------------------------------------------------------------- #
def _built_edition():
    from src.bulletin.edition import build_edition
    from src.bulletin.period import resolve_period

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        return build_edition(s, resolve_period("weekly", end=date(2026, 8, 11)))


def test_every_new_edition_opens_on_the_deterministic_introduction():
    ed = _built_edition()
    intro = ed["introduction"]
    assert intro["text"] and intro["narrated"] is False
    # Not a fallback: nothing failed and no model was asked.
    assert intro["fallback_reason"] is None
    assert "opt-in" in intro["method"]


def test_the_default_opening_renders_without_an_ai_label_or_a_failure_line():
    from src.bulletin.render import render_markdown

    ed = _built_edition()
    md = render_markdown(ed)
    assert ed["introduction"]["text"] in md
    head = md[: md.index(ed["introduction"]["text"])]
    assert "AI-derived" not in head
    assert "No model text" not in md


def test_the_opening_has_the_narrated_blocks_shape():
    a = I.opening_block({"masthead": {}, "period": {}})
    for key in ("unit", "text", "narrated", "sentences", "prompt_version", "fallback_reason"):
        assert key in a


def test_the_model_written_opening_is_opt_in(monkeypatch):
    from src.api import bulletin as B
    from src.config.app_settings import AppSettings

    assert AppSettings().bulletin_narrate_introduction is False
    monkeypatch.setattr(
        "src.config.app_settings.load_settings",
        lambda: AppSettings(bulletin_narrate_introduction=False),
    )
    assert B._narrate_introduction(None) is False
    assert B._narrate_introduction(True) is True  # an explicit ask still wins
    monkeypatch.setattr(
        "src.config.app_settings.load_settings",
        lambda: AppSettings(bulletin_narrate_introduction=True),
    )
    assert B._narrate_introduction(None) is True
    assert B._narrate_introduction(False) is False


def test_an_unreadable_settings_file_never_narrates_the_opening(monkeypatch):
    from src.api import bulletin as B

    def boom():
        raise OSError("unreadable")

    monkeypatch.setattr("src.config.app_settings.load_settings", boom)
    assert B._narrate_introduction(None) is False


# --------------------------------------------------------------------------- #
#  S6 -- perception languages
# --------------------------------------------------------------------------- #
def _field(active, reason="r"):
    return {"active": active, "reason": reason, "checks": ["who hallucination 0.1"] if active is not None else []}


_GATE = {
    "fr": {"active": True, "reason": "cleared", "n_cases": 4, "checks": ["where recall 1.0"],
           "fields": {"who": _field(True), "where": _field(True), "when": _field(None)}},
    "hi": {"active": True, "reason": "cleared for where", "n_cases": 2, "checks": ["x"],
           "fields": {"who": _field(False, "who hallucination 0.8 above 0.5"),
                      "where": _field(True), "when": _field(None)}},
    "de": {"active": False, "reason": "failed", "n_cases": 3, "checks": ["y"],
           "fields": {"who": _field(False), "where": _field(False), "when": _field(None)}},
    "sw": {"active": None, "reason": "unmeasured", "n_cases": None, "checks": [],
           "fields": {"who": _field(None), "where": _field(None), "when": _field(None)}},
}


def test_a_cleared_language_can_be_switched_off_and_says_so():
    g = PE.apply_operator_off(_GATE, ["fr"])
    ok, why = PE.language_gate("fr", g)
    assert ok is False and "switched off by you" in why
    assert g["fr"]["switched_off"] is True and g["fr"]["measured_active"] is True
    for fld in ("who", "where"):
        assert PE.field_gate("fr", fld, g)[0] is False
    # The unmeasured field keeps its own, more specific reason.
    assert g["fr"]["fields"]["when"]["reason"] == "r"
    assert PE.language_gate("fr", PE.apply_operator_off(_GATE, []))[0] is True


@pytest.mark.parametrize("lang", ["de", "sw"])
def test_NEGATION_a_failed_or_unmeasured_language_stays_refused_whatever_the_switch(lang):
    for off in ([], [lang], ["fr"], ["fr", "hi", "de", "sw"]):
        g = PE.apply_operator_off(_GATE, off)
        assert PE.language_gate(lang, g)[0] is False
        for fld in ("who", "where", "when"):
            assert PE.field_gate(lang, fld, g)[0] is False
        assert g[lang]["switched_off"] is False  # the refusal is the harness's, not yours


def test_who_stays_refused_where_its_field_failed_even_with_the_language_on():
    g = PE.apply_operator_off(_GATE, [])
    assert PE.language_gate("hi", g)[0] is True
    assert PE.field_gate("hi", "where", g)[0] is True
    assert PE.field_gate("hi", "who", g)[0] is False


def test_the_overlay_never_mutates_the_measured_gate():
    import copy

    before = copy.deepcopy(_GATE)
    PE.apply_operator_off(_GATE, ["fr", "hi", "de"])
    assert before == _GATE


def test_the_sweep_and_the_preview_both_read_the_switches(monkeypatch):
    from src.ai_layer import perception_extract_job as J

    monkeypatch.setattr(PE, "gate_languages_from_report", lambda _r: dict(_GATE))
    monkeypatch.setattr(PE, "operator_off_languages", lambda: ["fr"])
    monkeypatch.setattr(
        "src.ai_layer.perception_job.last_perception_eval_live_report", lambda: {}
    )
    g = J.current_language_gate()
    assert g["fr"]["active"] is False and g["fr"]["switched_off"] is True
    import inspect

    src = inspect.getsource(J.run_progressive_perception_extract_job)
    assert "apply_operator_off" in src and "operator_off_languages" in src


def test_the_setting_accepts_only_language_codes():
    from src.config import app_settings as AS

    with pytest.raises(AS.AppSettingsError):
        AS.save_settings({"perception_languages_off": ["fr", "../x"]})
    with pytest.raises(AS.AppSettingsError):
        AS.save_settings({"perception_languages_off": "fr"})
    assert AS.AppSettings().perception_languages_off == []
