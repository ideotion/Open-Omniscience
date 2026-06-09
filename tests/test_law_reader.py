"""World-law reader page: offline copy + amendment history with coloured diffs.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, LawRevision


def test_law_document_reader_renders_text_and_diff(tmp_path):
    from src.database.session import get_db

    engine = create_engine(
        f"sqlite:///{tmp_path / 'law.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)
    with Sess() as s:
        s.add(
            LawDocument(
                jurisdiction="uk",
                title="Data Protection Act",
                url="https://legislation.gov.uk/dpa",
                official_url="https://legislation.gov.uk/dpa",
                category="legislation",
                consolidated=True,
                baseline_text="Section 1.\nEveryone has rights.",
                last_status="ok",
                last_checked_at=datetime.now(UTC),
            )
        )
        s.commit()
        s.add(
            LawRevision(
                document_id=1,
                content_hash="abc",
                observed_at=datetime(2026, 1, 2, tzinfo=UTC),
                delta_bytes=42,
                diff="-old clause removed\n+new clause added",
                flagged=True,
                flag_reasons="large change",
            )
        )
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
        with TestClient(app) as c:
            r = c.get("/api/law/documents/1/view")
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/html")
            body = r.text
            assert "Data Protection Act" in body
            assert "Everyone has rights." in body  # captured baseline text
            assert "UK" in body and "consolidation" in body  # metadata
            assert "Amendment history" in body
            assert "new clause added" in body and "old clause removed" in body  # the diff
            assert "dl add" in body and "dl del" in body  # colourised
            assert "legislation.gov.uk/dpa" in body  # official link
            assert "not legal advice" in body  # honest framing
            assert "live request from your machine" in body  # external confirm
            assert c.get("/api/law/documents/999/view").status_code == 404
    finally:
        app.dependency_overrides.clear()
