"""S04-06 S6 — the in-app Wikidata ring load: the rate, the refusals, the merge.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The brief names two things this must prove — the 10 s spacing and the kill-switch refusal
BY NAME — and both are properties nothing else in the tree can see: a politeness rate is
invisible in a diff, and a refusal that happens for the right reason looks exactly like a
refusal that happens for the wrong one. Everything else here is the negative space: what
must NOT be written, and what must NOT be destroyed.

NO TEST IN THIS FILE OPENS A SOCKET. The getter is injected everywhere, and the one test
that proves the production path would refuse does so with the kill switch engaged, before
a session is constructed.
"""

from __future__ import annotations

from datetime import date

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.analytics import equivalence
from src.analytics import ring_loader as RL
from src.analytics.wikidata_rings import wbentities_url, wbsearch_url
from src.database.models import Article, Base, Keyword, KeywordMention, Source
from src.ingest import activate_kill_switch, clear_kill_switch


# --------------------------------------------------------------------------- #
#  A fake Wikidata: deterministic, offline, and it RECORDS when it was called.
# --------------------------------------------------------------------------- #
class FakeClock:
    """A monotonic clock that only moves when something sleeps on it.

    Real time would make the spacing test take a minute and pass for the wrong reason on
    a loaded runner; this makes the interval the ONLY thing under test.
    """

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeWikidata:
    """Answers the two Action API shapes and timestamps every call."""

    def __init__(self, clock: FakeClock, items: dict[str, dict]) -> None:
        self.clock = clock
        self.items = items
        self.calls: list[tuple[float, str]] = []

    def __call__(self, url: str) -> dict:
        self.calls.append((self.clock(), url))
        if "wbsearchentities" in url:
            for term, spec in self.items.items():
                if f"search={term}" in url.replace("%20", "+"):
                    return {"search": [{"id": spec["qid"]}]} if spec.get("qid") else {"search": []}
            return {"search": []}
        qid = url.split("ids=")[1].split("&")[0]
        for spec in self.items.values():
            if spec.get("qid") == qid:
                labels = {k: {"value": v} for k, v in (spec.get("labels") or {}).items()}
                return {"entities": {qid: {"labels": labels, "aliases": {}}}}
        return {"entities": {}}


_ITEMS = {
    "kanzleramt": {"qid": "Q1", "labels": {"de": "Kanzleramt", "en": "chancellery",
                                           "fr": "chancellerie"}},
    "wahlrecht": {"qid": "Q2", "labels": {"de": "Wahlrecht", "en": "suffrage"}},
    "nixdaheim": {"qid": None},                              # no item at all
    "einsprachig": {"qid": "Q4", "labels": {"de": "Einsprachig"}},  # one language only
}


def _cands(*normalized: str) -> list[RL.Candidate]:
    return [
        RL.Candidate(term=n, normalized=n, language="de", articles=5, mentions=9)
        for n in normalized
    ]


@pytest.fixture(autouse=True)
def _offline_by_default():
    clear_kill_switch()
    yield
    clear_kill_switch()


# --------------------------------------------------------------------------- #
#  1. R8: the rate is a gate over REQUESTS, not a sleep over items
# --------------------------------------------------------------------------- #
def test_every_pair_of_requests_is_at_least_ten_seconds_apart(tmp_path):
    """R8 = "<= 1 request per 10 seconds", asserted between CONSECUTIVE REQUESTS.

    This is the assertion a `sleep(10)` at the bottom of the loop would FAIL, and the
    reason the rate is a gate here: Q408's pattern is two calls per concept, so a
    per-item sleep sends two requests inside one 10 s window — half the ruled rate,
    while reading in a diff exactly like the rule. Measured on the fake clock, so the
    proof costs no wall time and cannot pass because a runner was slow."""
    clock = FakeClock()
    wd = FakeWikidata(clock, _ITEMS)
    gate = RL.RateGate(clock=clock, sleep=clock.sleep)
    out = RL.load_rings(_cands("kanzleramt", "wahlrecht"), get=wd, gate=gate,
                        write=False)

    assert out["resolved"] == 2
    assert len(wd.calls) == 4, "two candidates must be two searches and two entity reads"
    stamps = [t for t, _ in wd.calls]
    # NOT strict=: the two slices differ in length by one BY CONSTRUCTION -- that is
    # what makes them consecutive pairs.
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]  # noqa: B905
    assert all(g >= RL.POLITE_SLEEP_S for g in gaps), (
        f"requests were sent {gaps} seconds apart; R8 allows one per {RL.POLITE_SLEEP_S}"
    )
    # ANTI-VACUITY: a gate that never let anything through would also satisfy the line
    # above. The first request must NOT have waited, and the rest must have.
    assert gate.waits[0] == 0.0 and all(w > 0 for w in gate.waits[1:])


