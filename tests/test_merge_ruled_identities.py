"""The five tables whose cross-corpus identity the schema could not answer.

WHY THESE WERE LEFT UNMERGED. ``sources`` has a unique constraint on ``domain``, so "the
same source" is a question the schema already answers and the 2026-08-03 handlers for
``stat_figures`` and its three siblings could be written without asking anyone. These five
have no unique constraint at all: nothing anywhere records what makes two of them "the
same thing". Guessing has two failure modes and both are bad -- guess one way and every
merge DUPLICATES (merge 8 instances, get 8 copies, and it doubles again next time); guess
the other and every merge silently OVERWRITES or DROPS, with no error to notice.

So they were reported-but-not-merged with their questions stated, and the maintainer ruled
all five on 2026-08-03:

    watches                 identity = NAME
    watch_matches           follows watches: (that watch, when it fired)
    ai_custom_prompt        identity = (output_kind, prompt_text)   [not the label]
    ai_keyword              identity = (article, kind, term, model)
    law_revision_summaries  identity = (revision, model)

These tests pin each ruling in BOTH directions -- a row that differs in a field the ruling
puts INSIDE the identity must survive as two rows, and one that differs only in a field the
ruling leaves OUT must collapse to one. A test that only checked "it arrives" would pass
just as happily under the opposite ruling.

Every case runs the real ``merge_corpus`` over two real corpora. A self-restore cannot
exercise a merge at all -- every row reads as a duplicate, so no INSERT runs -- which is
the same reason the gap survived the field run that found it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup.merge import merge_corpus  # noqa: E402
from src.database.models import (  # noqa: E402
    AiCustomPrompt,
    AiKeyword,
    Article,
    Base,
    LawDocument,
    LawRevision,
    LawRevisionSummary,
    Source,
    Watch,
    WatchMatch,
)

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}

_T0 = datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC).replace(tzinfo=None)
_T1 = _T0 + timedelta(days=1)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _merge(tmp_path: Path, incoming, local=None) -> Path:
    """Populate an incoming and (optionally) a local corpus, merge, return the local path."""
    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        incoming(s)
        s.commit()
    sess = _corpus(working)
    if local is not None:
        with sess() as s:
            local(s)
            s.commit()
    merge_corpus(staged, working, _BATCH_META)
    return working


def _article(s, *, hash_: str = "h1", url: str = "https://ex.example/a") -> Article:
    src = s.query(Source).filter_by(domain="ex.example").one_or_none()
    if src is None:
        src = Source(name="Ex", domain="ex.example")
        s.add(src)
        s.flush()
    art = Article(url=url, canonical_url=url, source_id=src.id, title="T",
                  content="body", hash=hash_)
    s.add(art)
    s.flush()
    return art


def _watch(s, name: str, *, query: str = "sahel", window: int = 7) -> Watch:
    w = Watch(name=name, query=query, threshold=3, window_days=window)
    s.add(w)
    s.flush()
    return w


def _law_revision(s, *, content_hash: str = "ch-1") -> LawRevision:
    doc = s.query(LawDocument).filter_by(url="https://ex.example/code").one_or_none()
    if doc is None:
        doc = LawDocument(jurisdiction="fr", title="Code", url="https://ex.example/code")
        s.add(doc)
        s.flush()
    rev = LawRevision(document_id=doc.id, observed_at=_T0, content_hash=content_hash)
    s.add(rev)
    s.flush()
    return rev


# --------------------------------------------------------------------------- #
#  1. watches -- identity = NAME
# --------------------------------------------------------------------------- #
def test_a_watch_arrives_on_a_fresh_install(tmp_path):
    """The baseline hole: a saved condition is hand-authored content the app cannot
    recompute, and a fresh-install restore dropped it entirely."""
    with _corpus(_merge(tmp_path, lambda s: _watch(s, "Sahel coverage")))() as s:
        got = s.query(Watch).one()
        assert got.name == "Sahel coverage"
        assert got.query == "sahel"
        assert got.threshold == 3
        assert got.window_days == 7


def test_the_same_watch_name_on_two_machines_stays_one_watch(tmp_path):
    """THE ruling, forward. Identity is the name, so merging a machine that holds the same
    watch does not give the user a second copy of it."""
    working = _merge(
        tmp_path,
        lambda s: _watch(s, "Sahel coverage", window=14),   # incoming: window tweaked
        lambda s: _watch(s, "Sahel coverage", window=7),    # local: the original
    )
    with _corpus(working)() as s:
        rows = s.query(Watch).all()
        assert len(rows) == 1, "a window tweak on another machine created a second watch"
        assert rows[0].window_days == 7, "local wins -- the merge never overwrites what is here"


def test_a_watch_with_a_different_name_is_a_different_watch(tmp_path):
    """THE ruling, backward -- and the case that discriminates it from condition-identity.

    These two rows have an IDENTICAL query, threshold and window; only the name differs.
    Under the rejected condition-tuple identity they would collapse into one and the
    user would lose a watch they deliberately created. Under the ruled name identity both
    survive, which is the outcome the ruling chose: an unwanted extra row is visible in
    the list and one click from deleted, whereas a silently swallowed one is neither.
    """
    working = _merge(
        tmp_path,
        lambda s: _watch(s, "Sahel — daily", query="sahel", window=7),
        lambda s: _watch(s, "Sahel coverage", query="sahel", window=7),
    )
    with _corpus(working)() as s:
        assert {w.name for w in s.query(Watch).all()} == {"Sahel — daily", "Sahel coverage"}


# --------------------------------------------------------------------------- #
#  2. watch_matches -- follows the watch, keyed on when it fired
# --------------------------------------------------------------------------- #
def test_watch_history_arrives_and_points_at_the_right_local_watch(tmp_path):
    """The remap is the load-bearing part: ``watch_id`` is an id in the OTHER corpus, and
    carrying it verbatim would attach the history to whatever local watch happens to hold
    that number -- or to none at all."""
    def incoming(s):
        # Two watches, so a naive id carry-over has something wrong to point at.
        _watch(s, "Decoy")
        w = _watch(s, "Sahel coverage")
        s.add(WatchMatch(watch_id=w.id, matched_at=_T0, n_articles=9, new_articles=4,
                         article_ids="[1,2,3]"))

    def local(s):
        _watch(s, "Sahel coverage")  # exists here already, with a different local id

    with _corpus(_merge(tmp_path, incoming, local))() as s:
        target = s.query(Watch).filter_by(name="Sahel coverage").one()
        match = s.query(WatchMatch).one()
        assert match.watch_id == target.id, "the firing was attached to the wrong watch"
        assert match.n_articles == 9
        assert match.new_articles == 4


def test_two_firings_of_one_watch_both_survive_and_a_re_import_does_not_double_them(tmp_path):
    """Both directions at once: distinct firing times are distinct events, and the same
    backup imported twice must not multiply the history."""
    def incoming(s):
        w = _watch(s, "Sahel coverage")
        s.add(WatchMatch(watch_id=w.id, matched_at=_T0, n_articles=9, new_articles=4))
        s.add(WatchMatch(watch_id=w.id, matched_at=_T1, n_articles=12, new_articles=3))

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        incoming(s)
        s.commit()
    _corpus(working)
    merge_corpus(staged, working, _BATCH_META)
    merge_corpus(staged, working, _BATCH_META)  # the same artifact, twice

    with _corpus(working)() as s:
        assert s.query(WatchMatch).count() == 2, "re-importing one backup duplicated history"
        assert {m.n_articles for m in s.query(WatchMatch).all()} == {9, 12}


# --------------------------------------------------------------------------- #
#  3. ai_custom_prompt -- identity = (output_kind, prompt_text)
# --------------------------------------------------------------------------- #
def test_an_edited_prompt_arrives_as_a_second_row(tmp_path):
    """THE ruling, and the reason the maintainer overrode the label recommendation.

    Under label-identity plus the standing local-wins policy, a prompt improved on a
    secondary machine could never travel: the local row would win and the better text
    would be discarded with nothing said. Keying on the text makes the improvement arrive
    as a row the user can see, compare and keep.
    """
    def incoming(s):
        s.add(AiCustomPrompt(label="Figures", output_kind="figure",
                             prompt_text="Extract every figure WITH its unit."))

    def local(s):
        s.add(AiCustomPrompt(label="Figures", output_kind="figure",
                             prompt_text="Extract every figure."))

    with _corpus(_merge(tmp_path, incoming, local))() as s:
        texts = {p.prompt_text for p in s.query(AiCustomPrompt).all()}
        assert texts == {"Extract every figure.", "Extract every figure WITH its unit."}


def test_the_same_prompt_text_under_a_different_label_stays_one_extractor(tmp_path):
    """The other direction. Two machines that renamed the same extractor differently must
    not leave the user with two rows doing character-for-character the same thing."""
    def incoming(s):
        s.add(AiCustomPrompt(label="Figures v2", output_kind="figure",
                             prompt_text="Extract every figure."))

    def local(s):
        s.add(AiCustomPrompt(label="Figures", output_kind="figure",
                             prompt_text="Extract every figure."))

    with _corpus(_merge(tmp_path, incoming, local))() as s:
        rows = s.query(AiCustomPrompt).all()
        assert len(rows) == 1, "a rename created a duplicate extractor"
        assert rows[0].label == "Figures", "local wins"


def test_the_same_text_producing_a_different_kind_is_a_different_extractor(tmp_path):
    """``output_kind`` is in the key because it is the metadata TYPE produced: the same
    instruction pointed at a different output really is a different extractor."""
    def incoming(s):
        s.add(AiCustomPrompt(label="X", output_kind="statute", prompt_text="Extract."))

    def local(s):
        s.add(AiCustomPrompt(label="X", output_kind="figure", prompt_text="Extract."))

    with _corpus(_merge(tmp_path, incoming, local))() as s:
        assert {p.output_kind for p in s.query(AiCustomPrompt).all()} == {"figure", "statute"}


# --------------------------------------------------------------------------- #
#  4. ai_keyword -- identity = (article, kind, term, model)
# --------------------------------------------------------------------------- #
def test_two_models_reading_the_same_article_both_survive(tmp_path):
    """THE ruling's forward half. Two independent models naming the same entity is
    evidence in its own right, so the model is IN the identity and both readings keep."""
    def incoming(s):
        art = _article(s)
        s.add(AiKeyword(article_id=art.id, term="Angela Merkel", kind="who", model="mistral"))
        s.add(AiKeyword(article_id=art.id, term="Angela Merkel", kind="who", model="ministral"))

    with _corpus(_merge(tmp_path, incoming))() as s:
        rows = s.query(AiKeyword).all()
        assert len(rows) == 2
        assert {r.model for r in rows} == {"mistral", "ministral"}


def test_one_model_re_run_under_a_new_prompt_version_does_not_duplicate(tmp_path):
    """THE ruling's backward half, and the case that discriminates it from the rejected
    (…, model, prompt_version) key. This is the largest of the five tables: including the
    prompt version would double EVERY term in the corpus on each prompt re-tune. What it
    costs is knowing which prompt revision said it -- the least load-bearing part of the
    record, and the stated trade."""
    def incoming(s):
        art = _article(s)
        s.add(AiKeyword(article_id=art.id, term="Angela Merkel", kind="who",
                        model="mistral", prompt_version="v2"))

    def local(s):
        art = _article(s)
        s.add(AiKeyword(article_id=art.id, term="Angela Merkel", kind="who",
                        model="mistral", prompt_version="v1"))

    with _corpus(_merge(tmp_path, incoming, local))() as s:
        rows = s.query(AiKeyword).all()
        assert len(rows) == 1, "a prompt re-tune duplicated the AI metadata layer"
        assert rows[0].prompt_version == "v1", "local wins"


def test_the_same_term_in_a_different_kind_is_a_different_row(tmp_path):
    """A place called Merkel and a person called Merkel are not one fact."""
    def incoming(s):
        art = _article(s)
        s.add(AiKeyword(article_id=art.id, term="Berlin", kind="who", model="mistral"))
        s.add(AiKeyword(article_id=art.id, term="Berlin", kind="place", model="mistral"))

    with _corpus(_merge(tmp_path, incoming))() as s:
        assert {r.kind for r in s.query(AiKeyword).all()} == {"who", "place"}


def test_ai_metadata_attaches_to_the_right_local_article(tmp_path):
    """``article_id`` is remapped through map_articles like every other article child --
    the incoming corpus's ids mean nothing here."""
    def incoming(s):
        _article(s, hash_="h-decoy", url="https://ex.example/decoy")
        art = _article(s, hash_="h-target", url="https://ex.example/target")
        s.add(AiKeyword(article_id=art.id, term="Sahel", kind="place", model="mistral"))

    def local(s):
        _article(s, hash_="h-target", url="https://ex.example/target")

    with _corpus(_merge(tmp_path, incoming, local))() as s:
        target = s.query(Article).filter_by(hash="h-target").one()
        assert s.query(AiKeyword).one().article_id == target.id


