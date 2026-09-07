"""
The §18 export-privacy enumeration — what a reader of an exported file can see.

Owed before a first evidence archive leaves a machine. The property that matters
is not that the list exists but that it is HONEST about the two states people
confuse: an item measured and absent, and an item nobody measured. A privacy note
that reports the second as the first is a fabricated all-clear on a file somebody
is about to hand to someone else.

The negative-space lens is most of this file: a corpus with no newsletters, no
synthetic URIs and no signature must produce a note that says so — and the SAME
call without the article population must say NOT MEASURED for exactly those items
rather than repeating the clean answer.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.bulletin import privacy as P
from src.bulletin.period import resolve_period
from src.database.models import Article, Base, Source

_P = resolve_period("weekly", end=date(2026, 8, 1))


def _corpus(*, newsletters: int = 0, hazards: int = 0, plain: int = 3):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = Session(engine)
    news = Source(name="Alpha", domain="alpha.test", country="fr", source_type="news")
    mail = Source(
        name="Imported newsletters (.eml)",
        domain="newsletters.import.local",
        source_type="newsletter",
    )
    s.add_all([news, mail])
    s.flush()
    i = 0
    ids: list[int] = []

    def _add(src, url, title):
        nonlocal i
        i += 1
        a = Article(
            url=url,
            canonical_url=url,
            source_id=src.id,
            title=title,
            content="body",
            hash=f"{i:064d}",
            language="fr",
            published_at=datetime.fromisoformat("2026-07-27 12:00:00"),
        )
        s.add(a)
        s.flush()
        ids.append(int(a.id))

    for n in range(plain):
        _add(news, f"https://alpha.test/{n}", f"Article {n}")
    for n in range(newsletters):
        _add(mail, f"https://newsletters.import.local/{n}", f"Your weekly digest #{n}")
    for n in range(hazards):
        _add(news, f"hazard://usgs/{n}", f"M 5.{n} earthquake")
    s.commit()
    return s, ids


_EDITION = {
    "masthead": {
        "sources_contributing": 2,
        "corpus_articles": 4321,
        "top_sources": [{"name": "Alpha", "domain": "alpha.test", "articles": 3}],
    }
}


def _items(report):
    return {i["key"]: i for i in report["items"]}


# --------------------------------------------------------------------------- #
#  every §18 item is enumerated, for every artifact
# --------------------------------------------------------------------------- #
def test_every_section_18_item_is_named_for_every_export_kind():
    """§18's list is the contract. An item quietly dropped from one artifact is the
    one an operator would never learn to ask about."""
    session, ids = _corpus()
    expected = {
        "source_names_and_domains",
        "article_ids_and_corpus_totals",
        "app_version",
        "newsletter_subject_lines",
        "synthetic_uris",
        "signing_key",
        "timestamps_and_timezone",
        "publisher_full_text",
    }
    for kind in P.KINDS:
        report = P.export_privacy(session, _EDITION, kind=kind, article_ids=ids)
        assert set(_items(report)) == expected, kind


def test_an_unknown_kind_is_refused_rather_than_answered_generically():
    session, ids = _corpus()
    with pytest.raises(ValueError):
        P.export_privacy(session, _EDITION, kind="email", article_ids=ids)


# --------------------------------------------------------------------------- #
#  the tri-state: measured-there, measured-absent, NOT measured
# --------------------------------------------------------------------------- #
def test_a_corpus_with_no_newsletters_reports_absent_with_a_zero_count():
    session, ids = _corpus(newsletters=0)
    item = _items(P.export_privacy(session, _EDITION, kind="annexes", article_ids=ids))[
        "newsletter_subject_lines"
    ]
    assert item["present"] is False
    assert item["n"] == 0


def test_the_same_question_with_no_population_is_NOT_MEASURED_not_absent():
    """THE ONE THAT MATTERS. Without the article set the answer is unknown, and an
    unknown reported as False tells an operator that something is not in a file they
    are about to send."""
    session, _ = _corpus(newsletters=0)
    report = P.export_privacy(session, _EDITION, kind="annexes", article_ids=None)
    item = _items(report)["newsletter_subject_lines"]
    assert item["present"] is None
    assert "not measured" in item["basis"]
    assert "n" not in item, "an unmeasured item must not publish a count at all"
    assert "newsletter_subject_lines" in report["unmeasured"]
    assert report["articles_measured"] is None


def test_the_unmeasured_items_are_named_and_counted_apart():
    session, _ = _corpus()
    report = P.export_privacy(session, _EDITION, kind="evidence", article_ids=None)
    assert report["unmeasured_count"] == len(report["unmeasured"]) > 0
    assert set(report["unmeasured"]) == {"newsletter_subject_lines", "synthetic_uris"}


def test_a_newsletter_in_the_set_is_reported_present_with_its_subject_line():
    session, ids = _corpus(newsletters=2)
    item = _items(P.export_privacy(session, _EDITION, kind="annexes", article_ids=ids))[
        "newsletter_subject_lines"
    ]
    assert item["present"] is True
    assert item["n"] == 2
    assert any("weekly digest" in e for e in item["examples"])
    assert item["examples_are_bounded"] is True


def test_the_newsletter_count_is_not_multiplied_by_the_number_of_sources():
    """A predicate over Source with no join is a cartesian product, and the number it
    returns still looks plausible. Two newsletters across a two-source corpus is 2,
    never 4."""
    session, ids = _corpus(newsletters=2, plain=3)
    item = _items(P.export_privacy(session, _EDITION, kind="evidence", article_ids=ids))[
        "newsletter_subject_lines"
    ]
    assert item["n"] == 2


def test_a_synthetic_uri_is_found_and_the_count_is_stated_as_a_floor():
    session, ids = _corpus(hazards=2)
    item = _items(P.export_privacy(session, _EDITION, kind="evidence", article_ids=ids))[
        "synthetic_uris"
    ]
    assert item["present"] is True
    assert item["n"] == 2
    assert "FLOOR" in item["basis"], (
        "a count from a fixed vocabulary is a floor; implying a total would make a "
        "scheme added later read as absent"
    )


def test_a_corpus_with_no_synthetic_uris_reports_absent():
    session, ids = _corpus(hazards=0)
    item = _items(P.export_privacy(session, _EDITION, kind="evidence", article_ids=ids))[
        "synthetic_uris"
    ]
    assert item["present"] is False and item["n"] == 0


# --------------------------------------------------------------------------- #
#  the artifacts differ, and the note says how
# --------------------------------------------------------------------------- #
def test_the_published_report_carries_no_local_article_ids():
    """§9.2: a local id resolves to a DIFFERENT article on a recipient's install, so
    the published document links externally and names none."""
    session, ids = _corpus()
    report = _items(P.export_privacy(session, _EDITION, kind="report", article_ids=ids))
    assert report["article_ids_and_corpus_totals"]["present"] is False
    assert report["article_ids_and_corpus_totals"]["n"] == 4321, (
        "the corpus TOTAL still travels — it is in the masthead of every export"
    )


def test_the_files_do_carry_local_article_ids():
    session, ids = _corpus()
    for kind in ("annexes", "evidence"):
        item = _items(P.export_privacy(session, _EDITION, kind=kind, article_ids=ids))[
            "article_ids_and_corpus_totals"
        ]
        assert item["present"] is True, kind


def test_full_text_is_reported_per_artifact_and_follows_the_annexes_flag():
    session, ids = _corpus()

    def full(kind, **kw):
        return _items(
            P.export_privacy(session, _EDITION, kind=kind, article_ids=ids, **kw)
        )["publisher_full_text"]

    assert full("report")["present"] is False
    assert full("evidence")["present"] is True
    assert full("annexes", full_text=True)["present"] is True
    assert full("annexes", full_text=False)["present"] is False


def test_the_full_text_item_states_the_publishers_terms_question_without_answering_it():
    """The maintainer's to rule on. This app says the text is there and stops."""
    session, ids = _corpus()
    item = _items(P.export_privacy(session, _EDITION, kind="evidence", article_ids=ids))[
        "publisher_full_text"
    ]
    assert "publisher" in item["why_it_matters"] and "terms" in item["why_it_matters"]
    assert "does not answer it" in item["why_it_matters"]


