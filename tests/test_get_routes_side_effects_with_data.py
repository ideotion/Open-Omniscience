"""The GETs that answered 4xx on an empty database are driven again WITH DATA behind them (audit 0.5.0 item 35 follow-on, P3b).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``tests/test_get_routes_side_effects.py`` drives every GET once on whatever database the suite holds and names what each one does. On
that database 74 GETs (on 2026-10-27) answered 4xx before their handler body ran: a path id that does not exist, a query parameter
the schema requires, an artifact a POST job would have made. Whatever those handlers do with a real row is exactly what the first
file never measured. This file seeds a small corpus (a source and its group and metadata, an article, a law document with two
revisions, a watched wiki page with two revisions, commodity prices, an edition, an import report, a custody entry), builds a
valid request for each route from the seeded ids, and drives it under the SAME monitors and the SAME tables as the first file, so
a handler that opens a socket, starts a thread or a program, writes or removes a file or changes the database fails here by name.

It MEASURES; it does not fix. A new effect found here is routed to the lane that owns the handler (through the coordinator) and is
listed in ``_ROUTES_WITH_DATA`` as a FINDING with the reason, exactly as the first file lists F1 and F2.

Stated limits, in addition to the first file's: the corpus is one row of each kind, so a handler that branches on a second row, on
a particular language or on a larger table is measured on its simplest path. Ten driven routes still answer from their EMPTY branch
because the seed lacks a fact they need (stored revision text, a matching article series, a lane store); they are listed in
``_EMPTY_BRANCH``, and what they do with a row is not measured. Seven routes are not driven at all (``_NOT_DRIVEN``: five serve only an
in-memory job result, two read a lane store). The artifacts a POST job would leave (an all-diagnostics archive, a keyword-parts set, a
model-bench, ai-check, release-run, fold and re-index report) are PLANTED by hand, which is how three of them were found to append to
``diagnostics/runs.jsonl`` (``_ROUTES_WITH_DATA``). Directories are not watched, as in the first file: a GET that creates or touches a
folder (``all-job/volumes`` makes its ``volumes`` folder, a keyword-part download touches its set's mtime) is invisible. The seeded
rows are removed in the fixture's teardown from the suite's shared database and the teardown asserts none remain; a crash between seed
and teardown would leave them, which is why the rows that can carry a name do (``oo-getdata-probe``); prices, revisions and metadata
are removed by their parent's cascade or, for the commodity prices, only when this file made them.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_get_routes_side_effects import (
    _LOOPBACK_ROUTES,
    _PROGRAMS_ALLOWED,
    _ROUTES,
    _SQL_WRITES_ALLOWED,
    _analysis_extra_installed,
    _file_and_thread_problems,
    _is_loopback,
    _Monitor,
)

_MARK = "oo-getdata-probe"
_GOLD_SET = Path(__file__).resolve().parent.parent / "configs" / "ir_eval" / "gold_set.example.json"
_QID = "Q90000001"  # a Wikidata-shaped id no real item has (the cache row is the seed's own)
_PLACE = "node/90000001"

# Routes with no URL here, each for a reason read from the handler (the 2026-10-27 review found the first list's reasons false for 14
# of 21 and drove them; what stays is what cannot be driven without running a job or building a second store).
_NOT_DRIVEN: dict[str, str] = {
    "/api/diagnostics/card-audit/download": "serves only the in-memory result of POST /api/diagnostics/card-audit (no on-disk fallback)",
    "/api/diagnostics/keyword-triage/download": "serves only the in-memory result of POST /api/diagnostics/keyword-triage",
    "/api/diagnostics/p0-validation/download": "serves only the in-memory result of POST /api/diagnostics/p0-validation",
    "/api/diagnostics/perception-extract/download": "serves only the in-memory result of POST /api/diagnostics/perception-extract",
    "/api/diagnostics/source-tags/download": "serves only the in-memory result of POST /api/diagnostics/source-tags",
    "/api/osm/objects/{osm_type}/{osm_id}": "reads the OpenStreetMap lane store, a second database an import job builds (buildable locally; more than this file's seed)",
    "/api/wiki/lane/version": "reads the Wikipedia lane store, a second database an import job builds (buildable locally; more than this file's seed)",
}

# Routes that exist only with the `[analysis]` extra (numpy, pandas, scipy, sklearn, statsmodels): the Core-only install does not mount them, so
# they are neither driven nor required there. Every other route in either table is mounted on both installs.
_NEEDS_ANALYSIS_EXTRA: dict[str, str] = {
    "/api/commodities/{symbol}/correlation": "the commodity router is disabled without numpy/pandas (it says so at boot)",
}

_RUNS_LOG = (
    "FINDING F3 (routed): serving a diagnostics file appends a begin and an end line to diagnostics/runs.jsonl "
    "(src/monitoring/diagnostics_runs.py serve_begin/serve_end via served_file_response); a local download log, found only once the artifact is planted"
)
# Per-route allowances found WITH data, on top of the first file's ``_ROUTES``: (files it may create or change, thread names it
# may start, reason). Every line is a FINDING or a stated reason.
_ROUTES_WITH_DATA: dict[str, tuple[frozenset[str], frozenset[str], str]] = {
    "/api/diagnostics/all-job/download": (frozenset({"runs.jsonl", "runs.jsonl.lock"}), frozenset(), _RUNS_LOG),
    "/api/diagnostics/all-job/volumes/{name}": (frozenset({"runs.jsonl", "runs.jsonl.lock"}), frozenset(), _RUNS_LOG),
    "/api/diagnostics/keywords/parts/{set_id}/{name}": (frozenset({"runs.jsonl", "runs.jsonl.lock"}), frozenset(), _RUNS_LOG),
}


def _merged_routes() -> dict[str, tuple[frozenset[str], frozenset[str], str]]:
    out = dict(_ROUTES)
    for path, (files, threads, reason) in _ROUTES_WITH_DATA.items():
        old = out.get(path, (frozenset(), frozenset(), ""))
        out[path] = (old[0] | files, old[1] | threads, (old[2] + " | " + reason).strip(" |"))
    return out


# Routes that answer 2xx here on their EMPTY branch even with the seed (the handler needs a fact the seed does not make), so what they do
# with a row is NOT measured by this file. Stated, so the 53 are not read as 53 data-path measurements.
_EMPTY_BRANCH: dict[str, str] = {
    "/api/law/documents/{document_id}/compare": "the seeded revisions carry no stored text, so the diff code answers text-not-held",
    "/api/wiki/pages/{page_id}/compare": "the seeded revisions carry no stored text, so the diff code answers text-not-held",
    "/api/commodities/{symbol}/correlation": "30 daily prices and no matching article series: insufficient_data",
    "/api/entities/dossier": "reads the Wikipedia lane store: lane-never-run",
    "/api/entities/places/by-wiki": "reads the Wikipedia lane store: lane-never-run",
    "/api/entities/places/search": "reads the places lane store: lane-never-run",
    "/api/wiki/lane/sections": "reads the Wikipedia lane store: lane-never-run",
    "/api/osm/search": "reads the OpenStreetMap lane store: lane-never-run",
    "/api/osm/view": "reads the OpenStreetMap lane store: lane-never-run",
    "/api/osm/countries/{code}/completeness": "reads the OpenStreetMap lane store: lane-never-run",
}

# Routes whose answer must name something only the seed holds, so a seed that stopped reaching its handler fails here by name.
# (path -> a substring of the first 4000 characters of the body).
_MUST_SHOW: dict[str, str] = {
    "/api/sources/{source_id}": _MARK,
    "/api/sources/groups/{group_id}": _MARK,
    "/api/law/documents/{document_id}": _MARK,
    "/api/articles/{article_id}/view": _MARK,
    "/api/entities/items/{qid}": _MARK,
    "/api/entities/places/card": _MARK,
    "/api/links/preview": _MARK,
    "/api/wiki/pages/{page_id}/versions": "900002",
    "/api/law/documents/{document_id}/versions": "an amendment",
}


class _Ids:
    """What the seed made, by name."""

    source: int
    source2: int
    group: int
    article: int
    doc: int
    rev_old: int
    rev_new: int
    page: int
    wrev_old: int
    wrev_new: int
    edition: str
    report: str
    custody_item: str
    folder: str
    parts_set: str
    volume_name: str


def _plant(data: Path, ids: _Ids) -> list[Path]:
    """Write, by hand, the artifacts a POST job would have left on disk; returns what lies OUTSIDE ``data`` so the teardown removes it."""
    import zipfile

    outside: list[Path] = []
    stamp = "20261027-000000"
    for rel, body in (
        (f"triage/oo-ai-check-{stamp}.json", {"schema": "probe", "checks": []}),
        (f"bench/oo-model-bench-{stamp}.json", {"schema": "probe", "rows": []}),
        (f"diagnostics/release-run/oo-release-run-{stamp}.json", {"schema": "probe", "run_id": "probe", "outcome": "probe", "board_rows": [], "phases": []}),
        ("keyword_fold_report.json", {"ok": True, "probe": _MARK}),
        ("search_reindex_report.json", {"ok": True, "probe": _MARK}),
    ):
        f = data / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(body), encoding="utf-8")
    archive = data / "diagnostics" / f"oo-all-diagnostics-{stamp}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("README.txt", "probe")
    ids.volume_name = f"oo-diagnostics-{stamp}.zip"
    ids.parts_set = "oo-keyword-parts-probe"
    parts = data / "diagnostics" / ids.parts_set
    parts.mkdir(parents=True, exist_ok=True)
    (parts / "part-1.json").write_text("{}", encoding="utf-8")
    (parts / "set.json").write_text(json.dumps({"files": [{"name": "part-1.json", "bytes": 2, "sha256": "0" * 64}]}), encoding="utf-8")
    # The region preview reads <osm base_dir>/<code>.osm.pbf; that folder is the manager's, wherever it was bound.
    from src.geo.osm_downloads import get_manager, osm_filename

    pbf = get_manager().base_dir / osm_filename("europe")
    if not pbf.exists():
        pbf.parent.mkdir(parents=True, exist_ok=True)
        pbf.write_bytes(b"\x00" * 16)
        outside.append(pbf)
    return outside


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """Seed one row of each kind into the suite's database and the data folder; remove them afterwards."""
    import hashlib
    import os

    from src.database import session as dbsession
    from src.database.models import (
        Article,
        ArticleAnalysis,
        CommodityPrice,
        LawDocument,
        LawRevision,
        Place,
        Source,
        SourceGroup,
        SourceMetadata,
        WikidataItem,
        WikiPage,
        WikiRevision,
    )

    data = tmp_path_factory.mktemp("get-effects-data")
    saved = {k: os.environ.get(k) for k in ("OO_DATA_DIR", "OO_NO_SCHEDULER")}
    ids = _Ids()
    made: list[tuple[type, object]] = []
    outside: list[Path] = []
    seeded_prices = False
    left = -1
    now = datetime.now(UTC)
    day = now - timedelta(days=1)
    try:
        os.environ["OO_DATA_DIR"] = str(data)
        os.environ["OO_NO_SCHEDULER"] = "1"
        dbsession.init_db()  # the suite's database may not have its tables yet when this file runs alone
        with dbsession.SessionLocal() as s:
            grp = SourceGroup(name=f"{_MARK}-group")
            src = Source(name=f"{_MARK}-a", domain=f"{_MARK}-a.test")
            src2 = Source(name=f"{_MARK}-b", domain=f"{_MARK}-b.test")
            s.add_all([grp, src, src2])
            s.flush()
            grp.sources.append(src)  # many-to-many through source_group_association
            s.add(SourceMetadata(source_id=src.id))
            art = Article(
                url=f"https://{_MARK}-a.test/1",
                canonical_url=f"https://{_MARK}-a.test/1",
                source_id=src.id,
                title=f"{_MARK} flood report",
                content="Heavy rain caused a flood in Paris. The river rose by two metres on Tuesday. " * 8,
                hash=hashlib.sha256(_MARK.encode()).hexdigest(),
                language="en",
                published_at=day,
                quarantined=False,
            )
            s.add(art)
            doc = LawDocument(jurisdiction="uk", title=f"{_MARK} Act", url=f"https://{_MARK}.test/act")
            page = WikiPage(wiki="en", title=f"{_MARK} Flood")
            s.add_all([doc, page, WikidataItem(qid=_QID, status="ok", labels_json=json.dumps({"en": _MARK})), Place(id=_PLACE, qid=_QID, kind="city", name=_MARK, lat=48.85, lon=2.35)])
            s.flush()
            r1 = LawRevision(document_id=doc.id, observed_at=day - timedelta(days=2), content_hash="a" * 64, size=100, delta_bytes=100)
            r2 = LawRevision(document_id=doc.id, observed_at=day, content_hash="b" * 64, size=140, delta_bytes=40)
            w1 = WikiRevision(page_id=page.id, revid=900001, timestamp=day - timedelta(days=2))
            w2 = WikiRevision(page_id=page.id, revid=900002, timestamp=day)
            s.add_all([r1, r2, w1, w2])
            s.add(ArticleAnalysis(article_id=art.id, kind="summary", result="A flood.", model=_MARK))
            # "ND" is the symbol the correlation route is asked about; seeded only if the suite's database holds none, so the teardown
            # never deletes a price this file did not make.
            if not s.query(CommodityPrice).filter(CommodityPrice.symbol == "ND").count():
                seeded_prices = True
                for i in range(30):
                    s.add(CommodityPrice(symbol="ND", observed_on=date.today() - timedelta(days=i), price=100.0 + i))
            s.commit()
            ids.source, ids.source2, ids.group = src.id, src2.id, grp.id
            ids.article, ids.doc, ids.page = art.id, doc.id, page.id
            ids.rev_old, ids.rev_new, ids.wrev_old, ids.wrev_new = r1.id, r2.id, w1.id, w2.id
            made = [
                (Article, art.id),
                (Source, src.id),
                (Source, src2.id),
                (SourceGroup, grp.id),
                (LawDocument, doc.id),
                (WikiPage, page.id),
                (Place, _PLACE),
                (WikidataItem, _QID),
            ]
        # Files the file-backed routes read, under the per-test data folder.
        from src.bulletin.store import editions_dir

        ed = editions_dir()
        ed.mkdir(parents=True, exist_ok=True)
        ids.edition = "20260731-OOS-weekly-abcd1234.json"
        (ed / ids.edition).write_text(
            json.dumps(
                {
                    "filename": ids.edition,
                    "state": "draft",
                    "period": {"cadence": "weekly", "start": "2026-07-25", "end": "2026-08-01", "days": 7},
                    "masthead": {"articles": 10, "top_sources": []},
                    "disclosures": {"quarantined_in_period": 0},
                    "sections": [],
                    "stories": {"stories": [], "caveat": "A LEXICAL grouping."},
                }
            ),
            encoding="utf-8",
        )
        from src.backup.import_reports import persist_import_report

        ids.report = persist_import_report("restore", {"kind": "restore", "ok": True}, run_id="probe").name
        folder = data / "scan-me"
        folder.mkdir()
        ids.folder = str(folder)
        ids.custody_item = f"{_MARK}-item"
        outside = _plant(data, ids)
        yield ids, data
    finally:
        for k, v in saved.items():  # first, so a failing cleanup below cannot leave the suite on this module's folder
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for f in outside:
            f.unlink(missing_ok=True)
        if made:
            with dbsession.SessionLocal() as s:
                s.query(ArticleAnalysis).filter(ArticleAnalysis.model == _MARK).delete()
                for model, pk in reversed(made):
                    row = s.get(model, pk)
                    if row is not None:
                        s.delete(row)
                if seeded_prices:
                    s.query(CommodityPrice).filter(CommodityPrice.symbol == "ND").delete()
                s.commit()
                left = sum(
                    s.query(model).filter(model.id == pk if hasattr(model, "id") else model.qid == pk).count() for model, pk in made
                )
    if made:
        assert left == 0, f"the seed left {left} row(s) in the suite's database"