# --------------------------------------------------------------------------- #
#  5. law_revision_summaries -- identity = (revision, model)
# --------------------------------------------------------------------------- #
def test_two_models_summaries_of_one_law_change_sit_side_by_side(tmp_path):
    """THE ruling. Comparing two readings of the same legal change is the point, and the
    table is small enough that keeping both costs nothing."""
    def incoming(s):
        rev = _law_revision(s)
        s.add(LawRevisionSummary(revision_id=rev.id, summary="A", model="mistral"))
        s.add(LawRevisionSummary(revision_id=rev.id, summary="B", model="ministral"))

    with _corpus(_merge(tmp_path, incoming))() as s:
        rows = s.query(LawRevisionSummary).all()
        assert {r.model for r in rows} == {"mistral", "ministral"}
        assert {r.summary for r in rows} == {"A", "B"}


def test_one_models_resummary_replaces_rather_than_accumulates(tmp_path):
    """The excluded half: ``prompt_version`` is not in the key, so re-running one model
    under a tuned prompt updates in place instead of stacking summaries."""
    def incoming(s):
        rev = _law_revision(s)
        s.add(LawRevisionSummary(revision_id=rev.id, summary="newer", model="mistral",
                                 prompt_version="v2"))

    def local(s):
        rev = _law_revision(s)
        s.add(LawRevisionSummary(revision_id=rev.id, summary="older", model="mistral",
                                 prompt_version="v1"))

    with _corpus(_merge(tmp_path, incoming, local))() as s:
        rows = s.query(LawRevisionSummary).all()
        assert len(rows) == 1
        assert rows[0].summary == "older", "local wins"


