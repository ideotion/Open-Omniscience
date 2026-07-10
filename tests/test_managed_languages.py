"""Source-language gating: sources in languages the keyword engine cannot manage
(no stoplist / unsegmented) seed DISABLED by default and can be disabled in bulk —
kept, never deleted (maintainer 2026-06-18).

The managed-language logic is pure stdlib (runs in the core-only sandbox); the
seeder + endpoint tests use sqlalchemy/fastapi (CI).
"""

from __future__ import annotations

from src.analytics.managed import (
    is_managed,
    is_unmanaged,
    language_status,
    normalize_lang,
)
from src.analytics.segmentation import segmenter_available

# zh/ja/th are functional IFF the optional [segmentation] extra is installed; a core
# install reports them 'unsegmented'. The tests assert BOTH environments honestly.
_ZH_SEG = segmenter_available("zh")
_TH_SEG = segmenter_available("th")


def test_managed_language_classification():
    assert is_managed("en") and is_managed("EN") and is_managed("en-US")
    assert is_managed("fr") and is_managed("ar") and is_managed("ru")
    assert not is_managed("vi") and not is_managed("")
    # el/bg gained hand-filtered Greek/Cyrillic grammar stoplists (2026-06-18) -> managed.
    assert is_managed("el") and is_managed("bg")
    # 2026-06-22 remainder batch promoted tr/uk/fa/ur/ro/cs/sk/ca/sw/az/et/fi/bs/hr.
    assert is_managed("tr") and is_managed("uk") and is_managed("fa") and is_managed("ur")
    # 2026-07-10 segmenter wave: ko/mr are space-segmented + now carry stoplists.
    assert is_managed("ko") and is_managed("mr")
    # Unmanaged = a KNOWN language we cannot analyse; unknown/empty is NOT unmanaged
    # (we never disable what we cannot classify). vi is syllable-segmented -> always
    # unmanaged. zh/th are unsegmented UNLESS the [segmentation] extra is installed.
    assert is_unmanaged("vi")
    assert not is_unmanaged("en")
    assert not is_unmanaged("") and not is_unmanaged(None)
    assert language_status("en") == "functional"
    assert language_status("vi") == "no_stoplist"   # syllable-segmented, words fragment
    assert language_status("") == "unknown"
    # zh/th: segmenter-aware, honest in both environments.
    assert language_status("zh") == ("functional" if _ZH_SEG else "unsegmented")
    assert language_status("th") == ("functional" if _TH_SEG else "unsegmented")
    assert is_managed("zh") is _ZH_SEG and is_unmanaged("zh") is (not _ZH_SEG)
    assert is_managed("th") is _TH_SEG and is_unmanaged("th") is (not _TH_SEG)
    assert normalize_lang("pt-BR") == "pt" and normalize_lang("EN_us") == "en"


def test_engine_report_shares_the_managed_set():
    # The engine report must read the ONE source of truth (segmenter-aware), not a copy.
    import src.analytics.engine_report as er

    assert er._language_status is language_status


def _mem_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from src.database.models import Base

    # Share the ONE in-memory connection across threads: the FastAPI TestClient runs
    # the app in a separate (portal) thread, and the default SingletonThreadPool would
    # hand that thread a fresh, EMPTY in-memory DB ("no such table: sources"). StaticPool
    # + check_same_thread=False keep a single shared connection (matches the pattern in
    # tests/test_convergence.py's session fixture).
    eng = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng, future=True)()


def test_seeder_disables_new_unmanaged_language_sources():
    from src.catalog.csv_io import upsert_sources
    from src.database.models import Source

    s = _mem_session()
    rows = [
        {"name": "EN news", "domain": "en.test", "language": "en"},   # managed -> enabled
        {"name": "VI news", "domain": "vi.test", "language": "vi"},   # no_stoplist -> disabled
        {"name": "ZH news", "domain": "zh.test", "language": "zh"},   # unsegmented -> disabled unless segmenter
        {"name": "No lang", "domain": "x.test"},                      # unknown -> stays enabled
        {"name": "VI forced", "domain": "vi2.test", "language": "vi", "enabled": True},  # explicit wins
    ]
    res = upsert_sources(s, rows)
    assert res["created"] == 5
    by_domain = {x.domain: x for x in s.query(Source).all()}
    assert by_domain["en.test"].enabled is True
    assert by_domain["vi.test"].enabled is False  # vi is always unmanaged
    # zh seeds disabled only when it is unmanaged (no [segmentation] extra).
    assert by_domain["zh.test"].enabled is (not is_unmanaged("zh"))
    assert by_domain["x.test"].enabled is True
    assert by_domain["vi2.test"].enabled is True  # explicit enabled overrides the gate

    # Re-seeding must NOT flip the operator's choice on an existing source.
    s.query(Source).filter_by(domain="vi.test").update({"enabled": True})
    s.commit()
    upsert_sources(s, [{"name": "VI news", "domain": "vi.test", "language": "vi"}])
    assert s.query(Source).filter_by(domain="vi.test").first().enabled is True


def test_disable_unmanaged_languages_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.database.models import Source
    from src.database.session import get_db

    s = _mem_session()
    s.add_all([
        Source(name="EN", domain="en.test", language="en", enabled=True),
        Source(name="VI", domain="vi.test", language="vi", enabled=True),
        Source(name="TH", domain="th.test", language="th", enabled=True),
        Source(name="ZH", domain="zh.test", language="zh", enabled=True),
    ])
    s.commit()

    def _db():
        try:
            yield s
        finally:
            pass

    # th/zh are unmanaged only without the [segmentation] extra; vi is always unmanaged.
    expected = {lang for lang in ("vi", "th", "zh") if is_unmanaged(lang)}

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app) as c:
            r = c.get("/api/sources/unmanaged-languages").json()
            assert r["enabled_unmanaged"] == len(expected)
            assert set(r["by_language"]) == expected
            assert "en" in r["managed_languages"]

            d = c.post("/api/sources/disable-unmanaged-languages").json()
            assert d["disabled"] == len(expected)
            # Kept (not deleted), only disabled.
            assert s.query(Source).count() == 4
            assert s.query(Source).filter_by(domain="en.test").first().enabled is True
            assert s.query(Source).filter_by(domain="vi.test").first().enabled is False  # vi always unmanaged
            # Idempotent: nothing left to disable.
            assert c.post("/api/sources/disable-unmanaged-languages").json()["disabled"] == 0
    finally:
        app.dependency_overrides.clear()