def _urls(ids: _Ids) -> dict[str, str]:
    """Schema path -> a valid request for it, from the seeded ids. ``/api/...`` paths keep their placeholders as keys."""
    a, d, p = ids.article, ids.doc, ids.page
    return {
        "/api/articles/{article_id}/view": f"/api/articles/{a}/view",
        "/api/backup/import-reports/{filename}": f"/api/backup/import-reports/{ids.report}",
        "/api/backup/import-scan": f"/api/backup/import-scan?path={ids.folder}",
        "/api/bulletin/editions/{filename}": f"/api/bulletin/editions/{ids.edition}",
        "/api/bulletin/editions/{filename}/ai-plan": f"/api/bulletin/editions/{ids.edition}/ai-plan",
        "/api/bulletin/editions/{filename}/annexes": f"/api/bulletin/editions/{ids.edition}/annexes",
        "/api/bulletin/editions/{filename}/export-privacy": f"/api/bulletin/editions/{ids.edition}/export-privacy",
        "/api/bulletin/editions/{filename}/render": f"/api/bulletin/editions/{ids.edition}/render",
        "/api/bulletin/editions/{filename}/review": f"/api/bulletin/editions/{ids.edition}/review",
        "/api/commodities/{symbol}/correlation": "/api/commodities/ND/correlation?query=flood",
        "/api/diagnostics/ai-check/download": "/api/diagnostics/ai-check/download",
        "/api/diagnostics/all-job/download": "/api/diagnostics/all-job/download",
        "/api/diagnostics/all-job/volumes": "/api/diagnostics/all-job/volumes",
        "/api/diagnostics/all-job/volumes/{name}": f"/api/diagnostics/all-job/volumes/{ids.volume_name}",
        "/api/diagnostics/ir-eval": f"/api/diagnostics/ir-eval?gold_path={_GOLD_SET}",
        "/api/diagnostics/keywords/parts/latest": "/api/diagnostics/keywords/parts/latest",
        "/api/diagnostics/keywords/parts/{set_id}/{name}": f"/api/diagnostics/keywords/parts/{ids.parts_set}/part-1.json",
        "/api/diagnostics/model-bench/download": "/api/diagnostics/model-bench/download",
        "/api/diagnostics/release-run/download": "/api/diagnostics/release-run/download",
        "/api/entities/items/{qid}": f"/api/entities/items/{_QID}",
        "/api/entities/places/card": f"/api/entities/places/card?id={_PLACE}",
        "/api/geo/regions/{code}/preview": "/api/geo/regions/europe/preview",
        "/api/insights/keyword-fold-job/report": "/api/insights/keyword-fold-job/report",
        "/api/search/index-job/report": "/api/search/index-job/report",
        "/api/custody/{item_id}": f"/api/custody/{ids.custody_item}",
        "/api/custody/{item_id}/verify": f"/api/custody/{ids.custody_item}/verify",
        "/api/docs/{slug}": "/api/docs/user-manual",
        "/api/entities/dossier": "/api/entities/dossier?qid=Q90",
        "/api/entities/places/by-wiki": "/api/entities/places/by-wiki?external_id=enwiki:Paris",
        "/api/entities/places/search": "/api/entities/places/search?q=paris",
        "/api/events/astronomy": "/api/events/astronomy?year=2026",
        "/api/events/astronomy/lunar-series": "/api/events/astronomy/lunar-series?start=2026-01-01&end=2026-03-01",
        "/api/geo/downloads/size": "/api/geo/downloads/size?code=europe",
        "/api/governments/aggregate/{code}": "/api/governments/aggregate/WLD",
        "/api/governments/group-aggregate": "/api/governments/group-aggregate?group=G7&indicator=NY.GDP.MKTP.CD",
        "/api/governments/map": "/api/governments/map?indicator=NY.GDP.MKTP.CD",
        "/api/insights/corpus-facet-articles": f"/api/insights/corpus-facet-articles?facet=source&value={ids.source}",
        "/api/insights/graph": "/api/insights/graph?level=keyword&term=flood",
        "/api/insights/keyword-tags/keywords": "/api/insights/keyword-tags/keywords?axis=type&tag=person",
        "/api/insights/subjectivity": f"/api/insights/subjectivity?article_id={a}",
        "/api/insights/trend-articles": f"/api/insights/trend-articles?term=flood&start={date.today() - timedelta(days=7)}&end={date.today()}",
        "/api/integrity/profile": f"/api/integrity/profile?source={_MARK}-a",
        "/api/law/documents/{document_id}": f"/api/law/documents/{d}",
        "/api/law/documents/{document_id}/compare": f"/api/law/documents/{d}/compare?from={ids.rev_old}&to={ids.rev_new}",
        "/api/law/documents/{document_id}/provision-timeline": f"/api/law/documents/{d}/provision-timeline",
        "/api/law/documents/{document_id}/versions": f"/api/law/documents/{d}/versions",
        "/api/law/documents/{document_id}/view": f"/api/law/documents/{d}/view",
        "/api/library/history": "/api/library/history?metric=articles",
        "/api/links/articles-by-link": f"/api/links/articles-by-link?domain={_MARK}-a.test",
        "/api/links/preview": f"/api/links/preview?url=https://{_MARK}-a.test/1",
        "/api/llm/articles/{article_id}/analyses": f"/api/llm/articles/{a}/analyses",
        "/api/osm/countries/{code}/completeness": "/api/osm/countries/FR/completeness",
        "/api/osm/search": "/api/osm/search?q=paris",
        "/api/osm/view": "/api/osm/view?w=2.0&s=48.0&e=3.0&n=49.0",
        "/api/quarantine/source-furniture": f"/api/quarantine/source-furniture?source_id={ids.source}",
        "/api/search/omni": "/api/search/omni?q=flood",
        "/api/sources/groups/{group_id}": f"/api/sources/groups/{ids.group}",
        "/api/sources/{source_id}": f"/api/sources/{ids.source}",
        "/api/sources/{source_id}/citation-tally": f"/api/sources/{ids.source}/citation-tally",
        "/api/sources/{source_id}/metadata": f"/api/sources/{ids.source}/metadata",
        "/api/sources/{source_id}/observed-ips": f"/api/sources/{ids.source}/observed-ips",
        "/api/sources/{source_id}/provenance": f"/api/sources/{ids.source}/provenance",
        "/api/wiki/lane/sections": "/api/wiki/lane/sections?external_id=enwiki:Paris",
        "/api/wiki/pages/{page_id}/compare": f"/api/wiki/pages/{p}/compare?from=t{ids.wrev_old}&to=t{ids.wrev_new}",
        "/api/wiki/pages/{page_id}/revisions": f"/api/wiki/pages/{p}/revisions",
        "/api/wiki/pages/{page_id}/versions": f"/api/wiki/pages/{p}/versions",
        "/api/wiki/revisions/{rev_id}": f"/api/wiki/revisions/{ids.wrev_new}",
    }


