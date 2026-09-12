"""A feed that parses perfectly can still not be the institution's.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

Stage A asks whether a feed parses and is fresh, and refuses every other question on
purpose. A hijacked domain answers both beautifully -- an affiliate farm publishes several
times a day, so it is FRESHER than the ministry it replaced. Judges reading 1,840 rows found
a dozen of these one at a time; this scanner finds the same class from titles Stage A had
already fetched, at no token and no network cost.

THE FAILURE MODE THESE PIN IS THE SCANNER ACCUSING SOMEONE. Measured over 6,036 verified
rows, the bare lexicon flags 39, and about a dozen are entirely legitimate: a national
GAMBLING REGULATOR tendering casino licences, Italian football where "poker" is four goals
in a match, a historic Pamplona club called the Nuevo Casino Principal. THREE of them --
redgol.cl, elivebrescia.tv, radiorukungiri.co.ug -- are already in the shipped catalogue as
the news outlets they are, so a rule that auto-rejected on this signal would have deleted
them. Every title below is the real one those rows carried.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.analysis.scan_content_integrity import (
    FLAG_FIELDS,
    TIER_LEXICON,
    TIER_PLACEHOLDER,
    TIER_RESTRICTED,
    classify,
    scan,
)

_SRC = Path(__file__).resolve().parents[1] / "scripts/analysis/scan_content_integrity.py"


def _row(domain, titles, **kw):
    base = {"domain": domain, "name": domain, "country": "xx", "source_type": "institution",
            "status": "verified", "titles": titles, "feed_url": f"https://{domain}/feed"}
    base.update(kw)
    return base


def _run(tmp_path: Path, rows: list[dict], name: str = "w3") -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "verified.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )
    return d


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_the_namespace_is_what_raises_the_tier_not_the_words():
    """Identical content, two domains. Nobody but a government can HOLD a .gob.ve, so spam
    under one is a compromised live delegation; the same words on a .com may be a lapsed
    registration, an affiliate section, or a sports desk -- three different things a scanner
    cannot tell apart and must not pretend to."""
    titles = ["Casinos Sin Deposito en Casino online Espana",
              "WinBoss caracteristici In plus o secunda cel mai potrivit"]
    gov = classify(_row("italia.embajada.gob.ve", titles))
    com = classify(_row("italia-embajada.com", titles))
    assert gov["tier"] == TIER_RESTRICTED
    assert com["tier"] == TIER_LEXICON, (
        "the lexicon alone is ~0.6 precise; promoting it to the confident tier is how a "
        "scanner comes to accuse a gambling REGULATOR of being a gambling site"
    )


def test_the_three_catalogued_outlets_never_reach_the_confident_tier():
    """The anti-vacuity guard, and the one that would have cost real sources. These three are
    IN configs/sources.yml, doing their jobs. The scanner is allowed to put them on a reading
    list -- that is what a reading list is for -- and must never place them anywhere a
    caller could read as settled."""
    catalogued = [
        _row("redgol.cl", ["Como apostar en Serie A? Apuestas disponibles, cuotas y pronosticos"],
             country="cl"),
        _row("elivebrescia.tv", ["Union Brescia, vietato fermarsi: a Trento per il poker"],
             country="it"),
        _row("radiorukungiri.co.ug",
             ["Kagwirawo Rebrands to KBET, Launches a Unified Betting Experience"], country="ug"),
        _row("gamblingauthority.co.bw",
             ["EOI: THE DEVELOPMENT AND OPERATION OF BINGO AND CASINO ESTABLISHMENTS IN BOTSWANA"],
             country="bw"),
    ]
    for row in catalogued:
        hit = classify(row)
        assert hit is not None and hit["tier"] == TIER_LEXICON, (
            f"{row['domain']} is a legitimate outlet -- it may be READ, never concluded about"
        )


def test_the_restricted_namespaces_are_the_ones_a_private_party_cannot_register():
    """Both real families the corpus turned up, plus the negative that keeps the pattern
    from matching any old dotted name."""
    for domain in ("peru.embajada.gob.ve", "pn-ende.go.id", "usf.gov.jm", "nmim.gov.my",
                   "mik.brandenburg.de".replace("brandenburg.de", "gouv.fr"), "army.mil"):
        assert classify(_row(domain, ["Top Casino Bonuses 2026"]))["tier"] == TIER_RESTRICTED
    for domain in ("gamblingauthority.co.bw", "casino-news.gov-example.com", "govt.example.org"):
        assert classify(_row(domain, ["Top Casino Bonuses 2026"]))["tier"] == TIER_LEXICON


def test_a_placeholder_headline_is_a_whole_title_never_a_word_inside_one():
    """A feed whose entries are titled "test" is fresh about nothing -- the freshness Stage A
    measured is a CMS default, not publication. But "test" is also an ordinary word, and a
    substring match would flag every lab, exam board and drug regulator in the catalogue."""
    assert classify(_row("uruguay.embajada.gob.ve", ["test", "test", "test"]))["tier"] \
        == TIER_PLACEHOLDER
    assert classify(_row("nmim.gov.my", ["Lorem ipsum nulla amet"]))["tier"] == TIER_PLACEHOLDER
    assert classify(_row("lab.example", ["Latest test results published", "Testing programme"])) \
        is None
    assert classify(_row("news.example", ["Demonstration in the capital"])) is None


def test_a_row_reports_its_strongest_tier_and_still_records_every_rule():
    """Corroboration is worth seeing and must not inflate the verdict: two weak signals are
    two weak signals. The Venezuelan embassy rows that carry BOTH casino copy and "test"
    posts are the real instance."""
    hit = classify(_row("rumania.embajada.gob.ve",
                        ["Welcome Offers & Top crypto casinos canada Casino Bonuses", "test"]))
    assert hit["tier"] == TIER_RESTRICTED
    assert hit["rules"] == f"{TIER_PLACEHOLDER},{TIER_RESTRICTED}"


def test_a_clean_row_is_not_flagged_and_the_scan_counts_what_it_read(tmp_path):
    run = _run(tmp_path, [
        _row("australia.embajada.gob.ve",
             ["Venezuela asume la Presidencia del GRULAC en Australia"]),
        _row("chbany.cz", ["Rozpoctove opatreni c. 2/2026", "Pozvanka na 1. zasedani"]),
        _row("peru.embajada.gob.ve", ["Originel Salle de jeu casino bonus"]),
    ])
    out = tmp_path / "flags.csv"
    stats = scan([run], out)
    assert stats["scanned"] == 3 and stats["flagged"] == 1
    assert stats["by_tier"] == {TIER_RESTRICTED: 1}
    (flag,) = _read(out)
    assert flag["domain"] == "peru.embajada.gob.ve"
    assert set(flag) == set(FLAG_FIELDS)
    assert flag["evidence"], "a flag a reader cannot check is an accusation, not a finding"


def test_only_verified_rows_are_scanned_unless_asked_otherwise(tmp_path):
    """A deferred row was never fetched, so it has no content to contradict anything, and a
    rejected one is already out. Counting them would inflate the denominator the precision
    figure is quoted against."""
    run = _run(tmp_path, [
        _row("a.gov.uk", ["Casino bonus 2026"], status="verified"),
        _row("b.gov.uk", ["Casino bonus 2026"], status="deferred"),
        _row("c.gov.uk", ["Casino bonus 2026"], status="rejected"),
    ])
    assert scan([run], None)["scanned"] == 1
    assert scan([run], None, verified_only=False)["scanned"] == 3


def test_a_domain_judged_by_two_runs_is_listed_once(tmp_path):
    """The output is worked through by hand, so a duplicate is a second reading of the same
    site and an inflated count of how much is wrong."""
    a = _run(tmp_path, [_row("dup.gov.jm", ["Top Casino Bonuses"])], "a")
    b = _run(tmp_path, [_row("dup.gov.jm", ["Top Casino Bonuses"])], "b")
    stats = scan([a, b], None)
    assert stats["scanned"] == 1 and stats["flagged"] == 1


def test_the_scanner_never_opens_a_socket():
    """It reads finished run output. A content check that re-fetched would be a second fetch
    path outside EthicalFetcher, which the project does not have and must not grow here."""
    src = _SRC.read_text(encoding="utf-8")
    for lib in ("requests", "httpx", "urllib.request", "http.client", "socket", "aiohttp"):
        assert f"import {lib}" not in src, f"the scanner must not reach the network ({lib})"
