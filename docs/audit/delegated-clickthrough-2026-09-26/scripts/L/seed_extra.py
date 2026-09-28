"""Supplementary seed for the row-L walk (scratch only, never committed).

Written into the SAME encrypted data dir after ui_clickthrough_seed.py, with the server
STOPPED (single-writer). Everything goes through the app's own parse/store paths:

* World Bank figures: a World Bank API v2-shaped JSON payload -> src.stats.sdmx.parse_worldbank
  -> src.stats.store.store_figures (the exact pair the 'Load standard country data' job uses),
  for 3 indicators x 44 countries + 6 WB aggregates x 2019-2023. VALUES ARE SYNTHETIC
  (plausible magnitudes, not the Bank's numbers) -- a renderer check, not real data.
* USGS MCS supply rows: a salient-statistics long CSV -> src.stats.usgs.parse_mcs_csv ->
  store_figures (area codes as USGS publishes them: CN, US, AU, WLD).
* Index points: CommodityPrice rows for four catalogued index symbols (synthetic).
* Law + Wikipedia-lane change rows: copied from
  docs/audit/living-sources-clickthrough-2026-09-25/seed.py (law docs fr + uk with a flagged
  revision; the wiki lane's followed pages en/fr).
"""
import json
import random
from datetime import UTC, date, datetime, timedelta

from src.database.models import CommodityPrice, LawDocument, LawRevision
from src.database.session import SessionLocal, init_db
from src.stats.sdmx import parse_worldbank
from src.stats.store import store_figures
from src.stats.usgs import parse_mcs_csv

init_db()
rng = random.Random(20260926)
now = datetime.now(UTC)
naive = now.replace(tzinfo=None)
extracted = now.strftime("%Y-%m-%dT%H:%M:%SZ")

# (iso2, iso3, name, gdp_bn, pop_m, lifeexp)
COUNTRIES = [
    ("AF", "AFG", "Afghanistan", 14, 41, 62), ("AL", "ALB", "Albania", 23, 2.8, 76),
    ("DZ", "DZA", "Algeria", 239, 45, 76), ("AR", "ARG", "Argentina", 640, 46, 76),
    ("AU", "AUS", "Australia", 1700, 26, 83), ("AT", "AUT", "Austria", 516, 9.1, 81),
    ("BE", "BEL", "Belgium", 632, 11.7, 82), ("BR", "BRA", "Brazil", 2170, 216, 73),
    ("CA", "CAN", "Canada", 2140, 40, 82), ("CL", "CHL", "Chile", 335, 19.6, 79),
    ("CN", "CHN", "China", 17800, 1410, 78), ("CO", "COL", "Colombia", 363, 52, 73),
    ("CZ", "CZE", "Czechia", 330, 10.9, 79), ("DK", "DNK", "Denmark", 404, 5.9, 81),
    ("EG", "EGY", "Egypt, Arab Rep.", 396, 112, 70), ("FI", "FIN", "Finland", 300, 5.6, 81),
    ("FR", "FRA", "France", 3030, 68, 82), ("DE", "DEU", "Germany", 4460, 84, 81),
    ("GR", "GRC", "Greece", 243, 10.4, 80), ("HU", "HUN", "Hungary", 212, 9.6, 76),
    ("IN", "IND", "India", 3550, 1430, 67), ("ID", "IDN", "Indonesia", 1370, 277, 68),
    ("IE", "IRL", "Ireland", 545, 5.3, 82), ("IT", "ITA", "Italy", 2250, 59, 83),
    ("JP", "JPN", "Japan", 4210, 124, 84), ("KE", "KEN", "Kenya", 108, 55, 62),
    ("MX", "MEX", "Mexico", 1790, 128, 70), ("NL", "NLD", "Netherlands", 1120, 17.9, 82),
    ("NG", "NGA", "Nigeria", 363, 224, 53), ("NO", "NOR", "Norway", 485, 5.5, 83),
    ("PL", "POL", "Poland", 811, 36.7, 77), ("PT", "PRT", "Portugal", 287, 10.5, 81),
    ("RO", "ROU", "Romania", 351, 19, 75), ("SA", "SAU", "Saudi Arabia", 1070, 37, 77),
    ("ZA", "ZAF", "South Africa", 377, 60, 62), ("KR", "KOR", "Korea, Rep.", 1710, 51.7, 83),
    ("ES", "ESP", "Spain", 1580, 48, 83), ("SE", "SWE", "Sweden", 593, 10.5, 83),
    ("CH", "CHE", "Switzerland", 885, 8.8, 84), ("TR", "TUR", "Turkiye", 1110, 85, 76),
    ("UA", "UKR", "Ukraine", 179, 37, 69), ("GB", "GBR", "United Kingdom", 3340, 68, 81),
    ("US", "USA", "United States", 27400, 335, 77), ("XK", "XKX", "Kosovo", 10, 1.8, 76),
]
# WB aggregates as the API publishes them (country.id is WB's own 2-char code).
AGGREGATES = [
    ("1W", "WLD", "World", 105000, 8000, 73), ("XD", "HIC", "High income", 64000, 1240, 80),
    ("EU", "EUU", "European Union", 18300, 448, 81), ("Z4", "EAS", "East Asia & Pacific", 33000, 2380, 76),
    ("XM", "LIC", "Low income", 580, 740, 63), ("ZG", "SSF", "Sub-Saharan Africa", 2100, 1210, 61),
]


