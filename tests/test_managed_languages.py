"""Source-language gating: sources in languages the keyword engine cannot manage
(no stoplist / unsegmented) seed DISABLED by default and can be disabled in bulk —
kept, never deleted (maintainer 2026-06-18).

The managed-language logic is pure stdlib (runs in the core-only sandbox); the
seeder + endpoint tests use sqlalchemy/fastapi (CI).
"""

from __future__ import annotations

from src.analytics.managed import (
    MANAGED_LANGUAGES,
    is_managed,
    is_unmanaged,
    language_status,
    normalize_lang,
)


def test_managed_language_classification():
    assert is_managed("en") and is_managed("EN") and is_managed("en-US")
    assert is_managed("fr") and is_managed("ar") and is_managed("ru")
    assert not is_managed("tr") and not is_managed("zh") and not is_managed("")
    # el/bg gained hand-filtered Greek/Cyrillic grammar stoplists (2026-06-18) -> managed.
    assert is_managed("el") and is_managed("bg")
    # Unmanaged = a KNOWN language we cannot analyse; unknown/empty is NOT unmanaged
    # (we never disable what we cannot classify).
    assert is_unmanaged("tr") and is_unmanaged("uk") and is_unmanaged("zh")
    assert not is_unmanaged("en")
    assert not is_unmanaged("") and not is_unmanaged(None)
    assert language_status("en") == "functional"
    assert language_status("zh") == "unsegmented"
    assert language_status("tr") == "no_stoplist"
    assert language_status("") == "unknown"
    assert normalize_lang("pt-BR") == "pt" and normalize_lang("EN_us") == "en"


def test_engine_report_shares_the_managed_set():
    # The engine report must read the ONE source of truth, not a private copy.
    import src.analytics.engine_report as er

    assert er._FUNCTIONAL is MANAGED_LANGUAGES


def _mem_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Base

    eng = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def test_seeder_disables_new_unmanaged_language_sources():
    from src.catalog.csv_io import upsert_sources
    from src.database.models import Source

    s = _mem_session()
    rows = [
        {"name": "EN news", "domain": "en.test", "language": "en"},   # managed -> enabled
        {"name": "TR news", "domain": "tr.test", "language": "tr"},   # unmanaged -> disabled
        {"name": "ZH news", "domain": "zh.test", "language": "zh"},   # unsegmented -> disabled
        {"name": "No lang", "domain": "x.test"},                      # unknown -> stays enabled
        {"name": "TR forced", "domain": "tr2.test", "language": "tr", "enabled": True},  # explicit wins
    ]
    res = upsert_sources(s, rows)
    assert res["created"] == 5
    by_domain = {x.domain: x for x in s.query(Source).all()}
    assert by_domain["en.test"].enabled is True
    assert by_domain["tr.test"].enabled is False
    assert by_domain["zh.test"].enabled is False
    assert by_domain["x.test"].enabled is True
    assert by_domain["tr2.test"].enabled is True  # explicit enabled overrides the gate

    # Re-seeding must NOT flip the operator's choice on an existing source.
    s.query(Source).filter_by(domain="tr.test").update({"enabled": True})
    s.commit()
    upsert_sources(s, [{"name": "TR news", "domain": "tr.test", "language": "tr"}])
    assert s.query(Source).filter_by(domain="tr.test").first().enabled is True


def test_disable_unmanaged_languages_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.models import Source
    from src.database.session import get_db

    s = _mem_session()
    s.add_all([
        Source(name="EN", domain="en.test", language="en", enabled=True),
        Source(name="TR", domain="tr.test", language="tr", enabled=True),
        Source(name="UK", domain="uk.test", language="uk", enabled=True),
        Source(name="ZH", domain="zh.test", language="zh", enabled=True),
    ])
    s.commit()

    def _db():
        try:
            yield s
        finally:
            pass

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            r = c.get("/api/sources/unmanaged-languages").json()
            assert r["enabled_unmanaged"] == 3  # tr, uk, zh
            assert set(r["by_language"]) == {"tr", "uk", "zh"}
            assert "en" in r["managed_languages"]

            d = c.post("/api/sources/disable-unmanaged-languages").json()
            assert d["disabled"] == 3
            # Kept (not deleted), only disabled.
            assert s.query(Source).count() == 4
            assert s.query(Source).filter_by(domain="en.test").first().enabled is True
            assert s.query(Source).filter_by(domain="tr.test").first().enabled is False
            # Idempotent: nothing left to disable.
            assert c.post("/api/sources/disable-unmanaged-languages").json()["disabled"] == 0
    finally:
        app.dependency_overrides.clear()