def test_the_search_goes_out_in_the_terms_own_language(tmp_path):
    """Q408 = a. Searching every concept in English is how a ring table comes out
    anglicised, and the failure is silent: an English search for a German term usually
    returns SOMETHING, just not the right item."""
    clock = FakeClock()
    wd = FakeWikidata(clock, _ITEMS)
    RL.load_rings(_cands("kanzleramt"), get=wd, gate=RL.RateGate(clock=clock, sleep=clock.sleep),
                  write=False)
    search = next(u for _, u in wd.calls if "wbsearchentities" in u)
    assert "language=de" in search, search
    assert search == wbsearch_url("kanzleramt", "de")
    entities = next(u for _, u in wd.calls if "wbgetentities" in u)
    assert entities == wbentities_url("Q1")
    assert "languages=ar%7Cbn%7Cde" in entities, "labels must be asked for in all twelve"


# --------------------------------------------------------------------------- #
#  2. The kill switch refuses BY NAME, before any socket
# --------------------------------------------------------------------------- #
def test_airplane_mode_refuses_by_name_and_never_calls_the_getter():
    """Invariant #14e's corollary: a refusal BY THE KILL SWITCH must be named as such.

    The recorded defect is a probe that reported airplane mode as "size check failed",
    pointing an operator at someone else's server for their own setting. So this asserts
    the exception TYPE, that the message says airplane mode, and — the part that makes it
    a guarantee rather than a message — that nothing was fetched at all."""
    calls: list[str] = []

    def _never(url: str) -> dict:
        calls.append(url)
        return {}

    activate_kill_switch()
    with pytest.raises(RL.AirplaneRefusal) as err:
        RL.load_rings(_cands("kanzleramt"), get=_never, write=False)
    assert "airplane mode" in str(err.value).lower()
    assert calls == [], "the load reached a fetch while the kill switch was engaged"


def test_the_refusal_beats_an_empty_candidate_list():
    """Order matters: refusing only when there is work to do would make the guarantee
    depend on the corpus. A zero-candidate load under airplane mode must still refuse,
    because "we made no request" and "we would have made none anyway" are different
    claims and only the first one is about the kill switch."""
    activate_kill_switch()
    with pytest.raises(RL.AirplaneRefusal):
        RL.load_rings([], write=False)


# --------------------------------------------------------------------------- #
#  3. What must NOT be written
# --------------------------------------------------------------------------- #
def test_a_one_language_item_is_never_written_as_a_ring(tmp_path):
    """A ring with one language merges nothing, so writing it would assert a
    cross-language equivalence that does not exist — and would then be counted by every
    "rings held" figure as if it did."""
    clock = FakeClock()
    wd = FakeWikidata(clock, _ITEMS)
    out = RL.load_rings(_cands("einsprachig"), get=wd,
                        gate=RL.RateGate(clock=clock, sleep=clock.sleep), write=False)
    assert out["resolved"] == 0
    assert out["skipped"] == {RL.SKIP_ONE_LANGUAGE: 1}


def test_a_term_with_no_item_is_counted_and_the_batch_continues(tmp_path):
    """One unresolvable term must not cost the other nineteen their 10 s each."""
    clock = FakeClock()
    wd = FakeWikidata(clock, _ITEMS)
    out = RL.load_rings(_cands("nixdaheim", "kanzleramt"), get=wd,
                        gate=RL.RateGate(clock=clock, sleep=clock.sleep), write=False)
    assert out["skipped"] == {RL.SKIP_NO_ITEM: 1}
    assert out["rings"] == ["chancellery"]


