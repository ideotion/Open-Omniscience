"""The triage PROPOSAL step: a finished run log -> a reviewable, language-scoped proposal.

The verdicts were always in the log; what was missing was a caller that turns them into
something a human can judge, and the LANGUAGE that decides whether an addition is safe.
These tests pin the honesty properties rather than the shape: what is proposed, what is
deliberately held back, and that nothing is ever applied.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import triage as T
from src.ai_layer import triage_proposal as P
from src.ai_layer.triage_job import CANARIES, _verdicts_record
from src.database.models import Base, Keyword


@pytest.fixture()
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    yield s
    s.close()


def _kw(s, term, language, *, articles=5, mentions=9, entity=False):
    k = Keyword(
        term=term,
        normalized_term=term.lower(),
        language=language,
        article_count=articles,
        mention_count=mentions,
        is_entity=entity,
    )
    s.add(k)
    s.commit()
    return k


def _log(tmp_path, records):
    p = tmp_path / "oo-keyword-triage-20260813-000000-000000.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return p


def _verdicts(batch, mapping, languages=None):
    rec = {
        "schema": "oo-keyword-triage-verdicts-1",
        "batch": batch,
        "verdicts": {t: {"verdict": v, "kind": k} for t, (v, k) in mapping.items()},
        "missing": [],
    }
    if languages is not None:
        rec["languages"] = languages
    return rec


def test_junk_verdicts_become_a_PER_LANGUAGE_proposal_never_a_global_one(db, tmp_path):
    """The whole point of the step: scoped additions are collision-free, global ones are not.

    "content" is a junk English keyword here and a real French word elsewhere; the proposal
    must place it under 'en' and nowhere else, so merging it can never hide the French one.
    """
    _kw(db, "content", "en")
    _kw(db, "cookie policy", "en")
    _kw(db, "élection", "fr")
    log = _log(
        tmp_path,
        [
            {"schema": "oo-keyword-triage-run-1", "model": "m", "prompt_version": "v1"},
            _verdicts(
                0,
                {
                    "content": ("junk", "other"),
                    "cookie policy": ("junk", "other"),
                    "élection": ("content", "other"),
                },
            ),
        ],
    )

    out = P.build_triage_proposal(db, path=log)

    assert out["available"] is True
    by_lang = out["stoplist_additions"]["by_language"]
    assert by_lang["en"] == ["content", "cookie policy"]
    # The French keyword was judged CONTENT, so it is not proposed at all -- and crucially
    # "content" appears under 'en' only, never in a language-agnostic bucket.
    assert "fr" not in by_lang
    assert all("content" not in terms for lang, terms in by_lang.items() if lang != "en")


def test_a_term_under_SEVERAL_languages_is_held_back_not_assigned_to_one(db, tmp_path):
    """Keyword.term carries no unique constraint, so one spelling can exist per language.

    Choosing one would invent exactly the cross-language collision the scoping prevents,
    so the term is reported with its languages and proposed nowhere.
    """
    _kw(db, "pension", "en")
    _kw(db, "pension", "de")
    log = _log(tmp_path, [_verdicts(0, {"pension": ("junk", "other")})])

    out = P.build_triage_proposal(db, path=log)

    assert out["held_back"]["ambiguous_language"] == {"pension": ["de", "en"]}
    assert out["held_back"]["ambiguous_count"] == 1
    assert all("pension" not in terms for terms in out["stoplist_additions"]["by_language"].values())


def test_the_run_s_OWN_recorded_language_resolves_what_the_corpus_cannot(db, tmp_path):
    """A log that carries the language is self-describing: the ambiguity is already answered.

    The run judged the GERMAN 'pension'. That is a fact about what happened, not a choice
    between two live rows, so it resolves the same corpus state the previous test holds back.
    """
    _kw(db, "pension", "en")
    _kw(db, "pension", "de")
    log = _log(
        tmp_path, [_verdicts(0, {"pension": ("junk", "other")}, languages={"pension": "de"})]
    )

    out = P.build_triage_proposal(db, path=log)

    assert out["held_back"]["ambiguous_language"] == {}
    assert out["stoplist_additions"]["by_language"]["de"] == ["pension"]
    assert out["language_basis"]["from_the_run_log"] == 1
    assert out["language_basis"]["from_the_live_corpus"] == 0


def test_the_canaries_are_excluded_and_the_exclusion_is_reported(db, tmp_path):
    """Canaries ride EVERY batch by design, so their verdicts are anchors, not corpus
    judgements -- and there are thousands of them. Dropping them silently would read as
    "the model never saw them"; the count says otherwise."""
    canary = CANARIES[0].term
    _kw(db, "cookie policy", "en")
    log = _log(
        tmp_path,
        [
            _verdicts(0, {canary: ("junk", "other"), "cookie policy": ("junk", "other")}),
            _verdicts(1, {canary: ("junk", "other")}),
        ],
    )

    out = P.build_triage_proposal(db, path=log)

    assert out["judged"]["canary_verdicts_excluded"] == 2
    assert out["stoplist_additions"]["by_language"]["en"] == ["cookie policy"]
    for terms in out["stoplist_additions"]["by_language"].values():
        assert canary not in terms


def test_unsure_is_never_proposed_and_the_counts_say_how_many(db, tmp_path):
    """Propose only what the model was confident is noise. An 'unsure' verdict is real
    information about the run -- it is counted -- but it is not a deletion proposal."""
    _kw(db, "maybe junk", "en")
    _kw(db, "clearly junk", "en")
    log = _log(
        tmp_path,
        [_verdicts(0, {"maybe junk": ("unsure", "other"), "clearly junk": ("junk", "other")})],
    )

    out = P.build_triage_proposal(db, path=log)

    assert out["judged"]["unsure"] == 1
    assert out["judged"]["junk"] == 1
    assert out["stoplist_additions"]["by_language"]["en"] == ["clearly junk"]


def test_every_proposed_term_carries_the_evidence_a_reviewer_needs(db, tmp_path):
    """A bare word list cannot be judged. The counts a reviewer weighs travel with it."""
    _kw(db, "cookie policy", "en", articles=412, mentions=980, entity=False)
    log = _log(tmp_path, [_verdicts(0, {"cookie policy": ("junk", "other")})])

    out = P.build_triage_proposal(db, path=log)

    assert out["evidence"]["cookie policy"] == {
        "articles": 412,
        "mentions": 980,
        "tagged_entity": False,
    }


def test_a_repeat_that_DISAGREES_is_reported_rather_than_collapsed(db, tmp_path):
    """The sweep pages by a keyset cursor, so a term should appear once. Two different
    verdicts for one term means a resume re-judged it or the pagination overlapped -- a
    fact about the run, not something to average away."""
    _kw(db, "climate", "en")
    log = _log(
        tmp_path,
        [
            _verdicts(0, {"climate": ("content", "other")}),
            _verdicts(1, {"climate": ("junk", "other")}),
        ],
    )

    out = P.build_triage_proposal(db, path=log)

    assert out["judged"]["repeat_disagreements"] == 1
    assert out["judged"]["disagreement_examples"][0] == {
        "term": "climate",
        "first": "content",
        "later": "junk",
    }
    # FIRST wins, so a later flip cannot quietly turn a content word into a deletion.
    assert all("climate" not in v for v in out["stoplist_additions"]["by_language"].values())


def test_no_run_log_is_an_honest_absence_not_an_empty_proposal(db, tmp_path, monkeypatch):
    """An empty proposal would read as 'the model found nothing to remove'."""
    monkeypatch.setattr(P, "newest_triage_log", lambda: None)

    out = P.build_triage_proposal(db)

    assert out["available"] is False
    assert "no keyword-triage run log" in out["note"]
    assert "stoplist_additions" not in out


def test_the_proposal_writes_NOTHING_and_applies_NOTHING(db, tmp_path):
    """The standing rule: the analyzer proposes, a human judges. Building the proposal must
    leave the corpus and the live hide-set byte-identical -- a stoplist entry hides existing
    mentions at query time AND stops new ones at index time, and only the first is undoable
    without a full re-index."""
    from src.analytics.filters import hidden_set

    _kw(db, "cookie policy", "en")
    log = _log(tmp_path, [_verdicts(0, {"cookie policy": ("junk", "other")})])
    before_hidden = set(hidden_set())
    before_rows = {(k.term, k.language) for k in db.query(Keyword).all()}

    out = P.build_triage_proposal(db, path=log)

    assert out["stoplist_additions"]["provenance"] == "ai-proposed"
    assert "cookie policy" in out["stoplist_additions"]["by_language"]["en"]
    # Proposed, and still not hidden: nothing took effect.
    assert set(hidden_set()) == before_hidden
    assert "cookie policy" not in hidden_set()
    assert {(k.term, k.language) for k in db.query(Keyword).all()} == before_rows


def test_a_truncated_final_line_does_not_throw_the_whole_run_away(db, tmp_path):
    """A hard kill leaves a half-written line. Refusing the log over it would discard every
    verdict the run did produce."""
    _kw(db, "cookie policy", "en")
    p = tmp_path / "oo-keyword-triage-20260813-000000-000000.jsonl"
    with p.open("w", encoding="utf-8") as f:
        f.write(json.dumps(_verdicts(0, {"cookie policy": ("junk", "other")})) + "\n")
        f.write('{"schema": "oo-keyword-triage-verdi')  # killed mid-write

    out = P.build_triage_proposal(db, path=p)

    assert out["stoplist_additions"]["by_language"]["en"] == ["cookie policy"]


def test_the_last_report_publishes_the_FILE_s_totals_beside_the_footer_s(tmp_path, monkeypatch):
    """A sweep resumes by APPENDING to the same dated log, and the footer is written by
    whichever invocation ended -- so an attempt that found the backend down and gave up
    before its first batch writes `batches_completed: 0, verdicts_out: 0` beside thousands
    of batches of real work.

    A field log (2026-08-13) was exactly that: 6,208 batch records under a zeroed error
    footer. Reading the footer alone renders "0 batches, 0 verdicts" -- not a missing
    number but a WRONG one, which is worse, because it reads as a run that judged nothing
    when days of GPU time are sitting in the file. So the reader also sums the per-batch
    records the run itself wrote: the file's own account, exact and invocation-independent.
    """
    from src.ai_layer import triage_job as TJ

    d = tmp_path / "triage"
    d.mkdir()
    monkeypatch.setattr(TJ, "_triage_dir", lambda: d)
    recs = [{"schema": "oo-keyword-triage-run-1", "model": "m"}]
    for i in range(5):
        recs.append({
            "schema": "oo-keyword-triage-batch-1", "keywords_in": 25, "verdicts_out": 22,
            "parse_failures": 3, "missing": 3,
        })
        recs.append(_verdicts(i, {f"t{i}": ("junk", "other")}))
    recs.append({
        "schema": "oo-keyword-triage-run-summary-1", "state": "error",
        "batches_completed": 0, "keywords_in": 0, "verdicts_out": 0,
        "parse_failures": 0, "missing": 0, "error": "vLLM not reachable",
    })
    with (d / "oo-keyword-triage-20260802-133241-630762.jsonl").open("w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")

    rep = TJ.last_keyword_triage_report()

    assert rep["batches_logged"] == 5
    assert rep["logged_totals"] == {
        "keywords_in": 125, "verdicts_out": 110, "parse_failures": 15, "missing": 15,
    }
    # The footer is KEPT, not reconciled away: a reader that wants the last attempt's own
    # outcome still has its state and its error. The two measure different things.
    assert rep["summary"]["state"] == "error"
    assert rep["summary"]["verdicts_out"] == 0


def test_the_proposal_reads_the_log_not_the_footer_so_a_failed_attempt_loses_nothing(
    db, tmp_path
):
    """The same field shape, end to end. The footer says the run produced nothing; the
    proposal must still recover every verdict, because it streams the batch records and
    never consults the footer's counters."""
    _kw(db, "junkword", "en")
    log = _log(
        tmp_path,
        [
            {"schema": "oo-keyword-triage-run-1", "model": "m"},
            _verdicts(0, {"junkword": ("junk", "other")}),
            {"schema": "oo-keyword-triage-run-summary-1", "state": "error",
             "batches_completed": 0, "verdicts_out": 0, "error": "vLLM not reachable"},
        ],
    )

    out = P.build_triage_proposal(db, path=log)

    assert out["available"] is True
    assert out["judged"]["distinct_terms"] == 1
    assert out["stoplist_additions"]["by_language"]["en"] == ["junkword"]
    # ...and the failed attempt's own state is still reported, never hidden by the recovery.
    assert out["log"]["run_state"] == "error"


