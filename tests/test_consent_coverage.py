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
* ``gap``: a KNOWN defect, pinned as what it does today so that fixing it is a visible edit of this table. Two at present (see the rows):
  the source preflight and the RSS discovery read the person's airplane mode as the SOURCES being unreachable or having no feed. The two
  feed-verification rows were gaps until R296 and are ``named`` now.

DISCOVERY runs the other way, in two steps, and a row records which step finds it (``found``):

* ``direct``: a route handler anywhere under ``src/api`` that names a fetch primitive in its own body (``get_fetcher``, ``make_fetcher``,
  ``following_fetcher``, ``EthicalFetcher``, ``WikiClient``/``_client``, ``guarded_session``).
* ``hop``: ONE hop further. A handler that calls a function which itself names a primitive in its own body, where the call is resolved the
  way Python resolves it: a name imported from a ``src`` module (``from src.x import f``; ``from src import m`` then ``m.f``) or a function
  defined in the handler's own file. Never a bare method name, which would match every ``get`` and ``close`` in the tree.
* ``hand``: a row listed by hand because neither step can see it; it must stay invisible to both (zero slack the other way), so a scan
  that learns to see it forces the row to be reclassified.

Every ``direct`` and ``hop`` handler must be a row and every such row must still be found, zero slack. So a NEW egress route cannot ship
silent: it fails here until someone decides which of the two kinds it is.

LIMITS, stated. The scan reaches EXACTLY ONE hop. A handler that reaches a fetcher through two functions (a job object's ``start`` calling
a worker that calls a fetcher: the governments load, the Wikidata items fetch, the enrichment pass; a stats fetch whose fetching function
does not itself name the guarded session), through a decorator, or through a method on an object, is invisible to it and is a ``hand``
row, pinned by the proof its kind needs. The wiki-dump, OSM-download and AI-install managers (``wiki/dumps.py``,
``geo/osm_downloads.py``, ``llm/installer.py``) are NOT covered by this table at all: their routes reach a manager object, two functions
from any fetcher, so the scan cannot see them and no row lists them (a stated gap, not a finding). The kill switch is the gate for ``named`` rows, the popup is
not: an app already online fetches the moment the button is pressed, which is the ruled behaviour of the "online implies collecting"
consent, not a defect (see ``proposal-C2`` in the OSM lane's folder).
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
_SRC = _ROOT / "src"
_API = _SRC / "api"
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
    "guarded_session",
}
_METHODS = {"post", "put", "delete", "patch", "get"}
_KILL = "kill switch"


