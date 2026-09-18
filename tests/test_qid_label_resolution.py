"""Q1116: a bare Wikidata Q-id as a NAME — resolve at the polite rate, or decline the row.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Institutions C8: 26 of 267 verified rows (9.7 %) carry a bare Q-id where their name should
be, so splicing them as they stand would put `Q133293483` in the catalogue as a source name.

THE RULING TAKES BOTH HALVES — resolve, **or decline to admit the row** — and the second is
not a fallback. An unresolved row is never admitted under its identifier and never under a
guess; it is declined with a reason and left for a later pass.

THIS IS THE ONE PIECE OF S3 THAT TOUCHES THE NETWORK, so most of what follows is about what
the network half owes: the polite rate asserted by COUNTING (never by watching a clock), one
consent for the batch rather than one per row, and a refusal that NAMES the kill switch —
because a probe once reported airplane mode as "size check failed" and sent an operator to
look at somebody else's server for their own setting (invariant #14e's corollary). No test
here opens a socket: `fetch` and `sleep` are injected, which makes the rate checkable rather
than merely plausible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.analytics.wikidata_rings import POLITE_SLEEP_S
from src.catalog.qid_labels import (
    DECLINED_NO_LABEL,
    DECLINED_REFUSED,
    DECLINED_UNRESOLVED,
    AirplaneRefusal,
    admit_or_decline,
    bare_qid_rows,
    looks_like_bare_qid,
    resolve_labels,
)


def _entity(qid: str, labels: dict[str, str]) -> dict:
    return {"entities": {qid: {"labels": {k: {"value": v} for k, v in labels.items()}}}}


def _fetcher(table: dict[str, dict]):
    """A fetch that answers from a table and records the URLs it was asked for."""
    asked: list[str] = []

    def fetch(url: str) -> dict:
        asked.append(url)
        qid = url.split("ids=")[1].split("&")[0]
        if qid not in table:
            raise RuntimeError("not found")
        return _entity(qid, table[qid])

    return fetch, asked


# --------------------------------------------------------------------------- #
# What counts as a bare identifier
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("name", "bare"),
    [
        ("Q133293483", True), ("q42", True), ("  Q7  ", True),
        ("Q42 Douglas Adams", False),   # already carries the label the ruling is about
        ("Ville de Québec", False), ("Quebec", False),
        ("", False), (None, False),
        ("Q", False), ("QQ12", False),
    ],
)
def test_only_a_bare_identifier_matches(name, bare) -> None:
    """`Q42 Douglas Adams` is the case that must NOT match: it is a name that happens to
    begin with an identifier, and renaming it would destroy the label C8 is asking for."""
    assert looks_like_bare_qid(name) is bare


def test_bare_qid_rows_normalises_without_touching_the_others() -> None:
    rows = [(1, "Q133293483"), (2, "Ville de Québec"), (3, " q42 "), (4, None)]
    assert bare_qid_rows(rows) == [(1, "Q133293483"), (3, "Q42")]


# --------------------------------------------------------------------------- #
# The polite rate, counted
# --------------------------------------------------------------------------- #
def test_the_rate_is_at_most_one_request_per_ten_seconds() -> None:
    """R8, asserted by counting sleeps rather than by watching a clock — a wall-clock check
    would either be slow or be a race. n requests must carry n-1 full intervals."""
    table = {f"Q{i}": {"en": f"Body {i}"} for i in range(1, 6)}
    fetch, asked = _fetcher(table)
    naps: list[float] = []

    out = resolve_labels(list(table), fetch=fetch, sleep=naps.append,
                         kill_switch=lambda: False)

    assert out["requests"] == len(table) == len(asked)
    assert naps == [POLITE_SLEEP_S] * (len(table) - 1), (
        f"expected {len(table) - 1} intervals of {POLITE_SLEEP_S}s, got {naps}"
    )
    assert POLITE_SLEEP_S >= 10.0, "R8 is <= 1 request / 10 s"


def test_the_interval_is_imported_not_restated() -> None:
    """A rate two callers each hold their own copy of is a rate one of them will quietly
    relax — the ring builder's own words, and the reason this module imports it."""
    src = Path("src/catalog/qid_labels.py").read_text(encoding="utf-8")
    assert "from src.analytics.wikidata_rings import" in src
    assert "POLITE_SLEEP_S" in src
    assert "= 10.0" not in src, "the polite interval was restated instead of imported"


def test_a_duplicate_qid_costs_one_request_not_two() -> None:
    """Politeness is about requests made, not rows processed."""
    fetch, asked = _fetcher({"Q1": {"en": "One"}})
    out = resolve_labels(["Q1", "q1", " Q1 "], fetch=fetch, sleep=lambda _s: None,
                         kill_switch=lambda: False)
    assert len(asked) == 1 and out["requests"] == 1
    assert out["labels"] == {"Q1": "One"}


# --------------------------------------------------------------------------- #
# The refusal, named as itself
# --------------------------------------------------------------------------- #
def test_airplane_mode_refuses_by_name_before_any_request() -> None:
    """Invariant #14e's corollary. A generic failure here sends an operator to look at
    Wikidata for a setting of their own."""
    fetch, asked = _fetcher({"Q1": {"en": "One"}})
    with pytest.raises(AirplaneRefusal) as exc:
        resolve_labels(["Q1"], fetch=fetch, sleep=lambda _s: None, kill_switch=lambda: True)
    assert "airplane mode" in str(exc.value)
    assert asked == [], "a request was built before the refusal"
    # ...and it says what did NOT happen, so nobody reads the refusal as a decline.
    assert "no row was declined" in str(exc.value)


