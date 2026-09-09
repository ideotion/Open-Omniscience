"""The Observatory's ranked-table drill-through — audit §4.3 (P0).

``app-observatory.js`` used to pass a galaxy's curated cluster LABEL
(``hit.name`` / ``g.name`` / ``_obs.view.focus.name``) straight into
``openAnalysisFor`` as a literal full-text query. A cluster label is not text
that appears in articles: hand-verified on the live corpus, "Elections &
democracy" (the corpus's TOP galaxy by mentions) returned zero articles that
way, and "Public finance" returned 19 -- a populated, plausible, WRONG article
set presented as that galaxy's evidence (see the audit + FIX_BRIEF.md §4.3).

This file pins the fix, AS AMENDED ON 2026-09-09. The first fix was right about
WHAT to resolve and wrong about WHERE: it read ``/api/insights/supergroups``'
``members`` in the browser -- each member's normalized term plus a ring member's
cross-language surface forms -- and handed those STRINGS to ``corpus-algebra``,
which matches ``Keyword.normalized_term`` literally.

That was still TWO resolvers. The galaxy's own numbers come from
``supergroup_stats.resolve_member_keyword_ids``, which ALSO resolves a family
member's canonical-key variants, and no list of surface strings can express
that. The queue recorded the divergence as measured-latent (the live corpus's
members are all ring members, so the family branch never fires); it reproduces
on a two-article corpus with a family member "boeing" beside a keyword
"boeing's", where the ranked table counts two articles and the click opened one
-- exactly the class audit §4.3 is about.

So resolution moved to the server: ``GET /api/insights/supergroup-articles``
runs THAT function and returns the article ids, and one function now answers
both the table and the click. A galaxy whose membership resolves to no keyword
at all fails closed -- nothing opens and a toast names why -- while a galaxy
that resolves to keywords with no articles yet is a real empty answer and
opens.

Two layers, because a source assertion alone cannot prove the fix RUNS
correctly and a behavioural assertion alone cannot prove the OLD bug's three
exact call sites are gone (a fix could add a correct new path beside the old
broken one and still regress):

  1. Source-level: the three broken call sites (audit's app-observatory.js
     lines 406/444/484) are gone, the term-string path is gone with them, and
     the server resolver is what the click calls.
  2. Behavioural: ``_obsOpenGalaxy`` is DRIVEN under node with a mocked
     ``api``/``toast``/``openAnalysisForIds``, proving a resolved galaxy opens
     the analysis window on exactly the ids the endpoint returned, that an
     unresolvable one opens NOTHING and toasts an error, and that "resolved but
     empty" is not collapsed into "unresolvable".
  3. Server-level: the endpoint is driven against a constructed corpus that
     makes the two resolvers disagree, so the guard cannot pass vacuously on a
     corpus where they happen to agree.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import subprocess
import urllib.parse
from pathlib import Path

import pytest

from tests.js_source_helper import (
    assert_absent,
    assert_present,
    function_source,
    read_static,
)

_ROOT = Path(__file__).resolve().parents[1]


def _obs_js() -> str:
    return read_static("app-observatory.js")


# ---------------------------------------------------------------------------
# 1. Source-level: the exact broken call sites are gone; the real path is in.
# ---------------------------------------------------------------------------

def test_the_three_label_as_query_call_sites_are_gone() -> None:
    """The audit's exact defect lines: a galaxy's curated NAME handed to
    ``openAnalysisFor`` as a literal full-text query, from the table button,
    the canvas click, and the keyboard Enter/Space handler."""
    js = _obs_js()
    assert_absent(js, "openAnalysisFor(hit.name",
                   why="the canvas click must resolve real membership, not the label")
    assert_absent(js, "openAnalysisFor(b.dataset.obsOpen",
                   why="the table row must resolve real membership, not the label")
    assert_absent(js, "openAnalysisFor(_obs.view.focus.name",
                   why="the keyboard Enter/Space path must resolve real membership, not the label")
    # No other label-as-query path may have been left in reach of a click either.
    assert_absent(js, "openAnalysisFor(g.name",
                   why="no drill-through may pass the curated cluster label as a search query")


def test_the_drill_through_resolves_where_the_numbers_are_computed() -> None:
    """AMENDED 2026-09-09: the first fix was right about WHAT to resolve and wrong
    about WHERE.

    It read ``/api/insights/supergroups``' ``members`` here in the browser -- each
    member's normalized term plus a ring member's cross-language surface forms --
    and handed those STRINGS to ``corpus-algebra``, which matches
    ``Keyword.normalized_term`` literally. That is a SECOND resolver beside
    ``supergroup_stats.resolve_member_keyword_ids``, which the galaxy's own numbers
    use and which ALSO matches a family member's canonical-key variants. No list of
    surface strings can express that, so the two can disagree -- reproduced on a
    constructed corpus (family member "boeing", keyword "boeing's"): the ranked
    table counted two articles, the click opened one.

    So the resolution moved to the server, into one endpoint that runs the same
    function the numbers do.
    """
    js = _obs_js()
    assert_present(js, "_obsOpenGalaxy", why="the replacement resolver must exist")
    assert_present(js, "/api/insights/supergroup-articles",
                    why="membership must be resolved by the function that computes "
                        "the galaxy's own numbers, not re-derived from term strings")
    assert_present(js, "openAnalysisForIds",
                    why="must open the EXACT resolved id set, not a fresh text search")
    assert_absent(js, "/api/insights/corpus-algebra",
                  why="the term-string path is the second resolver this amendment "
                      "removed; it cannot see a family member's canonical-key variants")
    # Every former call site must still route through the resolver.
    assert_present(js, "_obsOpenGalaxy(hit.id, hit.name)")
    assert_present(js, "_obsOpenGalaxy(b.dataset.obsId, b.dataset.obsName)")
    assert_present(js, "_obsOpenGalaxy(_obs.view.focus.id, _obs.view.focus.name)")


def test_the_table_button_carries_the_galaxy_id_not_only_its_label() -> None:
    """The old markup carried only the label in ``data-obs-open`` -- there was no id to
    resolve against. The button must now carry the galaxy's real id."""
    js = _obs_js()
    assert_present(js, 'data-obs-id="${esc(g.id)}"',
                    why="the row must carry the galaxy id the resolver needs")
    assert_absent(js, "data-obs-open=", why="the label-only attribute must be gone")