@dataclass(frozen=True)
class Row:
    handler: tuple[str, str]  # (path under src/api, function name)
    clients: tuple[str, ...]  # the JS functions that press it (empty: no button calls it)
    kind: str  # "consent" | "named" | "gap"
    found: str = "direct"  # "direct" | "hop" | "hand": which discovery step sees the handler (see the module docstring)
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
    # found one hop away, or by hand (the module docstring says why each is invisible to a direct scan)
    Row(("weather.py", "weather_context"), ("claimWeather", "cardWeatherFetch"), "consent", found="hop"),
    Row(
        ("stats.py", "fetch_figures"),
        ("fetchStatFigure",),
        "consent",
        found="hand",
        why="the fetching function (stats/fetch.py) opens the guarded session two calls below the handler",
    ),
    Row(
        ("governments.py", "load_standard"),
        ("govLoadStandard",),
        "consent",
        found="hand",
        why="the handler starts a job object whose worker fetches (two hops)",
    ),
    Row(
        ("entities.py", "items_fetch"),
        ("entitySpineFetch",),
        "consent",
        found="hand",
        why="the handler starts a job object whose worker fetches (two hops)",
    ),
    Row(
        ("diagnostics/discovery.py", "discover_sources_endpoint"),
        ("discoverSources",),
        "consent",
        found="hand",
        why="the discovery module opens the session, reached through a function that does not name it",
    ),
    Row(
        ("diagnostics/discovery.py", "discover_world_sources"),
        ("discoverWorld",),
        "consent",
        found="hand",
        why="a job object whose worker fetches (two hops)",
    ),
    Row(
        ("diagnostics/discovery.py", "enrich_source_types"),
        ("enrichSourceTypes",),
        "consent",
        found="hand",
        why="a job object whose worker fetches (two hops)",
    ),
    # --- named: nothing asked, the refusal is named -------------------------------------------------------------------
    Row(("events.py", "feed_import"), ("feedAction",), "named"),
    Row(("events.py", "feed_verify"), ("feedAction",), "named"),
    Row(
        ("events.py", "feed_verify_batch"),
        (),
        "named",
        why="no button calls it since the manual sweep was retired",
    ),
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
    Row(
        ("hazards.py", "list_hazards"),
        (),
        "named",
        found="hop",
        why="a GET the map does not call (it reads the time map); each feed's failure names the kill switch in `failures`",
    ),
    Row(
        ("signals.py", "signals_hazards_snapshot"),
        (),
        "named",
        found="hop",
        why="`refresh=1` pulls the feeds through fetch_hazards; offline it saves nothing and each feed's failure names the kill switch",
    ),
    Row(
        ("source_management.py", "resolve_qid_names"),
        (),
        "named",
        found="hop",
        why="refuses up front with a 409 that names the kill switch; no button calls it",
    ),
    Row(("wiki.py", "track_page"), ("trackWikiPage",), "named"),
    Row(("wiki.py", "track_now"), ("trackWikiNow",), "named"),
    # --- gap: KNOWN defects, pinned as they behave today (a fix is a visible edit of this table) ----------------------
    Row(
        ("source_management.py", "run_source_preflight"),
        (),
        "gap",
        found="hop",
        why=(
            "pressed in airplane mode it records EVERY enabled source as unreachable, writes the preflight log (which marks the first-run "
            "preflight done) and answers with the sources' domains under `unreachable`; the refusal is only inside each record's robots_error. "
            "No button calls it"
        ),
    ),
    Row(
        ("source_management.py", "discover_rss_feeds"),
        (),
        "gap",
        found="hand",
        why=(
            "in airplane mode it answers 200 'Discovered RSS feeds for 0 sources' for sources it never asked about; reached through a "
            "SourceManager method. No button calls it"
        ),
    ),
    Row(
        ("stats.py", "refresh_stat_subscriptions"),
        ("refreshStatSubs",),
        "named",
        found="hand",
        pinned_by="tests/test_stat_subscriptions.py::test_refresh_is_airplane_gated_no_socket",
        why="the route is a one-line wrapper over refresh_due, which opens no socket offline and counts skipped_offline",
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


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)
    }


def _routed(fn: ast.AST) -> bool:
    return any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in _METHODS
        for d in getattr(fn, "decorator_list", [])
    )


def _functions(tree: ast.AST):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _src_module(dotted: str) -> str | None:
    """``src.stats.fetch`` -> ``stats/fetch.py`` (or ``stats/fetch/__init__.py``), relative to ``src``; None when it is not a file here."""
    base = _SRC.joinpath(*dotted.split(".")[1:])
    for cand in (base.with_suffix(".py"), base / "__init__.py"):
        if cand.exists():
            return cand.relative_to(_SRC).as_posix()
    return None


