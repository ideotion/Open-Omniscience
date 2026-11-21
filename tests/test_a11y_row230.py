"""Row 230: the a11y sweep's reader, Time map rank box and Explore header findings (V4, V5-V7, V8).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

docs/audit/a11y-sweep-2026-11-20 found, with axe in Chromium:
- V5/V6, the article reader: no ``<main>``, and the crumb, ``h1``, view tabs and read pane in no landmark;
- V7, the reader: the meta groups' ``h3`` straight after the ``h1``;
- V4, the Time map's ranked-table scroll box: nothing in it takes focus, so the keyboard cannot scroll it;
- V8, the Explore results table: an actions column header with no text.

The reader is rendered for real here; the two app modules are read as source, the way the other markup
guards in this suite read them. Mutation-checked by hand: ``<main>`` dropped, an ``h3`` restored on a meta
group, the rank box's ``tabindex`` removed, and one of the two Explore headers left empty each redden a test.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "static"


def _reader_html(tmp_path, monkeypatch) -> str:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, Base, Source
    from src.database.session import get_db

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    engine = create_engine(f"sqlite:///{tmp_path / 'rd.db'}", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(Source(name="Wire", domain="wire.test"))
        s.commit()
        s.add(Article(url="https://wire.test/a", canonical_url="https://wire.test/a", source_id=1, title="Article A",
                      content="Body A.\n\nSecond paragraph.", hash="ha", language="en", author="A. Writer",
                      published_at=datetime(2026, 11, 1, tzinfo=UTC), created_at=datetime.now(UTC)))
        s.commit()

    def _db():
        d = Sess()
        try:
            yield d
        finally:
            d.close()

    from src.api.main import app

    app.dependency_overrides[get_db] = _db
    try:
        return TestClient(app).get("/api/articles/1/view").text
    finally:
        app.dependency_overrides.clear()


def test_the_reader_puts_every_part_in_a_landmark(tmp_path, monkeypatch):
    body = _reader_html(tmp_path, monkeypatch)
    page = body.split("<body", 1)[1]
    assert page.count("<main>") == 1 and page.count("</main>") == 1
    header, rest = page.split("<main>", 1)
    main, after = rest.split("</main>", 1)
    assert "<header>" in header and "class=\"crumb\"" in header.split("<header>", 1)[1], "the crumb is the banner"
    assert "<h1>" in main and 'class="rtabs"' in main and 'id="rp-read"' in main and 'id="rp-links"' in main
    assert after.lstrip().startswith("<footer>"), "the footer is outside main, so it is the page's contentinfo"


def test_the_reader_headings_do_not_skip_a_level():
    src = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    groups = re.findall(r"<div class='mgrp[^']*'><(h\d)>", src)
    assert groups and set(groups) == {"h2"}, groups
    assert ".mgrp h3" not in src and ".mgrp h2 {{" in src and ".mgrp.deduced h2 {{" in src


def test_the_time_map_rank_box_takes_keyboard_focus():
    js = (STATIC / "app-map.js").read_text(encoding="utf-8")
    block = re.search(r'<details class="oomap-rank".*?</details>', js, re.S)
    assert block, "the ranked table is gone"
    box = re.search(r"<div ([^>]*overflow:auto[^>]*)>", block.group(0))
    assert box, "the scroll box is gone"
    attrs = box.group(1)
    assert 'tabindex="0"' in attrs and 'role="region"' in attrs and 'aria-label="${esc(t("Ranked table"))}"' in attrs


def test_the_explore_actions_column_has_a_name_in_every_language():
    js = (STATIC / "app-analysis.js").read_text(encoding="utf-8")
    heads = re.findall(r"<tr><th>Title</th><th>Source</th><th>Published</th><th>Lang</th>(<th>.*?</th>)</tr>", js)
    assert len(heads) == 2, heads
    assert all(h == "<th><span class='sr-only'>Actions</span></th>" for h in heads), heads
    assert re.search(r"\.sr-only\s*\{[^}]*clip:rect\(0,0,0,0\)", (STATIC / "app.css").read_text(encoding="utf-8"))
    for loc in sorted((STATIC / "locales").glob("*.json")):
        d = json.loads(loc.read_text(encoding="utf-8"))
        assert d.get("Actions") and d.get("Ranked table"), loc.name