def test_the_anti_vacuity_record_names_the_pre_fix_shape() -> None:
    """Prove the guard above is not vacuous -- WITHOUT reading git history.

    The first cut of this test ran ``git show HEAD:src/static/app-observatory.js``
    and asserted the three broken call sites were present in it, so that "the
    defect is gone" could not be a check that was always true. The intent was
    right and the mechanism was wrong, twice over:

      * it pins a claim to a MOVING ref -- it passed while the fix sat in the
        working tree and failed the moment the fix was committed, because HEAD
        then contained the fixed file;
      * ``actions/checkout`` fetches depth 1 by default, so the parent blob is
        not in a CI clone at all and the command would fail there regardless.

    An anti-vacuity proof must not depend on the repository's shape. So the
    pre-fix shape is RECORDED here as a literal, and what is asserted is that the
    current source no longer matches it while it does match the repair. The three
    call sites, as they stood at 227585f (docs-only, immediately before the fix):

        b.addEventListener("click", () => openAnalysisFor(b.dataset.obsOpen, ...))
        if (hit) openAnalysisFor(hit.name, {source: "observatory"});
        ... openAnalysisFor(_obs.view.focus.name, {source: "observatory"});

    Each passed a curated cluster LABEL as a literal full-text query. Measured on
    the live corpus at the time: "Elections & democracy" (the top galaxy by
    mentions) returned 0 articles, and "Public finance" returned 19 UNRELATED
    ones, presented as that galaxy's evidence.
    """
    js = read_static("app-observatory.js")
    pre_fix_shapes = (
        "openAnalysisFor(hit.name",
        "openAnalysisFor(b.dataset.obsOpen",
        "openAnalysisFor(_obs.view.focus.name",
    )
    for shape in pre_fix_shapes:
        assert shape not in js, (
            f"{shape!r} is the pre-fix label-as-query call this fix removed; "
            "its return means the Observatory is again answering with whatever "
            "articles happen to contain the cluster's name."
        )

def _harness_source() -> str:
    js = _obs_js()
    # function_source drops the `async` keyword (js_source_helper's decl-finder
    # matches on "function NAME(", which starts one token late for an async
    # declaration) -- restore it so `await` inside the body is legal syntax.
    open_galaxy = "async " + function_source(js, "_obsOpenGalaxy")
    return "\n".join([
        "'use strict';",
        "global.window = { OOI18N: { t: (s) => s } };",
        "global.OOI18N = global.window.OOI18N;",
        open_galaxy,
        _HARNESS_DRIVER,
    ])