def _imports(scope: ast.AST) -> dict[str, tuple[str, str | None]]:
    """Local name -> (dotted ``src`` module, symbol or None for a module import)."""
    out: dict[str, tuple[str, str | None]] = {}
    for n in ast.walk(scope):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.split(".")[0] == "src":
            for a in n.names:
                out[a.asname or a.name] = (n.module, a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[0] == "src":
                    out[a.asname or a.name.split(".")[0]] = (a.name, None)
    return out


#: The files that DEFINE the fetch primitives: a function there naming one is the primitive itself, not a caller of it.
_PRIMITIVE_HOMES = {"safety/fetcher.py", "ingest/__init__.py"}
_names_primitive_cache: dict[tuple[str, str], bool] = {}


def _def_names_primitive(rel: str, name: str) -> bool:
    """Does the function ``name`` defined in ``src/<rel>`` name a fetch primitive in its OWN body? (the one hop)"""
    key = (rel, name)
    if key not in _names_primitive_cache:
        tree = ast.parse((_SRC / rel).read_text(encoding="utf-8"))
        _names_primitive_cache[key] = rel not in _PRIMITIVE_HOMES and any(
            fn.name == name and _names(fn) & _FETCH_REFS for fn in _functions(tree)
        )
    return _names_primitive_cache[key]


def discovered_handlers() -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """``(direct, hop)``: route handlers under ``src/api`` that name a fetch primitive in their own body, and those that call (ONE hop) a
    function that does. A call resolves only through an import from a ``src`` module or a function defined in the handler's own file."""
    direct: set[tuple[str, str]] = set()
    hop: set[tuple[str, str]] = set()
    for path in sorted(_API.rglob("*.py")):
        rel = path.relative_to(_API).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module_imports = _imports(
            ast.Module(
                body=[n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))],
                type_ignores=[],
            )
        )
        local = {
            fn.name
            for fn in _functions(tree)
            if not _routed(fn) and _names(fn) & _FETCH_REFS
        }
        for fn in _functions(tree):
            if not _routed(fn):
                continue
            if _names(fn) & _FETCH_REFS:
                direct.add((rel, fn.name))
                continue
            imported = {**module_imports, **_imports(fn)}
            for call in (c for c in ast.walk(fn) if isinstance(c, ast.Call)):
                f = call.func
                if isinstance(f, ast.Name) and f.id in local:
                    hop.add((rel, fn.name))
                elif isinstance(f, ast.Name) and f.id in imported:
                    mod, sym = imported[f.id]
                    target = _src_module(mod)
                    if target and sym and _def_names_primitive(target, sym):
                        hop.add((rel, fn.name))
                elif (
                    isinstance(f, ast.Attribute)
                    and isinstance(f.value, ast.Name)
                    and f.value.id in imported
                ):
                    mod, sym = imported[f.value.id]
                    target = _src_module(f"{mod}.{sym}" if sym else mod) or _src_module(mod)
                    if target and _def_names_primitive(target, f.attr):
                        hop.add((rel, fn.name))
    return direct, hop


# --------------------------------------------------------------------------- #
# the static half                                                             #
# --------------------------------------------------------------------------- #


def test_every_fetching_route_handler_is_a_row_and_every_discovered_row_still_fetches():
    direct, hop = discovered_handlers()
    by_step = {step: {r.handler for r in EGRESS if r.found == step} for step in ("direct", "hop", "hand")}
    assert direct - by_step["direct"] == set(), (
        f"a route handler now fetches and has no row: {sorted(direct - by_step['direct'])}. Decide which kind it is: ask first (consent, and "
        "the client function must await ensureOnline/ensureAiEgress before its request) or name the refusal (named, and prove it)."
    )
    assert hop - direct - by_step["hop"] == set(), (
        f"a route handler now calls (one hop) a function that fetches and has no row: {sorted(hop - direct - by_step['hop'])}. Decide "
        "which kind it is, as above."
    )
    assert by_step["direct"] - direct == set(), (
        f"rows marked direct that no longer reference a fetch primitive: {sorted(by_step['direct'] - direct)}"
    )
    assert by_step["hop"] - (hop - direct) == set(), (
        f"rows marked hop that the one-hop scan no longer finds: {sorted(by_step['hop'] - (hop - direct))}"
    )
    assert by_step["hand"] & (direct | hop) == set(), (
        f"rows marked hand that the scan now sees: {sorted(by_step['hand'] & (direct | hop))} -- mark them direct or hop"
    )
    assert {r.found for r in EGRESS} <= {"direct", "hop", "hand"}
    handlers = [r.handler for r in EGRESS]
    assert len(handlers) == len(set(handlers)), "a handler appears twice"


