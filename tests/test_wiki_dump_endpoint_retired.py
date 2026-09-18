"""Q728's retirement, pinned where a route actually lives.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q728 = a (ruled 2026-09-15): "The modal becomes the Living sources view; the dump
machinery stays (it is built and tested) as an opt-in offline reader, never the
tracking path; the dump->corpus endpoint is retired."

TWO CLAUSES, AND THIS FILE GUARDS BOTH DIRECTIONS. A test that only asserted the
route was gone would be satisfied by deleting the whole dump subsystem, which the
same ruling forbids in the sentence before. So the absence of the ROUTE and the
presence of the READER are asserted together, here, where the pair is visible.

ANCHORED TO THE ROUTER'S OWN DEFINITIONS, NEVER ``app.routes``. The recorded defect:
a guard reading the shared, mutable ``src.api.main.app`` singleton's ``.routes`` went
flaky in CI on a POSITIVE assertion and was never reproducible locally. A NEGATIVE
read of that singleton is safe (a missing route cannot fail it), but the router's own
list is both safe and precise, so there is no reason to reach for the process global.
"""

from __future__ import annotations

import pathlib

#: The route as the DECORATOR spells it, and as the ROUTER exposes it. Two strings,
#: because they are two different things and asserting the first against the second is
#: the recorded wiring-test defect: a guard that compared the halves side by side
#: passed for months while a real prefix mismatch 404'd in the field. Composed here,
#: once, from the router's own prefix rather than a hardcoded copy of it.
RETIRED_DECORATOR_PATH = "/dumps/corpus-ingest"
_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _retired_full_path() -> str:
    from src.api.wiki import router

    return router.prefix + RETIRED_DECORATOR_PATH


def _wiki_router_paths() -> set[str]:
    from src.api.wiki import router

    return {getattr(r, "path", "") for r in router.routes}


def test_the_dump_to_corpus_endpoint_is_GONE_from_the_router():
    paths = _wiki_router_paths()
    assert paths, "the wiki router defines no routes at all -- this guard would pass on anything"
    # SANITY, and it is not decoration: the first version of this file compared the
    # DECORATOR path against paths that all carry the router's prefix, so it asserted
    # the absence of a string that could never have been present. A guard that cannot
    # fail is worse than no guard, because it reports safety.
    assert _retired_full_path().startswith("/api/wiki/"), "the router prefix moved"
    assert f"{router_prefix()}/dumps/page" in paths, (
        "the composition is wrong, so the absence assertion below means nothing"
    )
    assert _retired_full_path() not in paths, (
        "POST /api/wiki/dumps/corpus-ingest is back. Q728 = a retired it: a dump is a "
        "SNAPSHOT as of its build date, so an article ingested from one enters the "
        "corpus with stale text and nothing saying it has since changed -- which is "
        "the claim the live lane exists to avoid making."
    )


def router_prefix() -> str:
    from src.api.wiki import router

    return router.prefix


def test_it_is_gone_from_the_APP_too_so_no_second_wiring_re_adds_it():
    """A negative read of the shared app is safe, and it catches a re-add through
    another router that the per-router check above would not see."""
    from src.api.main import app

    assert _retired_full_path() not in {getattr(r, "path", "") for r in app.routes}


def test_the_request_model_is_gone_with_it():
    """A model with no endpoint is the shape of a half-removal that reads as done."""
    import src.api.wiki as wiki_api

    assert not hasattr(wiki_api, "IngestDumpPages"), (
        "the endpoint's request model survived its endpoint"
    )


def test_the_OFFLINE_READER_stays_because_the_same_ruling_says_so():
    """The other half. Deleting the dump subsystem would satisfy a naive absence test."""
    from src.wiki.corpus import ingest_dump_pages

    assert callable(ingest_dump_pages), (
        "Q728's first clause keeps the dump machinery as an opt-in offline reader; "
        "it is the FUNCTION an operator with a dump on disk uses, not the route"
    )
    paths = _wiki_router_paths()
    prefix = router_prefix()
    for kept in ("/dumps/page", "/dumps/search", "/dumps/fts-search", "/dumps/readable"):
        assert prefix + kept in paths, f"the offline reader lost {kept}, which the ruling keeps"


def test_no_caller_anywhere_still_POSTs_the_retired_path():
    """A frontend call site left behind would 404 in the field with no test failing.

    Searched over the whole tree rather than one file: the recorded defect is a
    two-file removal guarded in one file, where re-adding the other half passed
    unchanged.
    """
    import re

    offenders = []
    for path in list(_ROOT.glob("src/**/*.py")) + list(_ROOT.glob("src/**/*.js")):
        text = path.read_text(encoding="utf-8", errors="replace")
        # COMMENTS STRIPPED FIRST. The retirement's own note names the path it
        # retired -- as it should, so the next reader knows what was there and why --
        # and a guard that could not tell a call from a note ABOUT a call would
        # accuse the comment that documents the removal. (The inverse of the
        # recorded defect, where a "must be gone" guard stayed green because the
        # string survived inside `// callName();`.)
        code = re.sub(r"^\s*#[^\n]*$", "", text, flags=re.M)
        code = re.sub(r"^\s*//[^\n]*$", "", code, flags=re.M)
        if RETIRED_DECORATOR_PATH in code:
            offenders.append(path.relative_to(_ROOT).as_posix())
    assert not offenders, f"the retired path is still called by: {offenders}"
