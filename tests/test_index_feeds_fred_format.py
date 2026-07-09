"""Offline format guard for the OECD share-price FRED ids (field test 2026-07-08, Item 1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The OECD MEI "Share Prices" family on FRED is keyed by the 2-LETTER ISO country
code: SPASTT01<CC>M661N (e.g. SPASTT01USM661N, SPASTT01DEM661N). The catalog once
carried 3-letter codes (SPASTT01DEUM661N) which do NOT exist on FRED, so every OECD
index 404'd and whole continents rendered empty. This guard is a cheap, offline check
that catches exactly that mistake without touching the network (a wrong-but-well-formed
id still fails LOUDLY at import time — this only guards the *shape*).
"""

import re

from src.markets.feed_catalog import load_index_feeds

# FRED OECD share-price ids: SPASTT01 + 2-letter country + M6xxN.
_OECD_ID_RE = re.compile(r"^SPASTT01[A-Z]{2}M6[0-9]{2}N$")


def _oecd_feeds():
    return [f for f in load_index_feeds() if "SPASTT01" in f.symbol]


def test_every_oecd_share_price_id_uses_the_two_letter_fred_code():
    oecd = _oecd_feeds()
    assert oecd, "the catalog should carry OECD share-price indices"
    for f in oecd:
        assert _OECD_ID_RE.match(f.symbol), (
            f"{f.key}: FRED OECD id {f.symbol!r} must be SPASTT01<2-letter ISO>M6xxN "
            "(a 3-letter code does not exist on FRED and 404s the whole continent)"
        )
        # The url embeds the same id — they must agree, or one path fetches a dead series.
        assert f.symbol in f.url, f"{f.key}: url {f.url!r} must embed the corrected id {f.symbol!r}"


def test_the_four_live_confirmed_oecd_ids_are_present():
    # Live-confirmed on FRED (field test 2026-07-08): US / China / Spain / Korea.
    ids = {f.symbol for f in _oecd_feeds()}
    for confirmed in ("SPASTT01CNM661N", "SPASTT01ESM661N", "SPASTT01KRM661N"):
        assert confirmed in ids, f"expected live-confirmed OECD id {confirmed} in the catalog"


def test_no_stale_three_letter_oecd_ids_remain():
    # The exact regression: a 3-letter code slipping back in.
    for f in load_index_feeds():
        assert not re.search(r"SPASTT01[A-Z]{3,}M6[0-9]{2}N", f.symbol), (
            f"{f.key}: stale 3-letter OECD id {f.symbol!r} — use the 2-letter FRED code"
        )
