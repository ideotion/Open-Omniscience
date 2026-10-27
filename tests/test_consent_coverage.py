"""Every button that reaches the network either asks (the ONE consent popup) or says so when the kill switch refuses it
(invariant #14 and its corollary #14e; coordinator ruling R292, item C3, after C1 = PR #1535).

WHAT THE RATCHET IS. ``EGRESS`` below is the table of the UI actions whose server handler fetches. Each row is one of three kinds, and the
table is the ruling:

* ``consent``: the client function asks first. Pinned: ``ensureOnline`` (the offline->online popup, ``app-core.js``) or ``ensureAiEgress``
  (the purpose-scoped AI-install egress window) appears in the function's OWN body. There are TWO consent functions and a check for one
  alone mislabels the AI-install buttons (the sweep that found the second one first counted only ``ensureOnline``, and so missed it).
* ``named``: the button asks nothing, because offline the kill switch already stops every byte (``airplane.py``'s socket guard plus the
  per-call refusal) and online the person already passed the one consent. What it OWES is the corollary: the refusal must be NAMED, never
  read as a quiet "0 results". That is a behaviour, so each ``named`` row is proved by a real refusal (kill switch engaged, a transport that
  reaches no socket) either in this file or in the test that the row names.
* ``gap``: a KNOWN defect, pinned as what it does today so that fixing it is a visible edit of this table. Two rows: feed verification reports
  the person's own airplane mode as the HOST being unreachable (a green "Checked." toast, an ``unreachable`` verdict stored, the feed pushed
  onto the re-check ladder). It is a clear defect (R189, invariant #14e); its fix is a separate change.

DISCOVERY runs the other way. Every ``@router.post|put|delete|patch|get`` handler in ``src/api`` that names a fetch primitive in its body
(``get_fetcher``, ``make_fetcher``, ``following_fetcher``, ``EthicalFetcher``, ``WikiClient``/``_client``) must be a row, and every row
marked ``discovered`` must still be found, both ways, zero slack. So a NEW egress route cannot ship silent: it fails here until someone
decides which of the two kinds it is.

LIMITS, stated. Discovery is by DIRECT reference in the handler body: a handler that reaches a fetcher only through a helper (the stats
refresh through ``refresh_due``) is invisible to it, so that row is listed by hand and pinned by its own test. Other undiscovered fetching
routes exist (stats ``/figures/fetch``, governments ``/load-standard``, the discover and enrich routes, weather); every client of them that was
traced on 2026-10-27 asks first, so they add no unprompted button, but nothing here would notice a change to that. The kill switch is the gate for ``named`` rows, the popup is not: an app already online fetches the moment the button is pressed, which
is the ruled behaviour of the "online implies collecting" consent, not a defect (see ``proposal-C2`` in the OSM lane's folder).
"""

from __future__ import annotations

import ast
import contextlib
import pathlib
import re
from dataclasses import dataclass, field

import pytest

from src.ingest import activate_kill_switch, clear_kill_switch, kill_switch_active

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_API = _ROOT / "src" / "api"
_STATIC = _ROOT / "src" / "static"

#: The two consent functions. Both are named so a ratchet that knows only one does not mislabel the other's callers.
_CONSENT = ("ensureOnline", "ensureAiEgress")
#: Names that make a route handler a fetching handler. A DIRECT reference in the body is the whole detector (see LIMITS).
_FETCH_REFS = {
    "get_fetcher",
    "make_fetcher",
    "following_fetcher",
    "EthicalFetcher",
    "WikiClient",
    "_client",
}
_METHODS = {"post", "put", "delete", "patch", "get"}
_KILL = "kill switch"


@dataclass(frozen=True)
class Row:
    handler: tuple[str, str]  # (path under src/api, function name)
    clients: tuple[str, ...]  # the JS functions that press it (empty: no button calls it)
    kind: str  # "consent" | "named" | "gap"
    discovered: bool = (
        True  # False: found only by hand (no direct fetcher reference in the handler)
    )
    pinned_by: str = (
        ""  # "named" proved elsewhere: "path::test_name" (else the probe in THIS file proves it)
    )
    why: str = field(default="", compare=False)