class _Walk:
    def __init__(self, seen, statuses, bodies, watch_note, ids):
        self.ids = ids
        self.watch_note = watch_note
        self.seen = seen
        self.statuses = statuses
        self.bodies = bodies


def _schema_get_paths() -> set[str]:
    from src.api.main import app

    return {p for p, ops in app.openapi()["paths"].items() if "get" in ops}


@pytest.fixture(scope="module")
def walk(corpus):
    from src.api.main import app
    from src.database import session as dbsession
    from src.ingest import activate_kill_switch, clear_kill_switch

    ids, data = corpus
    schema = _schema_get_paths()
    dirs = [data]
    suite_dir = Path(str(dbsession.DATA_DIR))
    if suite_dir.resolve() != data.resolve():
        dirs.append(suite_dir)
    seen: dict = {}
    statuses: dict = {}
    bodies: dict = {}
    watchers: list[sqlite3.Connection] = []
    watch_note: str | None = "the main database is not a SQLite file"
    db_file = getattr(dbsession, "DB_FILE", None)
    if db_file:
        assert Path(db_file).exists(), f"the main database file {db_file} does not exist after init_db()"
        try:
            watchers.append(sqlite3.connect(f"file:{db_file}?mode=ro", uri=True))
            watchers[0].execute("PRAGMA data_version").fetchone()
            watch_note = None
        except sqlite3.DatabaseError as exc:  # an encrypted store is not readable without its key: the statement check still runs
            watchers.clear()
            watch_note = f"the main database could not be opened for watching ({exc}); the data_version check is skipped"
    with TestClient(app, raise_server_exceptions=False) as client:
        # Seed what only the app's own write path can make (a signed custody entry) with an ordinary request, outside any monitor.
        client.post(
            "/api/custody/log",
            json={"item_id": ids.custody_item, "item_hash": "c" * 64, "action": "ingest"},
            headers={"Host": "testserver"},
        )
        client.get("/api/no-such-route-warm-up", headers={"Host": "testserver"})
        activate_kill_switch()
        try:
            for path, url in _urls(ids).items():
                if path not in schema:
                    continue  # not mounted on this install (see _NEEDS_ANALYSIS_EXTRA)
                with _Monitor(dirs, tuple(watchers)) as mon:
                    r = client.get(url, headers={"Host": "testserver"})
                statuses[path], bodies[path], seen[path] = r.status_code, r.text[:4000], mon
        finally:
            clear_kill_switch()
            for w in watchers:
                w.close()
    return _Walk(seen, statuses, bodies, watch_note, ids)