def test_the_term_ceiling_is_reported_rather_than_left_to_be_inferred(db, tmp_path):
    """A short proposal and a capped one look identical from the outside. The cap keeps the
    log's PREFIX, which the sweep writes most-widespread-first, and says that it did."""
    for t in ("aaa", "bbb", "ccc"):
        _kw(db, t, "en")
    log = _log(
        tmp_path,
        [_verdicts(0, {t: ("junk", "other") for t in ("aaa", "bbb", "ccc")})],
    )

    uncapped = P.build_triage_proposal(db, path=log)
    assert uncapped["judged"]["terms_truncated"] is False
    assert len(uncapped["stoplist_additions"]["by_language"]["en"]) == 3

    read = P.read_log_verdicts(log, max_terms=2)
    assert read["terms_truncated"] is True
    assert len(read["verdicts"]) == 2


def test_the_bundle_member_produces_a_real_report_not_a_sentinel():
    """The proposal is generated by calling the ROUTE directly from
    `_all_diagnostics_members`, where a FastAPI default is the sentinel OBJECT rather than
    its value — `Query(False)` is truthy and an unresolved `Depends` is not a Session. The
    bundle's own guard would swallow either into an error stub and nothing would say so, so
    this drives the REAL member generator: the defect would live in the call, not the
    definition, and a source-level check of the signature would pass right over it."""
    import json as _json

    from src.api import diagnostics as d
    from src.database.session import SessionLocal

    with SessionLocal() as s:
        members = dict(d._all_diagnostics_members(s))
        assert "keyword-triage-proposal.json" in members
        resp = members["keyword-triage-proposal.json"]()
    body = _json.loads(bytes(resp.body))
    assert body["schema"] == P.PROPOSAL_SCHEMA
    # available False is legitimate here (no run log on a fresh install); a SENTINEL leak
    # is not — it would surface as a missing schema or an error stub, never as this pair.
    assert body["available"] in (True, False)
    if body["available"]:
        assert "by_language" in body["stoplist_additions"]
    else:
        assert "no keyword-triage run log" in body["note"]


def test_the_record_builder_carries_the_language_for_judged_terms_only(db):
    """The writer half: a language is recorded for terms the model actually returned, and
    only where the corpus has one -- an absent entry means 'no language', never a guess."""
    chunk = [
        T.TriageItem("cookie policy", language="en"),
        T.TriageItem("élection", language="fr"),
        T.TriageItem("unknownlang", language=None),
    ]
    pb = T.ParsedBatch(keywords_in=3)
    pb.verdicts = {
        "cookie policy": {"verdict": "junk", "kind": "other"},
        "unknownlang": {"verdict": "junk", "kind": "other"},
    }
    pb.missing = ["élection"]

    rec = _verdicts_record(7, pb, chunk)

    assert rec["languages"] == {"cookie policy": "en"}  # judged + has a language
    assert "élection" not in rec["languages"]  # has a language but was not judged
    assert "unknownlang" not in rec["languages"]  # judged but carries no language
    assert rec["batch"] == 7
