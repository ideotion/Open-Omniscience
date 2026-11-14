"""The Agenda's 'articles that mention a date' dialog (Lane M rows, R684; invariant 13b).

A picked day and a deduced event open GET /api/article-dates/by-date. Each mention can be
confirmed or rejected, which changes that date tag only, and Undo puts back the status it
had (POST /api/article-dates/{id}/reset when that was 'candidate'). The caveat that a
deduced date is never a confirmed event stays visible above the list.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Article, Base, Source
from src.timemap import datestore
from tests.js_source_helper import function_source, read_static

TODAY = date(2024, 6, 3)


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test"))
        s.commit()
        for i, text in enumerate(("The vote is set for 14 March 2025, officials said.", "Campaigns close before 14 March 2025.")):
            s.add(
                Article(
                    url=f"https://wire.test/{i}", canonical_url=f"https://wire.test/{i}", source_id=1, title=f"Story {i}",
                    hash=f"h{i}", language="en", content=text,
                    published_at=datetime(2024, 6, 1, tzinfo=UTC), created_at=datetime.now(UTC),
                )
            )
        s.commit()
        for art in s.query(Article).all():
            datestore.store_for_article(s, art, today=TODAY)
    return Sess


@pytest.fixture()
def client(tmp_path):
    from src.api.main import app
    from src.database.session import get_db

    Sess = _session(tmp_path)

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_by_date_rows_carry_the_tag_id_and_a_confirm_touches_only_that_tag(client):
    rows = client.get("/api/article-dates/by-date", params={"date": "2025-03-14"}).json()["articles"]
    assert len(rows) == 2 and all(isinstance(r["id"], int) for r in rows)
    first, second = rows
    assert client.post(f"/api/article-dates/{first['id']}/confirm").json()["status"] == "confirmed"
    after = {r["id"]: r["status"] for r in client.get("/api/article-dates/by-date", params={"date": "2025-03-14"}).json()["articles"]}
    assert after == {first["id"]: "confirmed", second["id"]: "candidate"}


def test_reset_puts_a_tag_back_to_candidate(client):
    tid = client.get("/api/article-dates/by-date", params={"date": "2025-03-14"}).json()["articles"][0]["id"]
    assert client.post(f"/api/article-dates/{tid}/reject").json()["status"] == "rejected"
    assert client.post(f"/api/article-dates/{tid}/reset").json()["status"] == "candidate"
    assert client.post("/api/article-dates/999999/reset").status_code == 404


def test_the_dialog_keeps_the_caveat_visible_and_offers_undo():
    js = read_static("app-agenda.js")
    render = function_source(js, "_agRenderMentions")
    assert "card-caveat" in render and "never confirmed as events" in render
    assert "it does not confirm that anything happens on it" in render
    row = function_source(js, "_agMentionRow")
    assert "/api/articles/" in row and "/view" in row, "a mention opens the local reader first (invariant #6)"
    assert "agMentionUndo" in row
    agrow = function_source(js, "agRow")
    assert "agOpenMentions" in agrow and "e.deduced" in agrow
    html = read_static("index.html")
    assert 'id="ag-mentions"' in html and 'id="ag-mentions-close"' in html


_NODE = r"""
const calls = [];
const store = {};
const el = (id) => (store[id] = store[id] || { innerHTML: "", textContent: "", open: id === "ag-mentions" });
global.window = {}; global.$ = el; global.esc = (s) => String(s); global.toast = () => {}; global.loadAgenda = () => {};
global.api = async (url, opts) => {
  calls.push(url);
  const st = url.endsWith("/confirm") ? "confirmed" : url.endsWith("/reject") ? "rejected" : "candidate";
  return { status: st };
};
SRC
_agMentions.rows = [{ id: 7, article_id: 1, title: "A", status: "candidate", precision: "day" }, { id: 8, article_id: 2, title: "B", status: "confirmed", precision: "month" }];
(async () => {
  await agMentionSet(7, "rejected");
  const afterReject = _agMentions.rows.map(r => r.status);
  const undoShown = el("ag-mentions-body").innerHTML.includes("agMentionUndo(7)");
  await agMentionUndo(7);
  await agMentionSet(8, "rejected");
  await agMentionUndo(8);
  const monthPill = el("ag-mentions-body").innerHTML.includes("names the month only, no day");
  // A reply from an earlier opening of the dialog changes nothing in the new one.
  const p = agMentionSet(7, "confirmed"); _agMentions.gen += 1; await p;
  const stale = _agMentions.rows[0].status;
  console.log(JSON.stringify({ calls, afterReject, undoShown, monthPill, stale, final: _agMentions.rows.map(r => r.status), changed: _agMentions.changed }));
})();
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_undo_restores_the_status_the_mention_had():
    js = read_static("app-agenda.js")
    names = ("_agStatusLabel", "_agMentionRow", "_agRenderMentions", "_agMentionPost", "agMentionSet", "agMentionUndo")
    asyncs = {"_agMentionPost", "agMentionSet", "agMentionUndo"}
    src = "\n".join(("async " if n in asyncs else "") + function_source(js, n) for n in names)
    consts = (
        "const AG_MENTIONS_LIMIT = 200;\n"
        "const _agMentions = { date: '2025-03-14', rows: [], prev: {}, changed: false, gen: 1, busy: new Set() };\n"
        "const _AG_STATUS_ROUTE = { confirmed: 'confirm', rejected: 'reject', candidate: 'reset' };\n"
    )
    out = subprocess.run(["node", "-e", _NODE.replace("SRC", consts + src)], capture_output=True, text=True, timeout=60, check=True)
    got = json.loads(out.stdout.strip().splitlines()[-1])
    assert got["calls"] == [
        "/api/article-dates/7/reject", "/api/article-dates/7/reset",
        "/api/article-dates/8/reject", "/api/article-dates/8/confirm",
        "/api/article-dates/7/confirm",
    ]
    assert got["monthPill"] is True, "a month-only mention says it names no day"
    assert got["stale"] == "candidate", "a reply from an earlier opening is dropped"
    assert got["afterReject"] == ["rejected", "confirmed"], "a reject changes that mention only"
    assert got["undoShown"] is True
    assert got["final"] == ["candidate", "confirmed"] and got["changed"] is True