def test_every_listed_route_reaches_its_body(walk):
    bad = {p: (s, walk.bodies[p]) for p, s in walk.statuses.items() if not 200 <= s < 300}
    assert not bad, f"{len(bad)} seeded request(s) did not reach a 2xx: {bad}"


def test_the_tables_name_real_routes_and_none_twice():
    """Identity against the empty walk's own 4xx set lives in ``test_get_routes_side_effects.py`` (it already holds that walk)."""
    schema = _schema_get_paths()
    driven = set(_urls(_placeholder_ids()))
    named = driven | set(_NOT_DRIVEN)
    absent = named - schema
    assert absent <= set(_NEEDS_ANALYSIS_EXTRA), f"these routes are named here but not in the schema: {sorted(absent - set(_NEEDS_ANALYSIS_EXTRA))}"
    if _analysis_extra_installed():
        assert not absent, f"the [analysis] extra is installed but these routes are not mounted: {sorted(absent)}"
    assert not driven & set(_NOT_DRIVEN), "a route is both driven and listed as not driven"
    assert set(_EMPTY_BRANCH) <= named and set(_MUST_SHOW) <= driven, "a route in _EMPTY_BRANCH or _MUST_SHOW is not one this file drives"
    assert not set(_EMPTY_BRANCH) & set(_MUST_SHOW), "a route cannot be both on its empty branch and required to show the seed"
    assert set(_ROUTES_WITH_DATA) <= driven, "_ROUTES_WITH_DATA names a route this file does not drive"
    assert all(r.strip() for r in _NOT_DRIVEN.values()) and all(r.strip() for r in _EMPTY_BRANCH.values())