_HARNESS_DRIVER = r"""
let toastCalls, apiCalls, openCalls, apiImpl;
function toast(msg, kind) { toastCalls.push({msg: msg, kind: kind}); }
function openAnalysisForIds(ids, label, opts) { openCalls.push({ids: ids, label: label, opts: opts}); }
async function api(url) { apiCalls.push(url); return apiImpl(url); }

async function scenario(id, name, impl) {
  toastCalls = []; apiCalls = []; openCalls = [];
  apiImpl = impl;
  await _obsOpenGalaxy(id, name);
  return { toastCalls: toastCalls, apiCalls: apiCalls, openCalls: openCalls };
}

(async () => {
  const out = {};

  // A resolvable galaxy: the endpoint answers with the ids ITS OWN resolver found.
  out.success = await scenario(5, "Elections & democracy", (url) => {
    if (url.indexOf("/api/insights/supergroup-articles") === 0) {
      return { group_id: 5, name: "Elections & democracy", members: 2,
               keyword_ids: 4, article_ids: [11, 22, 33], n_articles: 3,
               total_articles: 3, bounded: false };
    }
    throw new Error("unexpected url " + url);
  });

  // A galaxy whose membership resolves to NO keyword at all -- unresolvable.
  out.missing = await scenario(999, "Ghost galaxy", () => {
    return { group_id: 999, keyword_ids: 0, article_ids: [], n_articles: 0 };
  });

  // The request itself fails (a 404 for a removed id, an offline hiccup, ...).
  out.apiError = await scenario(5, "Elections & democracy", () => {
    throw new Error("network down");
  });

  // RESOLVED BUT EMPTY is a different fact from UNRESOLVABLE: the group has real
  // member keywords, they are simply not mentioned in any article yet. That is a
  // true empty answer and must open, not fail closed -- collapsing the two would
  // report "could not resolve" about a corpus that resolved perfectly well.
  out.resolvedEmpty = await scenario(7, "Quiet galaxy", () => {
    return { group_id: 7, keyword_ids: 12, article_ids: [], n_articles: 0,
             total_articles: 0, bounded: false };
  });

  process.stdout.write(JSON.stringify(out));
})();
"""


def _run_harness(tmp_path: Path) -> dict:
    script = tmp_path / "obs_drillthrough_harness.js"
    script.write_text(_harness_source(), encoding="utf-8")
    proc = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, f"harness failed:\n{proc.stdout}\n{proc.stderr}"
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def harness_result(tmp_path_factory) -> dict:
    return _run_harness(tmp_path_factory.mktemp("obs_dt"))


def test_resolved_galaxy_opens_the_real_membership_ids_not_the_label(harness_result) -> None:
    r = harness_result["success"]
    assert r["toastCalls"] == [], "a resolvable galaxy must not fail-close"
    assert len(r["openCalls"]) == 1, "must open the analysis window exactly once"
    call = r["openCalls"][0]
    assert call["ids"] == [11, 22, 33], (
        "must open the EXACT ids the endpoint's resolver returned -- not a set "
        "re-derived here from term strings"
    )
    assert call["label"] == "Elections & democracy", (
        "the label on the opened tab must match the label shown in the table (brief item 3)"
    )
    assert call["opts"] == {"source": "observatory"}

    # ONE request, to the endpoint that computes the galaxy's own numbers, keyed
    # by the galaxy ID -- never by its curated display name.
    calls = r["apiCalls"]
    assert len(calls) == 1, f"expected one resolution request, got {calls}"
    parsed = urllib.parse.urlparse(calls[0])
    assert parsed.path == "/api/insights/supergroup-articles", calls[0]
    assert urllib.parse.parse_qs(parsed.query)["group_id"] == ["5"], calls[0]
    assert "Elections" not in calls[0], (
        "the curated cluster label must never travel as a query term"
    )


def test_unresolvable_galaxy_fails_closed_no_window_opens(harness_result) -> None:
    r = harness_result["missing"]
    assert r["openCalls"] == [], "an unresolved galaxy must open NOTHING -- never a fallback search"
    assert len(r["toastCalls"]) == 1
    assert r["toastCalls"][0]["kind"] == "err"