def test_engaging_airplane_mode_MID_RUN_stops_the_run_and_declines_the_rest() -> None:
    """A start-only check would keep fetching for four more minutes on a 26-row run that
    sleeps ten seconds between requests. The operator engaged the switch; the run stops."""
    table = {f"Q{i}": {"en": f"Body {i}"} for i in range(1, 6)}
    fetch, asked = _fetcher(table)
    calls = {"n": 0}

    def kill_switch() -> bool:
        calls["n"] += 1
        return calls["n"] > 3   # clear for the first rows, engaged partway through

    out = resolve_labels(list(table), fetch=fetch, sleep=lambda _s: None,
                         kill_switch=kill_switch)

    assert 0 < len(asked) < len(table), f"the run did not stop partway: {asked}"
    assert out["declined"], "the unreached rows must be declined, not silently dropped"
    assert set(out["declined"].values()) == {DECLINED_REFUSED}
    assert len(out["labels"]) + len(out["declined"]) == len(table), (
        "every row must end in exactly one of the two buckets"
    )


# --------------------------------------------------------------------------- #
# Resolve, or decline — never a guess
# --------------------------------------------------------------------------- #
def test_a_label_in_any_language_beats_declining_the_row() -> None:
    """English is not privileged. A Czech municipality that Wikidata knows only in Czech gets
    its Czech name — naming it in English would be the anglicising failure the ring builder
    documents, and declining it would lose a real row for having the wrong language."""
    fetch, _ = _fetcher({"Q1": {"cs": "Dolní Lhota"}, "Q2": {"ar": "وزارة الصحة"}})
    out = resolve_labels(["Q1", "Q2"], fetch=fetch, sleep=lambda _s: None,
                         kill_switch=lambda: False)
    assert out["labels"] == {"Q1": "Dolní Lhota", "Q2": "وزارة الصحة"}
    assert out["declined"] == {}


def test_an_item_with_no_label_at_all_is_declined_as_ITSELF() -> None:
    """'We could not reach Wikidata' and 'Wikidata has no label' are different facts: a later
    pass can act on the first, and only a person can act on the second."""
    def fetch(url: str) -> dict:
        return _entity(url.split("ids=")[1].split("&")[0], {})

    out = resolve_labels(["Q9"], fetch=fetch, sleep=lambda _s: None, kill_switch=lambda: False)
    assert out["labels"] == {}
    assert out["declined"] == {"Q9": DECLINED_NO_LABEL}
    assert out["declined"]["Q9"] != DECLINED_UNRESOLVED


def test_a_failed_lookup_declines_one_row_and_never_aborts_the_batch() -> None:
    fetch, _ = _fetcher({"Q1": {"en": "One"}, "Q3": {"en": "Three"}})  # Q2 absent -> raises
    out = resolve_labels(["Q1", "Q2", "Q3"], fetch=fetch, sleep=lambda _s: None,
                         kill_switch=lambda: False)
    assert out["labels"] == {"Q1": "One", "Q3": "Three"}
    assert out["declined"] == {"Q2": DECLINED_UNRESOLVED}


def test_an_unresolved_row_is_declined_never_admitted_under_its_identifier() -> None:
    """THE SECOND HALF OF THE RULING, which is the half that protects the catalogue: the
    failure mode is a source called `Q133293483`, and it must be impossible."""
    rows = [(1, "Q1"), (2, "Q2"), (3, "Ville de Québec")]
    out = admit_or_decline(rows, {"Q1": "Dolní Lhota"})

    names = [a["name"] for a in out["admitted"]]
    assert "Dolní Lhota" in names
    assert "Ville de Québec" in names, "a row that was never a bare id must pass untouched"
    assert not any(looks_like_bare_qid(n) for n in names), (
        f"an identifier reached the catalogue as a name: {names}"
    )
    assert [d["qid"] for d in out["declined"]] == ["Q2"]
    assert "not discarded" in out["declined"][0]["detail"]


def test_the_endpoint_refuses_under_the_kill_switch_with_a_named_409(monkeypatch) -> None:
    """Driven through the real route. The refusal must be a 409 naming the kill switch, and
    it must arrive before anything is fetched."""
    from fastapi.testclient import TestClient

    import src.api.source_management as sm
    from src.api.main import app
    from src.ingest import activate_kill_switch, clear_kill_switch

    def _explode(url: str):  # noqa: ANN202 - a fetch here is the failure
        raise AssertionError("a request was made under airplane mode")

    monkeypatch.setattr("src.catalog.wikidata_apply._default_getter", _explode)
    assert sm.resolve_qid_names is not None
    activate_kill_switch()
    try:
        with TestClient(app) as c:
            r = c.post("/api/sources/resolve-qid-names")
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert "airplane mode" in detail
        assert "wikidata" in detail.lower(), "the refusal must say what it did not reach"
    finally:
        clear_kill_switch()