def _placeholder_ids() -> _Ids:
    ids = _Ids()
    for name in ("source", "source2", "group", "article", "doc", "rev_old", "rev_new", "page", "wrev_old", "wrev_new"):
        setattr(ids, name, 1)
    for name in ("edition", "report", "custody_item", "folder", "parts_set", "volume_name"):
        setattr(ids, name, "x")
    return ids


def test_no_seeded_get_reaches_a_non_loopback_address_with_the_kill_switch_engaged(walk):
    bad = {
        p: m.lookups + [c for c in m.connects if not _is_loopback(c)]
        for p, m in walk.seen.items()
        if m.lookups or any(not _is_loopback(c) for c in m.connects)
    }
    assert not bad, f"these GETs tried to reach the network with the kill switch engaged (per-call refusal missing): {bad}"


def test_only_the_listed_routes_open_a_loopback_socket_with_data(walk):
    bad = sorted(p for p, m in walk.seen.items() if m.connects and not _LOOPBACK_ROUTES.match(p))
    assert not bad, f"these GETs opened a socket and are not in _LOOPBACK_ROUTES: {bad}"


def test_every_thread_and_file_with_data_is_accounted_for(walk):
    problems = _file_and_thread_problems(walk.seen, _merged_routes())
    assert not problems, (
        "these GETs, driven with data, wrote, changed or removed a file or started a thread that no table accounts for (route the "
        f"finding to the handler's lane; list it in _ROUTES_WITH_DATA with the reason): {problems}"
    )


