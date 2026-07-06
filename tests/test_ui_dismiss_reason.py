"""
Wave 3 H — optional dismiss-with-reason for Home Leads.

Dismissing a Lead now offers a small chip set + free-text reason, POSTed to
POST /api/signals/dismiss-reason ({card_id, reason, card_type}). The reason is recorded
SEPARATELY from the dismissed-id set, so the unchanged dismissal mechanic
(POST /api/briefing/dismiss) never depends on it — a blank reason is a valid skip.

Browser-unverified per fork-3 — node-checked + grep-guarded here.
"""

from __future__ import annotations

from tests.test_repo_invariants import _ui_source


def test_dismiss_reason_endpoint_and_helpers_wired():
    ui = _ui_source()
    assert "/api/signals/dismiss-reason" in ui, "dismiss must POST the reason endpoint"
    assert "_leadDismissReasons" in ui, "the reason chip set must exist"
    assert "_leadDismissWith" in ui, "a reason→dismiss helper must exist"
    assert "card_id" in ui and "card_type" in ui, "the payload must carry card_id + card_type"


def test_dismissed_id_mechanic_is_unchanged():
    ui = _ui_source()
    # The reason is recorded separately; the dismissed-id POST is unchanged and still runs.
    assert "_dismissCardNow" in ui, "the unchanged dismissed-id mechanic must be a helper"
    assert "/api/briefing/dismiss" in ui, "the dismissed-id endpoint must still be called"


def test_dismiss_button_passes_the_card_type():
    ui = _ui_source()
    # The card-back Dismiss button hands both id and type to dismissCard(id, type).
    assert "dismissCard(" in ui, "the dismiss button must call dismissCard"
    assert "c.type" in ui, "the card type must flow to the reason payload"


def test_dismiss_reason_offers_chips_and_free_text():
    ui = _ui_source()
    assert "lead-dreason-text" in ui, "a free-text reason input must exist"
    assert '"not-relevant"' in ui or "'not-relevant'" in ui, "a stable reason chip key must exist"