def test_a_membership_fetch_failure_also_fails_closed(harness_result) -> None:
    r = harness_result["apiError"]
    assert r["openCalls"] == [], "an API failure must never fall back to a text-query guess"
    assert len(r["toastCalls"]) == 1
    assert r["toastCalls"][0]["kind"] == "err"


def test_resolved_but_empty_is_not_collapsed_into_unresolvable(harness_result) -> None:
    """Two different facts. A galaxy with twelve member keywords that nothing has
    been written about yet HAS a resolvable membership; its article set is simply
    empty. Reporting that as "could not be resolved" would describe the resolver
    as broken on a corpus where it worked perfectly."""
    r = harness_result["resolvedEmpty"]
    assert r["toastCalls"] == [], (
        "a group that resolved to real keywords must not report a resolution failure"
    )
    assert len(r["openCalls"]) == 1
    assert r["openCalls"][0]["ids"] == []


# ---------------------------------------------------------------------------
# 3. Server-level: the endpoint, on a corpus where the two resolvers DISAGREE
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def divergent_corpus(tmp_path_factory):
    """A two-article corpus built so the term-string path and the id resolver
    give DIFFERENT answers.

    The super-group has one FAMILY member, ``boeing``. The corpus holds two
    keywords -- ``boeing`` and ``boeing's`` -- mentioned in one article each.
    ``families.canonical_key`` collapses the trailing possessive, so
    ``resolve_member_keyword_ids`` returns BOTH keyword ids and the group's
    headline totals count both articles. A path that matches member terms
    literally sees only ``boeing`` and one article.

    This fixture is the anti-vacuity proof for the endpoint: without it the
    guard would pass on any corpus where the two happen to agree, which is
    every corpus whose members are all rings -- including the live one the
    divergence was first measured on.

    MODULE-SCOPED AND IDEMPOTENT, both deliberately. ``models.engine`` is bound
    once per PROCESS from the environment, so a function-scoped fixture that
    re-points ``OO_DATA_DIR`` gets the store the first import already opened --
    the second setup then hit ``UNIQUE constraint failed: sources.domain`` and
    its half-flushed session left the single-writer write gate held, which
    conftest's own guard reports as "would hang the next writer". Building once
    and looking rows up before creating them is what makes the fixture safe to
    run in a shared process.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("OO_DATA_DIR", str(tmp_path_factory.mktemp("obs_div")))
        mp.setenv("OO_DB_PLAINTEXT", "1")
        mp.setenv("OO_NO_SCHEDULER", "1")
        import datetime

        from fastapi.testclient import TestClient

        from src.api.main import app
        from src.database.models import (
            Article,
            Base,
            Keyword,
            KeywordMention,
            KeywordSuperGroup,
            KeywordSuperGroupMember,
            Source,
            engine,
            get_session,
        )

        Base.metadata.create_all(engine)
        session = get_session()
        try:
            src = session.query(Source).filter_by(domain="boeing-fixture.example").one_or_none()
            if src is None:
                src = Source(name="Divergence fixture", domain="boeing-fixture.example",
                             enabled=True, priority=1)
                session.add(src)
                session.commit()

            def _article(url, title):
                row = session.query(Article).filter_by(url=url).one_or_none()
                if row is None:
                    row = Article(url=url, canonical_url=url, source_id=src.id,
                                  title=title, content=title, hash=url)
                    session.add(row)
                    session.commit()
                return row

            def _keyword(term):
                row = session.query(Keyword).filter_by(normalized_term=term).one_or_none()
                if row is None:
                    row = Keyword(term=term, normalized_term=term, language="en")
                    session.add(row)
                    session.commit()
                return row

            plain_article = _article("https://boeing-fixture.example/1", "the plain member")
            variant_article = _article("https://boeing-fixture.example/2", "the possessive variant")
            k_plain = _keyword("boeing")
            k_variant = _keyword("boeing's")

            today = datetime.date.today()
            for kw, art, n in ((k_plain, plain_article, 3), (k_variant, variant_article, 5)):
                if session.query(KeywordMention).filter_by(
                    keyword_id=kw.id, article_id=art.id
                ).one_or_none() is None:
                    session.add(KeywordMention(keyword_id=kw.id, article_id=art.id, count=n,
                                               observed_on=today, source_id=src.id))
                # The DENORMALISED counters the ranked table reads. The app maintains
                # these at index time (store.py); a fixture that inserted mentions
                # without them would be an unfaithful corpus -- and it was, until the
                # table came back with 0 mentions beside a correctly-resolved set of
                # two keywords, which is what surfaced that the table's COUNTS and the
                # click's SET read different stores.
                kw.mention_count = n
                kw.article_count = 1
            session.commit()

            sg = session.query(KeywordSuperGroup).filter_by(name="Aviation fixture").one_or_none()
            if sg is None:
                sg = KeywordSuperGroup(name="Aviation fixture")
                session.add(sg)
                session.commit()
            if session.query(KeywordSuperGroupMember).filter_by(
                supergroup_id=sg.id, normalized_term="boeing"
            ).one_or_none() is None:
                session.add(KeywordSuperGroupMember(supergroup_id=sg.id,
                                                    normalized_term="boeing", ring_id=None))
                session.commit()

            info = {
                "group_id": sg.id,
                "plain_article": plain_article.id,
                "variant_article": variant_article.id,
            }
        finally:
            session.close()
        with TestClient(app) as client:
            yield client, info


def test_the_two_resolvers_really_do_disagree_on_this_corpus(divergent_corpus) -> None:
    """The premise, asserted rather than assumed. If a future change made the
    term-string path see the possessive variant too, every assertion below would
    still pass while testing nothing -- so the disagreement is measured first."""
    client, info = divergent_corpus
    algebra = client.get("/api/insights/corpus-algebra?terms=boeing&op=union").json()
    assert algebra["article_ids"] == [info["plain_article"]], (
        "the term-string path is expected to see ONLY the literal member term; if "
        "it now sees the variant too, this fixture no longer proves anything"
    )


def test_the_endpoint_opens_the_set_the_headline_numbers_were_computed_from(
    divergent_corpus,
) -> None:
    client, info = divergent_corpus
    body = client.get(f"/api/insights/supergroup-articles?group_id={info['group_id']}").json()
    assert body["keyword_ids"] == 2, (
        "the resolver must find the family member's canonical-key variant, which "
        "is the whole reason a term-string path cannot stand in for it"
    )
    assert sorted(body["article_ids"]) == sorted(
        [info["plain_article"], info["variant_article"]]
    ), "the click must open both articles the galaxy's own numbers counted"

    # And its MEMBERSHIP agrees with the ranked table it sits beside -- which is
    # the claim this endpoint exists to make, stated no wider than it holds.
    listing = client.get("/api/insights/supergroups").json()
    row = next(g for g in listing["supergroups"] if g["id"] == info["group_id"])
    assert row["distinct_keywords"] == body["keyword_ids"], (
        "the table and the set it opens must resolve membership through one function"
    )
    assert row["mentions"] == 8, "3 + 5 mentions across the two resolved keywords"
    # NOT the same store, and the difference is disclosed rather than hidden: the
    # table's mention/article COUNTS come from the denormalised Keyword counters
    # maintained at index time, while the article SET is read from keyword_mentions.
    # The response already carries the freshness envelope for the former, so a stale
    # counter is reported as "estimated" rather than presented as exact.
    assert listing["counts"]["basis"] in {"exact", "estimated"}, listing["counts"]


def test_an_unknown_group_is_a_404_not_an_empty_set(divergent_corpus) -> None:
    """An id that is not there and a group with nothing in it are different facts;
    returning an empty set for both would let the UI open an empty window for a
    galaxy that does not exist."""
    client, _info = divergent_corpus
    assert client.get("/api/insights/supergroup-articles?group_id=987654").status_code == 404


def test_the_bound_is_reported_rather_than_absorbed(divergent_corpus) -> None:
    """A capped answer is a true SUBSET, and says so -- the same convention
    corpus_algebra states."""
    client, info = divergent_corpus
    body = client.get(
        f"/api/insights/supergroup-articles?group_id={info['group_id']}&cap=1"
    ).json()
    assert body["n_articles"] == 1
    assert body["total_articles"] == 2
    assert body["bounded"] is True, "a truncated answer must say it was truncated"
    # Deterministic prefix, never "whichever chunk filled it first".
    assert body["article_ids"] == sorted([info["plain_article"], info["variant_article"]])[:1]