def test_a_raising_request_is_isolated_to_its_own_candidate(tmp_path):
    """A network error mid-batch is the normal case over 67 hours of lookups, not an
    exceptional one."""
    clock = FakeClock()
    wd = FakeWikidata(clock, _ITEMS)

    def _flaky(url: str) -> dict:
        if "wahlrecht" in url:
            raise OSError("connection reset")
        return wd(url)

    out = RL.load_rings(_cands("wahlrecht", "kanzleramt"), get=_flaky,
                        gate=RL.RateGate(clock=clock, sleep=clock.sleep), write=False)
    assert out["skipped"] == {RL.SKIP_ERROR: 1}
    assert out["resolved"] == 1


def test_a_cancel_stops_the_batch_and_says_so(tmp_path):
    """The task-manager Cancel must be honest (invariant #20): it stops at the next
    candidate and the result REPORTS that it stopped, so a short tally is never read as
    a complete one."""
    clock = FakeClock()
    wd = FakeWikidata(clock, _ITEMS)
    seen = {"n": 0}

    def _stop() -> bool:
        seen["n"] += 1
        return seen["n"] > 3  # let the first candidate through, then stop

    out = RL.load_rings(_cands("kanzleramt", "wahlrecht"), get=wd,
                        gate=RL.RateGate(clock=clock, sleep=clock.sleep, stop=_stop),
                        should_stop=_stop, write=False)
    assert out["stopped"] is True
    assert out["resolved"] < 2


# --------------------------------------------------------------------------- #
#  4. The merge must never destroy the operator's file
# --------------------------------------------------------------------------- #
def test_the_merge_adds_and_never_replaces(tmp_path):
    """The local ring file is ALSO where a restored backup's rings land (Q409 = b), so a
    load that truncated it would delete rings this app never created. The recorded
    near-miss is the generator script, whose docstring said "augments" for months while
    the code overwrote its target."""
    path = tmp_path / "rings" / "keyword_rings_local.yml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump({"rings": [
        {"id": "restored-one", "members": ["en:budget", "fr:budget"]},
    ]}), encoding="utf-8")

    added = RL.merge_local_rings([{"id": "chancellery", "qid": "Q1",
                                   "members": ["de:kanzleramt", "en:chancellery"]}], path=path)
    assert added == 1
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    ids = {r["id"] for r in doc["rings"]}
    assert ids == {"restored-one", "chancellery"}, "the merge dropped a pre-existing ring"


def test_a_loaded_ring_declares_where_it_came_from(tmp_path):
    """Q406 = b removed the human review step, so the file itself has to carry the fact
    that nobody reviewed these — the honesty non-negotiable's method + caveat, at rest."""
    path = tmp_path / "keyword_rings_local.yml"
    RL.merge_local_rings([{"id": "chancellery", "qid": "Q1",
                           "members": ["de:kanzleramt", "en:chancellery"]}], path=path)
    row = yaml.safe_load(path.read_text(encoding="utf-8"))["rings"][0]
    assert row["source"] == "wikidata"
    assert "unreviewed" in row["note"]
    assert row["qid"] == "Q1", "the QID is the audit trail; a ring without one cannot be checked"


