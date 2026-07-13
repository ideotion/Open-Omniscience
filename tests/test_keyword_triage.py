"""
LLM keyword-triage measure-first core (planning §8).

Proves the PURE mechanism with a stub client + an in-memory corpus — no network, no Ollama,
no GPU. The real batch run + the 7-model bench are operator-run on the Ollama rig. The
negative-space cases (mangled echo / hallucinated term / malformed verdict / dropped keyword /
failing canary) are mandatory for a parser (the #590 lesson).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.ai_layer import triage as T
from src.database.models import Base, Keyword


# --------------------------------------------------------------------------- #
# The self-test (the exported mechanism proof — must stay green).
# --------------------------------------------------------------------------- #
def test_selftest_passes():
    r = T.run_triage_selftest()
    assert r["passed"] is True, r["checks"]
    assert r["schema"] == "oo-keyword-triage-selftest-1"


# --------------------------------------------------------------------------- #
# parse_verdicts — the constrained parser + echo-back (negative space).
# --------------------------------------------------------------------------- #
def test_parse_happy_path():
    raw = "climate change :: content :: other\nsubscribe now :: junk :: other"
    pb = T.parse_verdicts(raw, ["climate change", "subscribe now"])
    assert pb.verdicts_out == 2
    assert pb.verdicts["climate change"] == {"verdict": "content", "kind": "other"}
    assert pb.parse_failures == 0 and pb.missing == []


def test_echo_back_rejects_a_mangled_term():
    # the model mis-spells the keyword -> no expected term matches -> rejected, NOT stored.
    pb = T.parse_verdicts("climate chnge :: junk :: other", ["climate change"])
    assert pb.verdicts_out == 0
    assert pb.parse_failures == 1
    assert pb.missing == ["climate change"]


def test_echo_back_rejects_a_hallucinated_term():
    # a term the batch never contained is a hallucination — never stored (negative space).
    pb = T.parse_verdicts("ghost topic :: content :: org", ["real term"])
    assert "ghost topic" not in pb.verdicts
    assert pb.verdicts_out == 0 and pb.parse_failures == 1


def test_malformed_verdict_or_kind_is_counted_never_guessed():
    raw = "a :: bogus :: other\nb :: content :: notakind"
    pb = T.parse_verdicts(raw, ["a", "b"])
    assert pb.verdicts_out == 0
    assert pb.parse_failures == 2
    assert set(pb.missing) == {"a", "b"}


def test_missing_keyword_is_counted():
    pb = T.parse_verdicts("a :: content :: other", ["a", "b", "c"])
    assert pb.verdicts_out == 1
    assert set(pb.missing) == {"b", "c"}


def test_duplicate_line_keeps_the_first():
    raw = "a :: content :: org\na :: junk :: other"
    pb = T.parse_verdicts(raw, ["a"])
    assert pb.verdicts["a"]["verdict"] == "content"
    assert pb.verdicts_out == 1


def test_term_containing_the_delimiter_still_parses():
    # rsplit-from-the-right: a keyword with an internal ' :: ' must still resolve.
    raw = "foo :: bar :: content :: place"
    pb = T.parse_verdicts(raw, ["foo :: bar"])
    assert pb.verdicts.get("foo :: bar") == {"verdict": "content", "kind": "place"}


def test_empty_and_none_raw_are_all_missing():
    for raw in (None, "", "   \n\n"):
        pb = T.parse_verdicts(raw, ["a", "b"])
        assert pb.verdicts_out == 0
        assert set(pb.missing) == {"a", "b"}
        assert pb.parse_failures == 0  # no lines emitted -> no failures, just missing


def test_kind_and_verdict_aliases_are_accepted_strictly():
    pb = T.parse_verdicts("un :: keep :: organisation", ["un"])
    assert pb.verdicts["un"] == {"verdict": "content", "kind": "org"}


def test_echo_match_is_case_accent_whitespace_tolerant():
    pb = T.parse_verdicts("  Élection   :: content :: other", ["élection"])
    assert pb.verdicts_out == 1  # matched despite case + extra whitespace


def test_unsure_count_property():
    raw = "a :: unsure :: other\nb :: content :: other"
    pb = T.parse_verdicts(raw, ["a", "b"])
    assert pb.unsure_count == 1


# --------------------------------------------------------------------------- #
# Canaries.
# --------------------------------------------------------------------------- #
def test_canary_passes_on_match():
    pb = T.parse_verdicts("cookie banner :: junk :: other", ["cookie banner"])
    c = T.check_canaries(pb, {"cookie banner": {"verdict": "junk"}})
    assert c["ok"] is True and c["failed"] == []


def test_canary_fails_on_verdict_mismatch():
    pb = T.parse_verdicts("cookie banner :: content :: other", ["cookie banner"])
    c = T.check_canaries(pb, {"cookie banner": {"verdict": "junk"}})
    assert c["ok"] is False and c["failed"][0]["got"] == "content"


def test_canary_fails_when_the_anchor_was_dropped():
    pb = T.parse_verdicts("something else :: content :: other", ["cookie banner", "something else"])
    c = T.check_canaries(pb, {"cookie banner": {"verdict": "junk"}})
    assert c["ok"] is False and c["failed"][0]["got"] is None


def test_canary_fails_on_kind_mismatch():
    pb = T.parse_verdicts("acme :: content :: person", ["acme"])
    c = T.check_canaries(pb, {"acme": {"verdict": "content", "kind": "org"}})
    assert c["ok"] is False


# --------------------------------------------------------------------------- #
# The prompt.
# --------------------------------------------------------------------------- #
def test_prompt_mixes_canaries_and_returns_all_expected():
    items = [T.TriageItem("real one", language="en", article_count=50)]
    canaries = (T.TriageItem("cookie banner", language="en"),)
    system, user, expected = T.build_triage_prompt(items, canaries=canaries)
    assert "real one" in user and "cookie banner" in user
    assert expected == ["real one", "cookie banner"]  # canary is indistinguishable in the batch
    assert "50 articles" in user and "lang=en" in user


def test_prompt_bounds_snippets():
    long = "x" * 500
    items = [T.TriageItem("t", snippets=(long, "b", "c"))]  # only first 2 snippets, bounded len
    _, user, _ = T.build_triage_prompt(items, max_snippet_chars=20)
    assert user.count("…") <= 4  # 2 snippets * 2 ellipses each at most
    assert "x" * 100 not in user  # snippet truncated


# --------------------------------------------------------------------------- #
# Timing schema + ETA.
# --------------------------------------------------------------------------- #
def test_gen_meta_passthrough_verbatim_and_none_when_absent():
    class R:
        total_duration = 5
        eval_count = 3
        # the others are absent -> None, never a fabricated 0.

    meta = T.gen_meta_from_result(R())
    assert meta["total_duration"] == 5 and meta["eval_count"] == 3
    assert meta["load_duration"] is None and meta["eval_duration"] is None


def test_batch_record_carries_timing_and_counts_no_score():
    pb = T.parse_verdicts("a :: content :: other\nb :: unsure :: other", ["a", "b"])
    rec = T.batch_record(
        started_at="t0", finished_at="t1",
        gen_meta={"total_duration": 9, "eval_count": 4},
        pb=pb, canary={"ok": True, "failed": []}, model="m", model_digest="sha:1",
    )
    assert rec["total_duration"] == 9 and rec["keywords_in"] == 2 and rec["unsure_count"] == 1
    assert rec["model_digest"] == "sha:1"
    _assert_no_score(rec)


def test_eta_line_math_and_degrade():
    assert T.eta_line(100, 0, 5) is None  # no throughput yet -> None (never a fabricated ETA)
    assert T.eta_line(100, 10, 0) is None
    e = T.eta_line(100, 10, 5.0)  # 2 valid/s -> 50 s
    assert e["throughput_valid_per_s"] == 2.0 and e["eta_seconds"] == 50.0


# --------------------------------------------------------------------------- #
# run_triage_batch — the thin networked runner (stub client).
# --------------------------------------------------------------------------- #
class _Stub:
    def __init__(self, text):
        self.text = text

    def generate(self, prompt, *, model, system=None, keep_alive=None):
        return type("R", (), {"text": self.text, "total_duration": 3, "eval_count": 2})()


def test_run_triage_batch_parses_and_measures():
    items = [T.TriageItem("alpha"), T.TriageItem("beta")]
    out = T.run_triage_batch(
        _Stub("alpha :: content :: other\nbeta :: junk :: other"),
        items, model="stub", monotonic=iter([0.0, 2.0]).__next__,
    )
    assert out["parsed"].verdicts_out == 2
    assert out["wall_s"] == 2.0
    assert out["gen_meta"]["total_duration"] == 3


# --------------------------------------------------------------------------- #
# Head-scope selection + the EXPORT-ONLY invariant (never writes the trusted index).
# --------------------------------------------------------------------------- #
def _db():
    engine = create_engine("sqlite:///:memory:", future=True,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def _kw(db, term, *, arts, mentions=0, lang="en"):
    k = Keyword(term=term, normalized_term=term.lower(), language=lang,
                article_count=arts, mention_count=mentions)
    db.add(k)
    return k


def test_select_triage_head_orders_by_article_spread():
    db = _db()
    _kw(db, "rare", arts=2)
    _kw(db, "broad", arts=900, mentions=3000)
    _kw(db, "mid", arts=50)
    db.commit()
    head = T.select_triage_head(db, limit=2)
    assert [h.term for h in head] == ["broad", "mid"]  # by article_count DESC
    assert head[0].article_count == 900 and head[0].mention_count == 3000


def test_select_triage_head_min_articles_filter():
    db = _db()
    _kw(db, "hapax", arts=1)
    _kw(db, "kept", arts=10)
    db.commit()
    head = T.select_triage_head(db, limit=10, min_articles=5)
    assert [h.term for h in head] == ["kept"]


def test_triage_path_never_writes_the_trusted_index():
    # THE honesty invariant: selecting the head + running a batch + exporting + proposing
    # artifacts touches ZERO trusted rows (triage is EXPORT-ONLY). Mirrors the ai_keyword
    # extraction test asserting zero KeywordMention.
    db = _db()
    _kw(db, "climate change", arts=900)
    _kw(db, "subscribe now", arts=120)
    db.commit()
    before = db.query(Keyword).count()
    head = T.select_triage_head(db, limit=10)
    out = T.run_triage_batch(
        _Stub("climate change :: content :: other\nsubscribe now :: junk :: other"),
        head, model="stub",
    )
    T.propose_stoplist_additions([out["parsed"]], {i.term: i for i in head})
    T.propose_kind_overrides([out["parsed"]], {i.term: i for i in head})
    assert db.query(Keyword).count() == before  # nothing added
    assert not db.dirty and not db.new  # no pending writes queued either


# --------------------------------------------------------------------------- #
# EXPORT-ONLY JSONL writer.
# --------------------------------------------------------------------------- #
def test_export_jsonl_round_trips(tmp_path):
    import json
    p = tmp_path / "triage.jsonl"
    n = T.export_triage_jsonl(p, [{"a": 1}, {"b": "é"}])
    assert n == 2
    T.export_triage_jsonl(p, [{"c": 3}])  # append, not overwrite
    lines = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    assert lines == [{"a": 1}, {"b": "é"}, {"c": 3}]


# --------------------------------------------------------------------------- #
# Deterministic artifact proposals (PROPOSE-only, provenance ai-proposed).
# --------------------------------------------------------------------------- #
def test_stoplist_proposal_groups_junk_by_language_excludes_unsure():
    items = {
        "banner": T.TriageItem("banner", language="en"),
        "biscuit": T.TriageItem("biscuit", language="fr"),
        "maybe": T.TriageItem("maybe", language="en"),
        "orphan": T.TriageItem("orphan", language=None),
    }
    pb = T.ParsedBatch(verdicts={
        "banner": {"verdict": "junk", "kind": "other"},
        "biscuit": {"verdict": "junk", "kind": "other"},
        "maybe": {"verdict": "unsure", "kind": "other"},   # excluded (not confident junk)
        "orphan": {"verdict": "junk", "kind": "other"},
    })
    out = T.propose_stoplist_additions([pb], items)
    assert out["by_language"]["en"] == ["banner"]  # 'maybe' (unsure) excluded
    assert out["by_language"]["fr"] == ["biscuit"]
    assert out["by_language"]["?"] == ["orphan"]  # unknown-language bucket
    assert out["provenance"] == "ai-proposed"
    _assert_no_score(out)


def test_kind_override_proposal_content_concrete_kind_only():
    items = {
        "acme": T.TriageItem("acme", language="en", is_entity=True),
        "topicword": T.TriageItem("topicword", language="en"),
        "junky": T.TriageItem("junky", language="en"),
    }
    pb = T.ParsedBatch(verdicts={
        "acme": {"verdict": "content", "kind": "org"},        # proposed
        "topicword": {"verdict": "content", "kind": "other"}, # excluded ('other' is not concrete)
        "junky": {"verdict": "junk", "kind": "person"},       # excluded (junk)
    })
    out = T.propose_kind_overrides([pb], items)
    terms = [p["term"] for p in out["proposals"]]
    assert terms == ["acme"]
    assert out["proposals"][0]["proposed_kind"] == "org"
    assert out["proposals"][0]["currently_tagged_entity"] is True
    _assert_no_score(out)


# --------------------------------------------------------------------------- #
# The bench — roster verification (HARD RULE) + metrics reported ALONE.
# --------------------------------------------------------------------------- #
def test_verify_roster_refuses_uninstalled_never_substitutes():
    r = T.verify_roster(["mistral:7b", "granite4.1:3b", "ghost:9b"], ["mistral:7b", "granite4.1:3b"])
    assert r["ok"] is False
    assert r["missing"] == ["ghost:9b"]
    assert r["runnable"] == ["mistral:7b", "granite4.1:3b"]  # the exact installed subset, no fuzzy match


def test_verify_roster_ok_when_all_present():
    r = T.verify_roster(["a", "b"], ["a", "b", "c"])
    assert r["ok"] is True and r["missing"] == []


def test_metrics_each_alone():
    assert T.valid_verdicts_per_sec(10, 2.0) == 5.0
    assert T.valid_verdicts_per_sec(0, 2.0) is None
    assert T.format_validity_rate(5, 4) == 0.8
    assert T.format_validity_rate(0, 0) is None
    assert T.pct_unsure(2, 8) == 0.25
    assert T.pct_unsure(1, 0) is None


def test_anchor_accuracy_junk_pr_separate_from_kind():
    verdicts = {
        "spam": {"verdict": "junk", "kind": "other"},       # gold junk -> junk TP
        "realorg": {"verdict": "content", "kind": "org"},   # gold content/org -> kind correct
        "missed": {"verdict": "content", "kind": "other"},  # gold junk -> junk FN (false negative)
    }
    anchors = {
        "spam": {"verdict": "junk"},
        "realorg": {"verdict": "content", "kind": "org"},
        "missed": {"verdict": "junk"},
        "dropped": {"verdict": "junk"},  # the model didn't return it -> counts as a junk FN
    }
    acc = T.anchor_accuracy(verdicts, anchors)
    # junk: TP=1 (spam), FP=0, FN=2 (missed + dropped) -> precision 1.0, recall 1/3
    assert acc["junk_precision"] == 1.0
    assert acc["junk_recall"] == round(1 / 3, 4)
    # kind: only realorg is a content anchor with a concrete gold kind -> 1/1
    assert acc["kind_accuracy"] == 1.0 and acc["kind_n"] == 1
    _assert_no_score(acc)


def test_pairwise_agreement_none_on_no_overlap():
    mv = {
        "m1": {"a": "junk", "b": "content"},
        "m2": {"a": "junk", "b": "junk"},     # agree on a, differ on b -> 0.5
        "m3": {"z": "content"},               # no overlap with m1/m2 -> None
    }
    out = T.pairwise_agreement(mv)
    assert out["pairs"]["m1|m2"]["agreement"] == 0.5 and out["pairs"]["m1|m2"]["n"] == 2
    assert out["pairs"]["m1|m3"]["agreement"] is None  # never a fabricated 1.0
    assert len(out["pairs"]) == 3  # C(3,2)


# --------------------------------------------------------------------------- #
# No-score honesty walk (a field named *score*/*ranking* trips the non-negotiable).
# --------------------------------------------------------------------------- #
def _assert_no_score(obj, path=""):
    banned = ("score", "ranking", "rank", "rating", "grade", "trust")
    if isinstance(obj, dict):
        for k, v in obj.items():
            lk = str(k).lower()
            assert not any(b in lk for b in banned), f"score-like key {path}.{k}"
            _assert_no_score(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _assert_no_score(v, f"{path}[{i}]")


def test_selftest_output_carries_no_score_field():
    _assert_no_score(T.run_triage_selftest())


# --------------------------------------------------------------------------- #
# Regressions pinned from the adversarial skeptic pass (negative-space collisions,
# export path-safety, metric edge cases). Each names the exact input the skeptics found.
# --------------------------------------------------------------------------- #
def test_normalized_collision_both_distinct_keywords_stored_no_misattribution():
    # Straße and Strasse both normalize to 'strasse' (ß->ss) but are DISTINCT index keywords.
    # An exact echo of each must store its OWN verdict — no data loss, no misattribution.
    raw = "strasse :: junk :: other\nStraße :: content :: place"
    pb = T.parse_verdicts(raw, ["Straße", "strasse"])
    assert pb.verdicts["Straße"] == {"verdict": "content", "kind": "place"}
    assert pb.verdicts["strasse"] == {"verdict": "junk", "kind": "other"}
    assert pb.verdicts_out == 2 and pb.missing == [] and pb.parse_failures == 0


def test_ambiguous_fuzzy_echo_on_a_collision_is_rejected_never_guessed():
    # a fuzzy echo ('STRASSE') that matches NEITHER original exactly but collides on the
    # normalized key must be rejected (we never guess which of the two it meant).
    pb = T.parse_verdicts("STRASSE :: junk :: other", ["Straße", "strasse"])
    assert pb.verdicts_out == 0 and pb.parse_failures == 1
    assert set(pb.missing) == {"Straße", "strasse"}


def test_collision_junk_stays_on_the_junk_term_in_the_stoplist_proposal():
    # the concrete export harm the skeptics found: a real keyword must NOT be proposed for
    # deletion because a colliding junk fragment shared its normalized form.
    items = {
        "strasse": T.TriageItem("strasse", language="de"),
        "Straße": T.TriageItem("Straße", language="de"),
    }
    pb = T.parse_verdicts("strasse :: junk :: other\nStraße :: content :: place",
                          ["strasse", "Straße"])
    prop = T.propose_stoplist_additions([pb], items)
    assert prop["by_language"]["de"] == ["strasse"]  # the real place 'Straße' is NOT proposed


def test_format_validity_reaches_one_when_a_canary_duplicates_a_head_keyword():
    # expected_terms with an exact duplicate (a canary == a head keyword) must be deduped for
    # the count, so a perfect answer to the one distinct keyword scores 1.0, not 0.5.
    pb = T.parse_verdicts("election :: content :: other", ["election", "election"])
    assert pb.keywords_in == 1 and pb.verdicts_out == 1
    assert T.format_validity_rate(pb.keywords_in, pb.verdicts_out) == 1.0


def test_verify_roster_dedups_requested_tags():
    r = T.verify_roster(["a", "a", "b"], ["a"])
    assert r["runnable"] == ["a"] and r["missing"] == ["b"]  # 'a' counted once, not twice


def test_eta_line_rejects_negative_remaining():
    assert T.eta_line(-50, 10, 5.0) is None  # a nonsensical remaining degrades, never a negative ETA


def test_export_refuses_a_database_or_non_jsonl_target(tmp_path):
    import pytest
    T.export_triage_jsonl(tmp_path / "ok.jsonl", [{"a": 1}])  # allowed
    for bad in ("open_omniscience.db", "corpus.sqlite", "notes.txt", "open_omniscience.db-wal"):
        with pytest.raises(ValueError):
            T.export_triage_jsonl(tmp_path / bad, [{"a": 1}])


def test_anchor_kind_not_credited_when_model_did_not_call_it_content():
    # a content anchor the model mislabelled as junk (but happened to output the right kind)
    # must NOT earn kind credit — kind is 'how well it types what it CALLS content'.
    verdicts = {"acme": {"verdict": "junk", "kind": "org"}}
    anchors = {"acme": {"verdict": "content", "kind": "org"}}
    acc = T.anchor_accuracy(verdicts, anchors)
    assert acc["kind_n"] == 1 and acc["kind_accuracy"] == 0.0