# --------------------------------------------------------------------------- #
#  app version and signing key: measured, not assumed
# --------------------------------------------------------------------------- #
def test_the_app_version_is_checked_against_the_record_not_assumed():
    session, ids = _corpus()
    absent = _items(P.export_privacy(session, _EDITION, kind="report", article_ids=ids))
    assert absent["app_version"]["present"] is False
    assert "checked rather than assumed" in absent["app_version"]["basis"]

    present = _items(
        P.export_privacy(
            session, dict(_EDITION, app_version="0.3.0"), kind="report", article_ids=ids
        )
    )
    assert present["app_version"]["present"] is True
    assert "0.3.0" in present["app_version"]["basis"]


def test_the_signing_key_item_states_the_condition_that_would_change_its_answer():
    """Nothing signs a bulletin today. The item exists so that whoever adds a
    signature meets §18's requirement rather than rediscovering it."""
    session, ids = _corpus()
    item = _items(P.export_privacy(session, _EDITION, kind="evidence", article_ids=ids))[
        "signing_key"
    ]
    assert item["present"] is False
    assert "IF signing is ever added" in item["basis"]
    assert "ephemeral" in item["basis"]


# --------------------------------------------------------------------------- #
#  it reaches the operator, and it travels inside the file
# --------------------------------------------------------------------------- #
def test_the_evidence_plan_carries_the_enumeration_before_anything_is_written():
    """The plan step exists so the operator decides with the real numbers in front of
    them. Stating this afterwards would be stating it after the decision."""
    from src.bulletin.evidence import evidence_plan

    session, _ = _corpus(newsletters=1)
    plan = evidence_plan(session, _P)
    assert plan["privacy"]["kind"] == "evidence"
    assert _items(plan["privacy"])["newsletter_subject_lines"]["present"] is True


