"""Seed the data folder for the Claim Workspace S2 walk (steps ④ and ⑥, gate 0.5 row K).

Runs S1's seed (``../claim-workspace-clickthrough-2026-09-28/seed.py``: one wire story carried
four ways, two unconnected reports, a statistics record, an Arabic report, an unrelated market
story), then gives the trail something for step ④ to offer:

* two articles name a DROUGHT at Zermatt, with the place extractor's point -> one offer whose
  slice is NOT held (its button asks the host, behind the consent popup);
* one article names a FLOOD in France with no point -> one offer pinned to the
  gazetteer's stand-in city, whose slice IS held: an invented reanalysis slice is written to
  the local cache under the exact request URL, so "Show the slice held" is walked without any
  network. The slice is labelled as invented in its own provenance.
"""
import json
import runpy
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
runpy.run_path(str(HERE.parent / "claim-workspace-clickthrough-2026-09-28" / "seed.py"))

from src.analytics.claim_workspace import build_workspace  # noqa: E402
from src.database.models import Article, ArticleMentionedPlace, Keyword, KeywordMention  # noqa: E402
from src.database.session import SessionLocal  # noqa: E402
from src.weather.openmeteo import cache_path  # noqa: E402

db = SessionLocal()
try:
    by_title = {a.title: a for a in db.query(Article).all()}
    drought = Keyword(term="drought", normalized_term="drought", language="en")
    flood = Keyword(term="flood", normalized_term="flood", language="en")
    db.add_all([drought, flood])
    db.flush()
    for title in ("Alps glacier melt doubled", "Zurich glaciologists on the ice"):
        a = by_title[title]
        db.add(KeywordMention(keyword_id=drought.id, article_id=a.id, count=1,
                              observed_on=a.published_at.date()))
        db.add(ArticleMentionedPlace(article_id=a.id, name="Zermatt", country="ch", kind="city",
                                     lat=46.0207, lon=7.7491, note="walk seed"))
    a = by_title["Glacier melt doubled in the Alps"]
    db.add(KeywordMention(keyword_id=flood.id, article_id=a.id, count=1,
                          observed_on=a.published_at.date()))
    db.add(ArticleMentionedPlace(article_id=a.id, name="France", country="fr", kind="country",
                                 note="walk seed"))
    db.commit()

    ws = build_workspace(db, "Glacier melt in the Alps has doubled since 2000")
    offers = ws["corroboration"]["offers"]
    held = next(o for o in offers if o["rule"] == "flood")
    start = date.fromisoformat(held["window_start"])
    end = date.fromisoformat(held["window_end"])
    days = [date.fromordinal(d).isoformat() for d in range(start.toordinal(), end.toordinal() + 1)]
    daily = {"time": days}
    for i, v in enumerate(held["variables"]):
        daily[v] = [round(3.0 + ((k * (i + 3)) % 11) * 1.7, 1) for k in range(len(days))]
    cache_path(held["request_url"]).write_text(json.dumps({
        "ok": True, "label": held["rule_label"], "daily": daily,
        "units": {v: ("°C" if v.startswith("temperature") else "km/h" if v.startswith("wind") else "cm" if v.startswith("snowfall") else "mm")
                  for v in held["variables"]},
        "cached": False,
        "provenance": {"requested_url": held["request_url"], "fetched_at": "2026-09-28T12:00:00+00:00",
                       "dataset": "INVENTED for the walk: no host was asked",
                       "license": "walk fixture"},
    }))
    print("offers:", [(o["rule"], o["place"], o["coords_from"], o["cached"]) for o in offers])
finally:
    db.close()