def test_an_unreadable_local_file_is_refused_not_overwritten(tmp_path):
    """Corrupt YAML is a repair job, not a licence to delete. The alternative — treat an
    unparseable file as empty and write over it — turns one bad character into the loss
    of every ring the operator restored."""
    path = tmp_path / "keyword_rings_local.yml"
    path.write_text("rings: [ this is not: valid: yaml", encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    added = RL.merge_local_rings([{"id": "x", "members": ["en:a", "fr:b"]}], path=path)
    assert added == 0
    assert path.read_text(encoding="utf-8") == before


def test_a_write_invalidates_every_memoised_ring_view(tmp_path, monkeypatch):
    """Three lru_caches sit on the ring files. Clearing only `load_rings` is the shape
    where a term resolves through one surface and not another, which is why
    `invalidate_ring_caches` exists — this proves the loader calls it."""
    monkeypatch.setattr(equivalence, "local_rings_path", lambda: tmp_path / "local.yml")
    equivalence.invalidate_ring_caches()
    assert equivalence.ring_of("de", "kanzleramt") is None  # warms all three caches

    clock = FakeClock()
    wd = FakeWikidata(clock, _ITEMS)
    RL.load_rings(_cands("kanzleramt"), get=wd,
                  gate=RL.RateGate(clock=clock, sleep=clock.sleep))
    assert equivalence.ring_of("de", "kanzleramt") == "chancellery", (
        "a freshly loaded ring is invisible until a restart — the caches were not cleared"
    )
    equivalence.invalidate_ring_caches()


# --------------------------------------------------------------------------- #
#  5. Q407: which candidates, in which order
# --------------------------------------------------------------------------- #
def _sess():
    e = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def _seed_keywords(s, rows):
    s.add(Source(name="S", domain="s.test"))
    s.flush()
    a = Article(url="u", canonical_url="u", source_id=1, title="t", content="c", hash="h")
    s.add(a)
    s.flush()
    for term, lang, articles, is_entity in rows:
        k = Keyword(term=term, normalized_term=term, language=lang, frequency=0,
                    mention_count=articles * 2, article_count=articles, is_entity=is_entity)
        s.add(k)
        s.flush()
        s.add(KeywordMention(keyword_id=k.id, article_id=a.id, count=1,
                             observed_on=date.today(), language=lang))
    s.commit()


def test_the_worklist_excludes_what_a_ring_already_covers():
    """The point of the gap digest is to resolve NEW concepts. `climat` is a shipped ring
    member (measured, not assumed — the fixture asserts it), so a job that re-resolved it
    would spend 20 s to learn what the tree already holds."""
    assert equivalence.ring_of("fr", "climat") is not None, "fixture premise moved"
    s = _sess()
    _seed_keywords(s, [("climat", "fr", 9, False), ("zzznotaword", "fr", 8, False)])
    got = [c.normalized for c in RL.gap_candidates(s, limit=10)]
    assert got == ["zzznotaword"]


def test_the_worklist_excludes_entities_and_thin_terms():
    """Entities resolve ambiguously on Wikidata (the homograph garbage vetting dropped),
    and a term below the article floor has too little spread to be worth an item."""
    s = _sess()
    _seed_keywords(s, [
        ("zzzacronym", "de", 9, True),    # entity
        ("zzzthin", "de", 1, False),      # below _RING_CAND_MIN_ARTICLES
        ("zzzgood", "de", 9, False),
    ])
    assert [c.normalized for c in RL.gap_candidates(s, limit=10)] == ["zzzgood"]


def test_the_worklist_round_robins_across_languages():
    """Draining the worst-covered language first would spend a small budget entirely on
    one language and report, truthfully, that it improved nothing anywhere else."""
    s = _sess()
    _seed_keywords(s, [(f"zzzde{i}", "de", 20 - i, False) for i in range(5)]
                   + [(f"zzzru{i}", "ru", 20 - i, False) for i in range(5)])
    langs = [c.language for c in RL.gap_candidates(s, limit=4)]
    assert sorted(langs) == ["de", "de", "ru", "ru"], langs


def test_the_gap_summary_states_that_it_made_no_network_call():
    """Invariant #14e gates every pre-action estimate that EGRESSES; this one does not,
    and the honest thing is to say so on the surface rather than leave a reader to assume
    either way. Asserted because a method string is a claim like any other."""
    s = _sess()
    _seed_keywords(s, [("zzzgood", "de", 9, False)])
    out = RL.gap_summary(s)
    assert out["candidates"] == 1
    assert out["per_language"] == {"de": 1}
    assert "No network call" in out["method"]
    assert out["seconds_per_candidate"] == RL.POLITE_SLEEP_S * 2