def test_the_scan_reaches_exactly_one_hop():
    """The limit, pinned: the governments load reaches its fetcher through a job object's worker (two hops) and the stats fetch through a
    function that does not itself name the session, so neither may be found; a scan that grew a second hop would find them and force the
    two ``hand`` rows to be reclassified (the test above), which is the point."""
    direct, hop = discovered_handlers()
    seen = direct | hop
    assert ("governments.py", "load_standard") not in seen
    assert ("stats.py", "fetch_figures") not in seen
    assert ("weather.py", "weather_context") in hop and ("hazards.py", "list_hazards") in hop


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


def _probe_feed_verify(c):
    r = c.post("/api/events/feeds/wph-hol-ad/verify", headers=_H)
    j = r.json()
    return r, r.status_code == 200 and j.get("skipped_offline") == 1 and (
        j.get("verdict") or {}
    ).get("status") == "skipped_offline"


def _probe_feed_verify_batch(c):
    r = c.post("/api/events/feeds/verify-batch?limit=2", headers=_H)
    j = r.json()
    return r, r.status_code == 200 and j.get("skipped_offline") == 2 and j.get(
        "checked"
    ) == 0 and j.get("verdicts") == {}


def _probe_list_hazards(c):
    r = c.get("/api/hazards", headers=_H)
    failures = r.json().get("failures")
    return r, r.status_code == 200 and isinstance(failures, list) and len(failures) >= 1 and all(
        _kill(f) for f in failures
    )


def _probe_signals_hazards_snapshot(c):
    r = c.post("/api/signals/hazards/snapshot?refresh=true", headers=_H)
    j = r.json()
    failures = j.get("failures")
    return r, r.status_code == 200 and j.get("saved") is False and isinstance(failures, list) and len(
        failures
    ) >= 1 and all(_kill(f) for f in failures)


def _probe_resolve_qid_names(c):
    r = c.post("/api/sources/resolve-qid-names", headers=_H)
    return r, r.status_code == 409 and "airplane mode is engaged" in str(r.json().get("detail"))


def _probe_run_source_preflight(c):
    """GAP: the manual preflight reads airplane mode as the SOURCES being unreachable (and logs it as a completed sweep)."""
    _seed_source(c)
    r = c.post("/api/sources/preflight?limit=5", headers=_H)
    j = r.json()
    return r, r.status_code == 200 and j.get("unreachable") == ["consent-probe.test"] and "skipped_offline" not in j


def _probe_discover_rss_feeds(c):
    """GAP: a source with no feed is 'checked' and reported as having none, while nothing was asked of its host."""
    from src.database.models import Source

    with c.sessionmaker() as s:
        s.add(Source(name="No feed", domain="no-feed.test", rss_url=None))
        s.commit()
    r = c.post("/api/sources/discover/rss", headers=_H)
    j = r.json()
    return r, r.status_code == 200 and j.get("total_checked") == 1 and j.get("with_rss_found") == 0 and not _kill(
        r.text
    )


_PROBES = {
    ("hazards.py", "list_hazards"): _probe_list_hazards,
    ("signals.py", "signals_hazards_snapshot"): _probe_signals_hazards_snapshot,
    ("source_management.py", "resolve_qid_names"): _probe_resolve_qid_names,
    ("source_management.py", "run_source_preflight"): _probe_run_source_preflight,
    ("source_management.py", "discover_rss_feeds"): _probe_discover_rss_feeds,
    ("events.py", "feed_import"): _probe_feed_import,
    ("ingestion.py", "ingest_url_endpoint"): _probe_ingest_url,
    ("law.py", "law_track"): _probe_law_track,
    ("markets.py", "run_rule_now"): _probe_run_rule,
    ("markets.py", "import_custom_feed"): _probe_import_custom_feed,
    ("monitoring.py", "sources_health"): _probe_sources_health,
    ("wiki.py", "track_page"): _probe_track_page,
    ("wiki.py", "track_now"): _probe_track_now,
    ("events.py", "feed_verify"): _probe_feed_verify,
    ("events.py", "feed_verify_batch"): _probe_feed_verify_batch,
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