def test_the_evidence_archive_carries_the_note_as_a_file(tmp_path):
    import zipfile

    from src.bulletin.evidence import build_evidence_archive

    session, _ = _corpus(newsletters=1)
    out = build_evidence_archive(session, _EDITION, _P, tmp_path)
    with zipfile.ZipFile(out["path"]) as zf:
        assert "WHAT-A-READER-CAN-SEE.md" in zf.namelist()
        text = zf.read("WHAT-A-READER-CAN-SEE.md").decode("utf-8")
    assert "What a reader of this file can see" in text
    assert "subject line" in text
    # And the contents page names it, so a reader browsing the ZIP finds it.
    with zipfile.ZipFile(out["path"]) as zf:
        assert "WHAT-A-READER-CAN-SEE.md" in zf.read("README.md").decode("utf-8")


def test_the_markdown_prints_NOT_MEASURED_rather_than_a_blank_cell():
    """A blank cell in a table reads as "no". The one thing this note must never do
    is let an unanswered question look like a clean answer."""
    session, _ = _corpus()
    md = P.privacy_markdown(
        P.export_privacy(session, _EDITION, kind="evidence", article_ids=None)
    )
    assert "NOT MEASURED" in md
    assert "An unanswered question is not a clean answer." in md


def test_the_markdown_prints_a_count_beside_a_present_item():
    session, ids = _corpus(newsletters=3)
    md = P.privacy_markdown(
        P.export_privacy(session, _EDITION, kind="evidence", article_ids=ids)
    )
    assert "yes (3)" in md


def test_no_score_shaped_key_in_the_payload():
    import json

    session, ids = _corpus(newsletters=1, hazards=1)
    out = P.export_privacy(session, _EDITION, kind="evidence", article_ids=ids)
    flat = json.dumps(out, default=str).lower()
    for banned in ("score", "ranking", "rating", "grade"):
        assert f'"{banned}"' not in flat and f'_{banned}"' not in flat


def test_quarantined_articles_are_counted_rather_than_reported_as_zero_when_unreadable():
    """A None here means unreadable, and it must never be a 0 — an excluded set of
    unknown size and an empty one are different facts."""
    session, _ = _corpus()
    assert P.quarantined_in_period(session, _P) == 0

    class _Broken:
        def query(self, *a, **k):
            raise RuntimeError("no such table")

    assert P.quarantined_in_period(_Broken(), _P) is None