def test_a_summary_attaches_to_the_right_local_revision(tmp_path):
    """The revision id map is built on (document, content_hash) -- the only key that
    identifies a revision across corpora."""
    def incoming(s):
        _law_revision(s, content_hash="ch-decoy")
        rev = _law_revision(s, content_hash="ch-target")
        s.add(LawRevisionSummary(revision_id=rev.id, summary="S", model="mistral"))

    def local(s):
        _law_revision(s, content_hash="ch-target")

    with _corpus(_merge(tmp_path, incoming, local))() as s:
        target = s.query(LawRevision).filter_by(content_hash="ch-target").one()
        assert s.query(LawRevisionSummary).one().revision_id == target.id


# --------------------------------------------------------------------------- #
#  The report
# --------------------------------------------------------------------------- #
def test_the_restore_report_no_longer_lists_the_five_as_unmerged(tmp_path):
    """They were in the "reported-but-not-merged" middle state, which reads as
    intentional. Now they are merged, so the report must stop naming them -- otherwise
    the operator's own evidence still says the data was dropped."""
    def incoming(s):
        art = _article(s)
        w = _watch(s, "W")
        s.add(WatchMatch(watch_id=w.id, matched_at=_T0, n_articles=1, new_articles=1))
        s.add(AiCustomPrompt(label="P", output_kind="figure", prompt_text="X"))
        s.add(AiKeyword(article_id=art.id, term="t", kind="who", model="m"))
        rev = _law_revision(s)
        s.add(LawRevisionSummary(revision_id=rev.id, summary="S", model="m"))

    staged, working = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(staged)() as s:
        incoming(s)
        s.commit()
    _corpus(working)
    counts, _ = merge_corpus(staged, working, _BATCH_META)

    unmerged = counts.get("_unmerged", {}) or {}
    for name in ("watches", "watch_matches", "ai_custom_prompt", "ai_keyword",
                 "law_revision_summaries"):
        assert name not in unmerged, f"{name} is still reported as unmerged"
        assert name in counts, f"{name} is not reported at all"
        assert counts[name]["new"] == 1, f"{name} did not report the row it carried"
