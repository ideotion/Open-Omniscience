"""
A feed's login is masked wherever the app shows the feed address, and kept wherever the address must come back (R637).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R628/R634 kept the login out of the feed KEY, but ``rss_url`` itself still carried it, unmasked, in every source answer the UI
renders (Steward 3's R628+R634 read, finding 1). R637, as ruled: every API answer that shows ``rss_url`` (and the health check's
probed URL) masks the userinfo as ``***@`` (``fetch_verdict.shown_url``, the fetcher's own ``failure_url``), and so do the request
logs; the CSV and YAML exports and the backups keep the URL as written, so they round-trip. A form saved with the masked URL keeps
the stored login (``fetch_verdict.url_to_store``), and a login never goes to another host, port or scheme.

Every answer is checked for the PASSWORD itself, anywhere in the body, not for one key. The credentials are fakes; nothing leaves
the process (the discovery and the health probe run on stand-ins).
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source

_DOMAIN = "news.example"
_NEEDLE = "hunter2"
_CRED = f"https://alice:{_NEEDLE}@{_DOMAIN}/rss"
_SHOWN = f"https://***@{_DOMAIN}/rss"
_PLAIN = f"https://{_DOMAIN}/rss"


def _needle_free(text: str) -> None:
    assert _NEEDLE not in text, text
    assert "alice" not in text, text


# --------------------------------------------------------------------------- #
# The store and the client
# --------------------------------------------------------------------------- #


def _engine(url: str):
    engine = create_engine(url, future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def sess_factory(tmp_path):
    engine = _engine(f"sqlite:///{tmp_path / 's.db'}")
    yield sessionmaker(bind=engine, future=True)
    engine.dispose()


@pytest.fixture()
def client(sess_factory):
    from src.api.main import app
    from src.database.session import get_db

    def _db():
        db = sess_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _stored(sess_factory, sid: int) -> str | None:
    with sess_factory() as s:
        return s.get(Source, sid).rss_url


@pytest.fixture()
def cred_source(sess_factory) -> int:
    """One source whose feed URL carries a login, tagged and in a group, as the operator stored it."""
    from src.database.models import SourceGroup

    with sess_factory() as s:
        src = Source(name="News", domain=_DOMAIN, rss_url=_CRED, tags="news")
        group = SourceGroup(name="watch")
        s.add_all([src, group])
        s.flush()
        group.sources.append(src)
        s.commit()
        return src.id


# --------------------------------------------------------------------------- #
# 1. Every answer that shows a source's feed address masks its login
# --------------------------------------------------------------------------- #


def test_the_source_list_answers_mask_the_login(client, cred_source):
    for path in ("/api/sources/", "/api/sources", "/api/sources?fields=id,name,rss_url", "/api/catalog/sources",
                 "/api/sources/search?query=news", f"/api/sources/{cred_source}"):
        r = client.get(path)
        assert r.status_code == 200, (path, r.text)
        _needle_free(r.text)
        assert _SHOWN in r.text, path  # the address is still shown, its login as ***@


def test_the_group_answer_masks_the_login(client, cred_source):
    groups = client.get("/api/sources/groups/").json()
    gid = next(g["id"] for g in groups if g["name"] == "watch")
    r = client.get(f"/api/sources/groups/{gid}")
    assert r.status_code == 200, r.text
    _needle_free(r.text)
    assert r.json()["sources"][0]["rss_url"] == _SHOWN


def test_the_rss_discovery_answer_masks_a_listed_sources_stored_url(client, cred_source, monkeypatch):
    from src.services.duckduckgo import DuckDuckGoSearch

    handed: list = []

    def _found(source_list, timeout=10):  # a listed source that has a feed comes back as it went in, url and rss_url both
        handed.extend(source_list)
        return [dict(s, rss_urls=[s["rss_url"]]) for s in source_list]

    monkeypatch.setattr(DuckDuckGoSearch, "find_missing_rss_feeds", staticmethod(_found))
    r = client.post("/api/sources/discover/rss", json=[cred_source])
    assert r.status_code == 200, r.text
    assert handed and handed[0]["url"] == _CRED  # the discovery itself is handed the stored URL
    _needle_free(r.text)
    assert r.json()["results"][0]["rss_url"] == _SHOWN


def test_the_topic_discovery_answer_masks_each_found_url(client, monkeypatch):
    import src.safety.settings as safety
    from src.database.source_manager import SourceManager

    monkeypatch.setattr(safety, "load_settings", lambda: SimpleNamespace(discovery_external_enabled=True))
    monkeypatch.setattr(SourceManager, "discover_sources_by_topic",
                        lambda self, topic, max_sources, region="wt-wt": [{"domain": _DOMAIN, "url": _CRED, "rss_urls": [_CRED, _PLAIN]}])
    r = client.post("/api/sources/discover/topic?topic=news")
    assert r.status_code == 200, r.text
    _needle_free(r.text)
    assert r.json()["sources"][0]["rss_urls"] == [_SHOWN, _PLAIN]


def test_the_discovered_sources_answer_masks_the_login_it_stored(client, sess_factory):
    r = client.post("/api/sources/discover/add", json=[{"domain": _DOMAIN, "name": "News", "rss_url": _CRED}])
    assert r.status_code == 200, r.text
    _needle_free(r.text)
    assert _stored(sess_factory, r.json()["sources"][0]["id"]) == _CRED  # a login typed into a new source is stored as typed


def test_the_health_check_probes_the_stored_url_and_shows_it_masked():
    from src.monitoring.health import check_source

    asked: list[str] = []

    class _Fetcher:
        def fetch(self, url, require_html=True):
            asked.append(url)

    out = check_source(SimpleNamespace(id=1, name="News", domain=_DOMAIN, rss_url=_CRED), fetcher=_Fetcher()).to_dict()
    assert asked == [_CRED]  # the fetch keeps the login
    _needle_free(repr(out))
    assert out["url"] == _SHOWN


def test_shown_url_leaves_no_feed_and_a_plain_url_as_they_are():
    from src.ingest.fetch_verdict import shown_url

    assert shown_url(None) is None and shown_url("") == ""
    assert shown_url(_PLAIN) == _PLAIN
    assert shown_url(_CRED) == _SHOWN
    assert shown_url(f"https://alice:{_NEEDLE}@{_DOMAIN}:8443/rss?x=1") == f"https://***@{_DOMAIN}:8443/rss?x=1"


# --------------------------------------------------------------------------- #
# 2. The request logs mask it too
# --------------------------------------------------------------------------- #


def test_the_create_and_update_request_logs_mask_the_login(client, sess_factory, caplog):
    caplog.set_level(logging.INFO)
    r = client.post("/api/sources/", json={"name": "News", "domain": _DOMAIN, "rss_url": _CRED})
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert client.put(f"/api/sources/{sid}", json={"rss_url": f"https://alice:{_NEEDLE}@{_DOMAIN}/feed"}).status_code == 200
    said = [rec.getMessage() for rec in caplog.records if "source request" in rec.getMessage()]
    assert len(said) == 2, said
    for line in said:
        _needle_free(line)
        assert "***@" in line
    assert _stored(sess_factory, sid) == f"https://alice:{_NEEDLE}@{_DOMAIN}/feed"


# --------------------------------------------------------------------------- #
# 3. Saving the form with the masked URL
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("sent", "kept"),
    [
        (_SHOWN, _CRED),                                                          # (a) sent back unchanged: the stored login
        ("https://***@other.example/rss", "https://other.example/rss"),           # (b) another host: the login does not follow
        (_PLAIN, _PLAIN),                                                         # (c) the login removed: stored without one
        (f"https://bob:sw0rdfish@{_DOMAIN}/rss", f"https://bob:sw0rdfish@{_DOMAIN}/rss"),  # a new login typed: as typed
        (f"https://***@{_DOMAIN}/world", f"https://alice:{_NEEDLE}@{_DOMAIN}/world"),    # the same host, another path: kept
        (f"https://***@{_DOMAIN}:8443/rss", f"https://{_DOMAIN}:8443/rss"),       # another port: not carried
        (f"http://***@{_DOMAIN}/rss", f"http://{_DOMAIN}/rss"),                   # another scheme (to cleartext): not carried
        (f"https://***@{_DOMAIN.upper()}:443/rss", f"https://alice:{_NEEDLE}@{_DOMAIN.upper()}:443/rss"),  # one host key
    ],
    ids=["a-unchanged", "b-other-host", "c-login-removed", "new-login-typed", "same-host-other-path", "other-port",
         "other-scheme", "same-host-key"],
)
def test_saving_the_source_form_keeps_or_drops_the_stored_login(client, sess_factory, cred_source, sent, kept):
    r = client.put(f"/api/sources/{cred_source}", json={"name": "News", "rss_url": sent})
    assert r.status_code == 200, r.text
    assert _stored(sess_factory, cred_source) == kept
    _needle_free(r.text)


def test_saving_the_form_unchanged_round_trips_what_the_form_was_shown(client, sess_factory, cred_source):
    shown = client.get(f"/api/sources/{cred_source}").json()
    body = {k: shown[k] for k in ("name", "domain", "rss_url", "rate_limit_ms", "enabled", "priority")}
    assert client.put(f"/api/sources/{cred_source}", json=body).status_code == 200
    assert _stored(sess_factory, cred_source) == _CRED


def test_an_update_of_another_field_leaves_the_stored_login(client, sess_factory, cred_source):
    assert client.put(f"/api/sources/{cred_source}", json={"priority": 1}).status_code == 200
    assert _stored(sess_factory, cred_source) == _CRED


def test_a_masked_url_never_stores_the_mask_as_a_login(client, sess_factory):
    r = client.post("/api/sources/", json={"name": "Other", "domain": "other.example", "rss_url": "https://***@other.example/rss"})
    assert r.status_code == 200, r.text
    assert _stored(sess_factory, r.json()["id"]) == "https://other.example/rss"
    r = client.post("/api/sources/discover/add", json=[{"domain": "third.example", "rss_url": "https://***@third.example/rss"}])
    assert r.status_code == 200, r.text
    assert _stored(sess_factory, r.json()["sources"][0]["id"]) == "https://third.example/rss"


@pytest.mark.parametrize(
    ("sent", "stored", "out"),
    [
        (None, _CRED, None),
        ("", _CRED, ""),
        (7, _CRED, 7),
        (_SHOWN, None, _PLAIN),
        (_SHOWN, _PLAIN, _PLAIN),            # nothing stored to keep: the mask is dropped
        (_PLAIN, _PLAIN, _PLAIN),
        ("https://***@[::1/rss", _CRED, "https://[::1/rss"),  # a host that cannot be read carries nothing
        ("https://a%40b:pw@news.example/rss", _CRED, "https://a%40b:pw@news.example/rss"),
        # the form shows a space as %20: sent back unchanged, it is the stored URL itself, its space and its login included
        (f"https://***@{_DOMAIN}/a%20b", f"https://alice:{_NEEDLE}@{_DOMAIN}/a b", f"https://alice:{_NEEDLE}@{_DOMAIN}/a b"),
        (f"https://{_DOMAIN}/a%20b", f"https://{_DOMAIN}/a b", f"https://{_DOMAIN}/a b"),
        # the independent read of R637, stated: only the mask exactly as shown is the stored login; any other userinfo is what
        # the person typed and is stored as typed; a host spelled otherwise than the fetcher keys it (a trailing dot) drops it
        (f"https://%2A%2A%2A@{_DOMAIN}/rss", _CRED, f"https://%2A%2A%2A@{_DOMAIN}/rss"),
        (f"https://**\t*@{_DOMAIN}/rss", _CRED, f"https://**\t*@{_DOMAIN}/rss"),
        (f"https://***:x@{_DOMAIN}/rss", _CRED, f"https://***:x@{_DOMAIN}/rss"),
        (f"https://***@{_DOMAIN}./rss", _CRED, f"https://{_DOMAIN}./rss"),
    ],
)
def test_url_to_store(sent, stored, out):
    from src.ingest.fetch_verdict import url_to_store

    assert url_to_store(sent, stored) == out


@pytest.mark.parametrize("url", [f"alice:{_NEEDLE}@{_DOMAIN}/rss", f"https:alice:{_NEEDLE}@{_DOMAIN}/rss"],
                         ids=["no-scheme", "no-authority"])
def test_shown_url_leaves_a_form_with_no_authority_as_written_and_the_fetcher_refuses_it(tmp_path, url):
    """Stated (the independent read of R637): ``shown_url`` masks a userinfo only after a ``//`` authority, so these two forms are
    shown as written; neither is fetched: the fetcher refuses a URL with no http(s) scheme or no host before any request."""
    from src.ingest import EthicalFetcher, FetchFailed
    from src.ingest.fetch_verdict import shown_url

    assert shown_url(url) == url
    with pytest.raises(FetchFailed, match="unsupported or malformed URL"):
        EthicalFetcher(robots_cache_path=tmp_path / "robots.json").fetch(url)


# --------------------------------------------------------------------------- #
# 4. The exports and the backups keep the URL as written, so they round-trip
# --------------------------------------------------------------------------- #


def test_the_csv_export_keeps_the_login_and_imports_back(sess_factory, tmp_path, cred_source):
    from src.api.source_io import export_csv
    from src.catalog.csv_io import parse_sources_csv, upsert_sources

    async def _body(response):
        return "".join([chunk if isinstance(chunk, str) else chunk.decode() async for chunk in response.body_iterator])

    with sess_factory() as s:
        body = asyncio.run(_body(export_csv(s)))
    assert _CRED in body
    rows, errors = parse_sources_csv(body)
    assert not errors
    other = sessionmaker(bind=_engine(f"sqlite:///{tmp_path / 'b.db'}"), future=True)
    with other() as s:
        upsert_sources(s, rows)
        assert [r.rss_url for r in s.query(Source)] == [_CRED]


def test_the_yaml_exports_keep_the_login_and_import_back(client, sess_factory, tmp_path, cred_source):
    from src.database.source_manager import SourceManager

    assert _CRED in client.get("/api/sources/export").text  # the YAML-shaped export answer (JSON is YAML): as written
    path = tmp_path / "out.yml"
    with sess_factory() as s:
        SourceManager(s).export_sources_to_yaml(str(path))
    assert _CRED in path.read_text(encoding="utf-8")
    other = sessionmaker(bind=_engine(f"sqlite:///{tmp_path / 'b.db'}"), future=True)
    with other() as s:
        SourceManager(s).import_sources_from_yaml(str(path))
        assert [r.rss_url for r in s.query(Source)] == [_CRED]


def test_a_backup_restore_keeps_the_login(tmp_path):
    from src.backup import merge

    staged, working = tmp_path / "staged.db", tmp_path / "working.db"
    for path in (staged, working):
        _engine(f"sqlite:///{path}").dispose()
    engine = _engine(f"sqlite:///{staged}")
    with sessionmaker(bind=engine, future=True)() as s:
        src = Source(name="News", domain=_DOMAIN, rss_url=_CRED)
        s.add(src)
        s.flush()
        page = f"https://{_DOMAIN}/a"
        s.add(Article(title="a", url=page, canonical_url=page, source_id=src.id, content="an article", hash="a".ljust(64, "0")))
        s.commit()
    engine.dispose()
    merge.merge_corpus(staged, working, {"artifact_kind": "oo-backup-2", "origin_fingerprint": "test", "app_version": "0.5.0",
                                         "alembic_rev": "head", "manifest": None})
    con = sqlite3.connect(working)
    try:
        assert [r[0] for r in con.execute("SELECT rss_url FROM sources")] == [_CRED]
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# 5. The UI says so, visibly, beside the export button and on the backup surface
# --------------------------------------------------------------------------- #


def test_the_export_and_backup_caveats_are_visible_and_translated():
    import json
    import re
    from pathlib import Path

    static = Path(__file__).resolve().parent.parent / "src" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    shown = {}
    for cid in ("src-export-logins", "backup-feed-logins", "ux-backup-feed-logins"):
        m = re.search(rf'<p class="card-caveat" id="{cid}"[^>]*title="([^"]+)">([^<]+)</p>', html)
        assert m, cid  # a visible paragraph, never [hidden], never behind a toggle
        shown[cid] = (m.group(1), m.group(2))
        assert "hidden" not in m.group(0)
    assert html.index('id="src-export-logins"') > html.index("/api/catalog/export.csv")  # beside the export button
    # R637 amended 2026-11-09 06:13Z: a backup made without encryption is a plain file like the export, so the backup
    # line says so and asks for it to be kept private; the hover both lines share says it for both.
    backup_title, backup_line = shown["backup-feed-logins"]
    assert "A backup made without encryption is a plain file, so keep it private." in backup_line
    assert "so a restore can still fetch that feed" in backup_line
    for title, _line in shown.values():
        assert title == backup_title
        assert "The export, like a backup made without encryption, is a plain file, so keep it private." in title
    assert shown["src-export-logins"][1].endswith("so the file imports back unchanged. Keep it private.")
    # the independent read of R637: "Back up first" and "Download a backup first" open the export dialog without passing the
    # panel, so the same line, the same keys, is inside the dialog where the backup is made
    assert shown["ux-backup-feed-logins"] == shown["backup-feed-logins"]
    dialog = html[html.index('<dialog id="ux-export"') : html.index("</dialog>", html.index('<dialog id="ux-export"'))]
    assert 'id="ux-backup-feed-logins"' in dialog and dialog.index('id="ux-backup-feed-logins"') < dialog.index('id="ux-run"')
    for opener in ('id="nl-backup-first-btn" data-on-click="downloadBackupFirst(this)"', 'data-on-click="openUnifiedExport()">Download a backup first'):
        assert opener in html, opener  # the two ways in that pass no panel
    for code in ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"):
        table = json.loads((static / "locales" / f"{code}.json").read_text(encoding="utf-8"))
        for title, line in shown.values():
            assert table.get(title) and table.get(line), code
