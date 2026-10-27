"""``POST /api/sources/import`` reaches the shipped catalog (R330, found by the read of PR 1586).

The route built ``Path(__file__).parent.parent.parent.parent / "configs" / "sources.yml"`` -- four hops from ``src/api/``, which lands one directory
ABOVE the repo root -- so it answered 500 (``FileNotFoundError``) on every install. It now resolves the root with ``src.paths.repo_root()``, the
way the rest of ``src`` does.

Install layouts the path holds for: a SOURCE CHECKOUT (``<root>/src/api/source_management.py`` with ``<root>/configs/sources.yml``) and a WHEEL
(``pyproject.toml`` ships ``configs`` as a top-level package beside ``src``, so both sit directly under site-packages and ``repo_root()`` is
site-packages). STATED LIMIT: this suite runs on the checkout layout only; the wheel layout is argued from the packaging config and covered by the
CI wheel smokes' install, not by a test here. The test runs the REAL import against the shipped catalog in a throwaway database, so a regression
shows up as the 500, not as a mocked path.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.api.main import app
from src.database.models import Base, Source
from src.database.session import get_db
from src.paths import repo_root

_H = {"Sec-Fetch-Site": "same-origin", "Referer": "http://127.0.0.1/", "Origin": "http://127.0.0.1"}


@pytest.fixture()
def db_and_client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 's.db'}", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine, future=True)

    def _db():
        db = Sess()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield Sess, c
    app.dependency_overrides.clear()


def test_the_catalog_the_route_reads_is_the_one_that_ships():
    assert (repo_root() / "configs" / "sources.yml").is_file(), (
        "the route's path must name a file that exists"
    )


def test_the_import_route_reaches_the_shipped_catalog(db_and_client):
    Sess, client = db_and_client
    r = client.post("/api/sources/import", headers=_H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] > 0, "an empty database imports the shipped catalog"
    with Sess() as s:
        assert s.scalar(select(func.count()).select_from(Source)) >= body["added"]