def wb_payload(series_id, label, pick):
    rows = []
    for iso2, iso3, name, gdp, pop, le in COUNTRIES + AGGREGATES:
        base = pick(gdp, pop, le)
        for year in range(2019, 2024):
            val = None if (iso3 == "AFG" and series_id == "NY.GDP.MKTP.CD" and year >= 2022) else \
                round(base * (0.94 + 0.03 * (year - 2019)) * (1 + rng.uniform(-0.01, 0.01)), 3)
            rows.append({
                "indicator": {"id": series_id, "value": label},
                "country": {"id": iso2, "value": name},
                "countryiso3code": iso3, "date": str(year), "value": val,
                "unit": "", "obs_status": "", "decimal": 0,
            })
    return [{"page": 1, "pages": 1, "per_page": 20000, "total": len(rows)}, rows]


db = SessionLocal()
try:
    tallies = {}
    for sid, label, pick in [
        ("NY.GDP.MKTP.CD", "GDP (current US$)", lambda g, p, e: g * 1e9),
        ("SP.POP.TOTL", "Population, total", lambda g, p, e: p * 1e6),
        ("SP.DYN.LE00.IN", "Life expectancy at birth, total (years)", lambda g, p, e: e),
    ]:
        figs = parse_worldbank(wb_payload(sid, label, pick), agency="worldbank", extracted_at=extracted)
        tallies[sid] = store_figures(db, figs)
    mcs = (
        "commodity,commodity_id,area,area_code,year,measure,value,unit\n"
        "Rare earths,rare-earths,World,WLD,2023,production,350000,metric tons REO\n"
        "Rare earths,rare-earths,China,CN,2023,production,240000,metric tons REO\n"
        "Rare earths,rare-earths,United States,US,2023,production,43000,metric tons REO\n"
        "Rare earths,rare-earths,Australia,AU,2023,production,18000,metric tons REO\n"
        "Rare earths,rare-earths,World,WLD,2023,reserves,110000000,metric tons REO\n"
        "Rare earths,rare-earths,United States,US,2023,net_import_reliance,,percent\n"
    )
    tallies["usgs"] = store_figures(db, parse_mcs_csv(mcs, extracted_at=extracted))
    for sym, base in [("SP500", 4800.0), ("SPASTT01DEM661N", 118.0),
                      ("SPASTT01FRM661N", 124.0), ("SPASTT01GBM661N", 109.0)]:
        for m in range(24):
            db.add(CommodityPrice(symbol=sym, market="walk-seed",
                                  observed_on=date(2024, 7, 1) + timedelta(days=30 * m),
                                  price=round(base * (1 + 0.004 * m + rng.uniform(-0.02, 0.02)), 2),
                                  currency="USD" if sym == "SP500" else "idx", unit="idx",
                                  source="walk-L-seed"))
    code = LawDocument(jurisdiction="fr", title="Walk Code civil (extract)",
                       url="https://law.walk.invalid/fr/code", last_checked_at=naive - timedelta(hours=4))
    act = LawDocument(jurisdiction="uk", title="Walk Act 2026", url="https://law.walk.invalid/uk/act",
                      last_checked_at=naive - timedelta(hours=2))
    eu = LawDocument(jurisdiction="eu", title="Walk EU Regulation 2026/1", url="https://law.walk.invalid/eu/reg",
                     last_checked_at=naive - timedelta(hours=3))
    db.add_all([code, act, eu])
    db.flush()
    db.add_all([
        LawRevision(document_id=code.id, content_hash="l1", delta_bytes=-640, observed_at=naive - timedelta(hours=4),
                    flagged=True, flag_reasons="large-removal",
                    diff="-Article 12: the old wording.\n+Article 12: the new wording."),
        LawRevision(document_id=code.id, content_hash="l2", delta_bytes=0, observed_at=naive - timedelta(hours=1)),
        LawRevision(document_id=act.id, content_hash="u1", delta_bytes=120, observed_at=naive - timedelta(hours=2),
                    diff="+Section 3A: a new subsection."),
        LawRevision(document_id=eu.id, content_hash="e1", delta_bytes=80, observed_at=naive - timedelta(hours=3),
                    diff="+Article 5(2): amended."),
    ])
    db.commit()
finally:
    db.close()

# Wikipedia lane change rows (copied from the living-sources walk seed).
from src.versioned.models import VersionedChange, VersionedCursor, VersionedRevision  # noqa: E402
from src.versioned.pipeline import ensure_entity  # noqa: E402
from src.versioned.store import create_lane, lane_session  # noqa: E402

create_lane("wiki")
with lane_session("wiki") as lane:
    rome = ensure_entity(lane, "en:Walk Rome", title="Walk Rome", language="en")
    lyon = ensure_entity(lane, "fr:Walk Lyon", title="Walk Lyon", language="fr")
    lane.flush()
    first = VersionedRevision(entity_id=rome.id, revision_ref="1001", content_hash="h1",
                              content="Rome is a city.\n", diff_method="no-previous-text")
    lane.add(first)
    lane.flush()
    lane.add_all([
        VersionedChange(entity_id=rome.id, change_ref="c0", feed="stream:en", change_kind="create",
                        recorded_at=now - timedelta(days=2), ingested_revision_id=first.id, byte_delta=16),
        VersionedChange(entity_id=lyon.id, change_ref="c2", feed="stream:fr", change_kind="edit",
                        recorded_at=now - timedelta(minutes=20), byte_delta=-120),
        VersionedCursor(feed="stream:en", contiguous_through=now - timedelta(minutes=3), updated_at=now),
    ])
    lane.commit()
print(json.dumps(tallies, default=str))