def test_no_seeded_get_issues_a_write_statement_or_starts_an_unlisted_program(walk):
    writes = {p: sorted(set(m.sql_writes) - _SQL_WRITES_ALLOWED.get(p, frozenset())) for p, m in walk.seen.items()}
    writes = {p: w for p, w in writes.items() if w}
    programs = {p: sorted(set(m.processes) - set(_PROGRAMS_ALLOWED)) for p, m in walk.seen.items()}
    programs = {p: v for p, v in programs.items() if v}
    assert not writes, f"these GETs, driven with data, wrote to the database: {writes}"
    assert not programs, f"these GETs, driven with data, started a program that is not listed: {programs}"


def test_no_seeded_get_changes_the_database_without_a_write_statement(walk):
    """A write through a connection the engine does not see (a raw sqlite3 handle) moves ``PRAGMA data_version`` on the watcher."""
    if walk.watch_note:
        pytest.skip(walk.watch_note)
    bad = sorted(p for p, m in walk.seen.items() if m.db_changed and p not in _SQL_WRITES_ALLOWED)
    assert not bad, f"these GETs, driven with data, changed the main database: {bad}"


def test_the_walk_reads_the_seeded_rows_not_an_empty_answer(walk):
    """Liveness: a route that answers 200 with an empty body proves nothing about the code behind a row. These name what only the seed holds."""
    missing = {p: walk.bodies[p][:200] for p, needle in _MUST_SHOW.items() if p in walk.bodies and needle not in walk.bodies[p]}
    assert not missing, f"these routes answered without the seed's row (the request no longer reaches the data): {missing}"
    assert f'"article_ids":[{walk.ids.article}' in walk.bodies["/api/insights/corpus-facet-articles"].replace(" ", ""), walk.bodies["/api/insights/corpus-facet-articles"][:200]
    assert "language unknown" not in walk.bodies["/api/insights/subjectivity"], walk.bodies["/api/insights/subjectivity"][:200]