_SKIPPED = "tests/test_skipped_offline.py::test_the_batch_endpoint_carries_it_in_the_aggregate_and_each_row"

EGRESS: tuple[Row, ...] = (
    # --- consent: the client asks first -------------------------------------------------------------------------------
    Row(("events.py", "feed_import_url"), ("importIcsUrl",), "consent"),
    Row(("law.py", "add_law_document"), ("lawAddDocument", "lawSetWatched"), "consent"),
    Row(("markets.py", "import_catalog_feed"), ("importFeed",), "consent"),
    Row(
        ("markets.py", "import_all_feeds"),
        ("firstRun", "retryFailedFeeds", "loadIndicesData", "loadMarketData"),
        "consent",
    ),
    # --- named: nothing asked, the refusal is named -------------------------------------------------------------------
    Row(("events.py", "feed_import"), ("feedAction",), "named"),
    Row(("ingestion.py", "ingest_url_endpoint"), ("ingestUrl",), "named"),
    Row(("ingestion.py", "ingest_source_endpoint"), ("ingestSource",), "named", pinned_by=_SKIPPED),
    Row(("ingestion.py", "ingest_batch_endpoint"), ("ingestBatch",), "named", pinned_by=_SKIPPED),
    Row(("law.py", "law_track"), ("lawTrack",), "named"),
    Row(("markets.py", "run_rule_now"), ("runMarketRule",), "named"),
    Row(
        ("markets.py", "import_custom_feed"),
        ("importCustomFeed",),
        "named",
        why="a feed URL the person typed; the sweep first filed it under consent by mistake (no ensureOnline in its body)",
    ),
    Row(
        ("monitoring.py", "sources_health"),
        (),
        "named",
        why="a GET that probes sources; no button calls it",
    ),
    Row(("wiki.py", "track_page"), ("trackWikiPage",), "named"),
    Row(("wiki.py", "track_now"), ("trackWikiNow",), "named"),
    Row(
        ("stats.py", "refresh_stat_subscriptions"),
        ("refreshStatSubs",),
        "named",
        discovered=False,
        pinned_by="tests/test_stat_subscriptions.py::test_refresh_is_airplane_gated_no_socket",
        why="the route is a one-line wrapper over refresh_due, which opens no socket offline and counts skipped_offline",
    ),
    # --- gap: a known defect, pinned as it is so that fixing it is a visible edit of this table -----------------------
    Row(
        ("events.py", "feed_verify"),
        ("feedAction",),
        "gap",
        why="offline it stores an `unreachable` verdict and a ladder attempt for a healthy feed; the toast says Checked.",
    ),
    Row(
        ("events.py", "feed_verify_batch"),
        (),
        "gap",
        why="the same, 25 feeds at a time; no button calls it since the manual sweep was retired",
    ),
)


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #


def _strip_js_comments(text: str) -> str:
    """Drop ``//`` and ``/* */`` comments, so a sentence that merely MENTIONS ensureOnline does not count as calling it.
    String literals are not parsed (a ``//`` inside a URL string loses the rest of that line, which can only hide a call, never invent
    one, and a hidden call fails the test loudly)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?<![:\w])//[^\n]*", "", text)


def _js_bodies(name: str) -> list[str]:
    """Every definition of the JS function ``name`` across the served modules: the slice from ``function name(`` to its closing brace."""
    out: list[str] = []
    for path in sorted(_STATIC.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", text):
            i, depth = text.index("(", m.start()), 0
            while True:
                depth += {"(": 1, ")": -1}.get(text[i], 0)
                i += 1
                if depth == 0:
                    break
            j = text.index("{", i)
            k, depth = j, 0
            while True:
                depth += {"{": 1, "}": -1}.get(text[k], 0)
                k += 1
                if depth == 0:
                    break
            out.append(text[m.start() : k])
    return out


_ASKS = re.compile(r"\bawait\s+(?:" + "|".join(_CONSENT) + r")\s*\(")
_REQUEST = re.compile(r"\bapi\s*\(")


def asks_before_it_fetches(body: str) -> bool:
    """The function AWAITS a consent function (a bare call would not wait for the answer) before its first ``api(`` request.
    Comments are removed first. A body with no ``api(`` of its own (it hands the request to a helper) only needs the await."""
    code = _strip_js_comments(body)
    ask = _ASKS.search(code)
    if not ask:
        return False
    request = _REQUEST.search(code)
    return request is None or ask.start() < request.start()


def discovered_handlers() -> set[tuple[str, str]]:
    """Route handlers anywhere under ``src/api`` that name a fetch primitive in their own body or signature."""
    found: set[tuple[str, str]] = set()
    for path in sorted(_API.rglob("*.py")):
        rel = path.relative_to(_API).as_posix()
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            routed = any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr in _METHODS
                for d in fn.decorator_list
            )
            if not routed:
                continue
            names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {
                n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)
            }
            if names & _FETCH_REFS:
                found.add((rel, fn.name))
    return found


# --------------------------------------------------------------------------- #
# the static half                                                             #
# --------------------------------------------------------------------------- #


def test_every_fetching_route_handler_is_a_row_and_every_discovered_row_still_fetches():
    listed = {r.handler for r in EGRESS if r.discovered}
    seen = discovered_handlers()
    assert seen - listed == set(), (
        f"a route handler now fetches and has no row: {sorted(seen - listed)}. Decide which kind it is: ask first (consent, and the "
        "client function must await ensureOnline/ensureAiEgress before its request) or name the refusal (named, and prove it)."
    )
    assert listed - seen == set(), (
        f"rows marked discovered that no longer reference a fetch primitive: {sorted(listed - seen)}"
    )
    handlers = [r.handler for r in EGRESS]
    assert len(handlers) == len(set(handlers)), "a handler appears twice"


@pytest.mark.parametrize(
    "row", [r for r in EGRESS if r.kind == "consent"], ids=lambda r: r.handler[1]
)
def test_a_consent_row_awaits_the_answer_in_the_body_of_every_client_function(row):
    assert row.clients, "a consent row needs the button that asks"
    for client in row.clients:
        bodies = _js_bodies(client)
        assert bodies, f"{client}: not found in the served JS -- renamed?"
        assert all(asks_before_it_fetches(b) for b in bodies), (
            f"{client} reaches {row.handler} and does not `await {' / '.join(_CONSENT)}(...)` in its own code before its request"
        )


def test_the_consent_predicate_reads_code_not_prose():
    """Three shapes that a plain substring search would let through, and the real one it must accept."""
    real = 'async function f() { if (!await ensureOnline(t("x"))) return; await api("/api/x", {method: "POST"}); }'
    assert asks_before_it_fetches(real)
    assert not asks_before_it_fetches("function f() { /* ensureOnline( */ await api('/x'); }")
    assert not asks_before_it_fetches(
        "function f() {\n // consents first (ensureOnline,\n await api('/x'); }"
    )
    assert not asks_before_it_fetches("async function f() { ensureOnline('x'); await api('/x'); }")
    assert not asks_before_it_fetches(
        "async function f() { await api('/x'); await ensureOnline('x'); }"
    )


@pytest.mark.parametrize(
    "row", [r for r in EGRESS if r.kind in ("named", "gap")], ids=lambda r: r.handler[1]
)
def test_a_named_or_gap_row_has_a_live_client_and_a_proof(row):
    for client in row.clients:
        assert _js_bodies(client), f"{client}: not found in the served JS -- renamed?"
    assert not any(
        asks_before_it_fetches(b) for client in row.clients for b in _js_bodies(client)
    ), (
        "this row's client now asks first: reclassify the row as consent so the table stays the ruling"
    )
    if row.pinned_by:
        path, _, test = row.pinned_by.partition("::")
        text = (_ROOT / path).read_text(encoding="utf-8")
        assert re.search(r"^def " + re.escape(test) + r"\(", text, re.M), (
            f"{row.pinned_by}: the test is gone"
        )
        assert "skipped_offline" in text
    else:
        assert row.handler in _PROBES, (
            f"{row.handler}: needs a probe in this file or a pinned_by test"
        )


def test_the_probes_are_exactly_the_rows_that_have_no_other_proof():
    probed = {r.handler for r in EGRESS if r.kind in ("named", "gap") and not r.pinned_by}
    assert set(_PROBES) == probed, f"probe and table disagree: {sorted(set(_PROBES) ^ probed)}"


# --------------------------------------------------------------------------- #
# the behavioural half: a REAL refusal                                        #
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def airplane_mode():
    was = kill_switch_active()
    activate_kill_switch()
    try:
        yield
    finally:
        (activate_kill_switch if was else clear_kill_switch)()


_H = {"Sec-Fetch-Site": "same-origin", "Referer": "http://127.0.0.1/", "Origin": "http://127.0.0.1"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """The real app on a throwaway FILE database (so a route's threadpool thread sees the rows), loopback host, and a private data
    folder (the feed verdict and attempt files are written under it)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.api.main import app
    from src.database.models import Base
    from src.database.session import get_db

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    engine = create_engine(
        f"sqlite:///{tmp_path / 'consent.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, base_url="http://127.0.0.1") as c:
            c.sessionmaker = Session  # type: ignore[attr-defined]
            yield c
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _seed_source(c):
    from src.database.models import Source

    with c.sessionmaker() as s:
        src = Source(
            name="Consent probe",
            domain="consent-probe.test",
            rss_url="https://consent-probe.test/rss",
        )
        s.add(src)
        s.commit()
        return src.id


def _kill(text) -> bool:
    return isinstance(text, str) and _KILL in text.lower()


# Each probe returns (response, whether it says what the row claims). The predicates read the TOP LEVEL of the answer the button reads,
# never a string nested somewhere in it: a refusal that is only a field of a per-item record is exactly the shape that hides it.


def _probe_feed_import(c):
    r = c.post("/api/events/feeds/wph-hol-ad/import", headers=_H)
    return r, r.status_code == 502 and _kill(r.json().get("detail"))


def _probe_ingest_url(c):
    sid = _seed_source(c)
    r = c.post(
        "/api/ingest", json={"source_id": sid, "url": "https://consent-probe.test/a"}, headers=_H
    )
    j = r.json()
    return r, r.status_code == 200 and j.get("result") == "fetch_failed" and _kill(j.get("detail"))


def _probe_law_track(c):
    from src.database.models import LawDocument

    with c.sessionmaker() as s:
        s.add(
            LawDocument(
                jurisdiction="kh",
                title="Consent probe",
                url="https://consent-probe.test/law",
                watched=True,
            )
        )
        s.commit()
    r = c.post("/api/law/track", headers=_H)
    return r, r.status_code == 200 and r.json().get("skipped_offline") == 1


def _probe_run_rule(c):
    from src.database.models import MarketExtractionRule

    sid = _seed_source(c)
    with c.sessionmaker() as s:
        rule = MarketExtractionRule(
            source_id=sid,
            category="commodity",
            symbol="CPRB",
            url="https://consent-probe.test/p",
            selector=".p",
            currency="USD",
            unit="kg",
        )
        s.add(rule)
        s.commit()
        rid = rule.id
    r = c.post(f"/api/markets/rules/{rid}/run", headers=_H)
    j = r.json()
    return r, r.status_code == 200 and j.get("status") == "fetch_failed" and (
        _kill(j.get("detail")) or _kill(j.get("reason"))
    )


def _probe_import_custom_feed(c):
    body = {
        "url": "https://consent-probe.test/x.csv",
        "symbol": "CPRB",
        "unit": "t",
        "currency": "USD",
    }
    r = c.post("/api/markets/feeds/import-url", json=body, headers=_H)
    detail = r.json().get("detail")
    return r, r.status_code == 502 and isinstance(detail, dict) and _kill(detail.get("detail"))


def _probe_sources_health(c):
    _seed_source(c)
    r = c.get("/api/monitoring/health?limit=1", headers=_H)
    return r, r.status_code == 200 and r.json().get("summary", {}).get(
        "refused_by_kill_switch"
    ) == 1


def _probe_track_page(c):
    from src.wiki.track import ensure_page

    with c.sessionmaker() as s:
        page = ensure_page(s, "enwiki", "Consent_probe")
        s.commit()
        pid = page.id
    r = c.post(f"/api/wiki/pages/{pid}/track?ores=false", headers=_H)
    return r, r.status_code == 502 and _kill(r.json().get("detail"))


def _probe_track_now(c):
    from src.wiki.track import ensure_page

    with c.sessionmaker() as s:
        ensure_page(s, "enwiki", "Consent_probe")
        s.commit()
    r = c.post("/api/wiki/track-now?ores=false", headers=_H)
    return r, r.status_code == 200 and r.json().get("skipped_offline") == 1


def _probe_feed_verify_gap(c):
    """THE DEFECT, as it is today: 200, an `unreachable` verdict (the HOST is blamed), nothing at the top level naming the switch."""
    r = c.post("/api/events/feeds/wph-hol-ad/verify", headers=_H)
    j = r.json()
    verdict = j.get("verdict") or {}
    return r, r.status_code == 200 and verdict.get("status") == "unreachable" and not any(
        _kill(v) for v in j.values() if isinstance(v, str)
    )


def _probe_feed_verify_batch_gap(c):
    r = c.post("/api/events/feeds/verify-batch", headers=_H)
    j = r.json()
    verdicts = j.get("verdicts") or {}
    return r, r.status_code == 200 and j.get("ok") == 0 and bool(verdicts) and all(
        v.get("status") == "unreachable" for v in verdicts.values()
    )


_PROBES = {
    ("events.py", "feed_import"): _probe_feed_import,
    ("ingestion.py", "ingest_url_endpoint"): _probe_ingest_url,
    ("law.py", "law_track"): _probe_law_track,
    ("markets.py", "run_rule_now"): _probe_run_rule,
    ("markets.py", "import_custom_feed"): _probe_import_custom_feed,
    ("monitoring.py", "sources_health"): _probe_sources_health,
    ("wiki.py", "track_page"): _probe_track_page,
    ("wiki.py", "track_now"): _probe_track_now,
    ("events.py", "feed_verify"): _probe_feed_verify_gap,
    ("events.py", "feed_verify_batch"): _probe_feed_verify_batch_gap,
}


@pytest.mark.parametrize("handler", sorted(_PROBES), ids=lambda h: h[1])
def test_pressed_in_airplane_mode_a_route_does_what_its_row_claims(client, handler):
    row = next(r for r in EGRESS if r.handler == handler)
    with airplane_mode():
        r, ok = _PROBES[handler](client)
    assert r.status_code != 404, (
        f"the probe did not reach the route ({r.status_code}): {r.text[:200]}"
    )
    if row.kind == "gap":
        assert ok, (
            f"{handler} no longer behaves as the gap row says -- if the defect is fixed, move the row to `named` and make its probe "
            f"assert the top-level refusal. {r.status_code} {r.text[:300]}"
        )
    else:
        assert ok, (
            f"{handler}: the refusal is not named at the top level of the answer -- {r.status_code} {r.text[:300]}"
        )
