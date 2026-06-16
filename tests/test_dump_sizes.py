"""
Tests for the bundled, dated Wikipedia dump SIZE ESTIMATES.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The estimates are shown INLINE in the edition picker so it is informative without
a per-edition network probe (zero-network boot / airplane mode stay intact). They
go stale, so a freshness test forces a re-review — mirroring the model catalog's
CATALOG_AS_OF discipline. The exact size is always read from the dump server at
download time.
"""

from __future__ import annotations

import re
from datetime import date

from fastapi.testclient import TestClient

from src.wiki.dump_sizes import (
    DUMP_SIZES_AS_OF,
    estimate_bytes,
    estimated_codes,
)
from src.wiki.languages import APP_LANGUAGE_CODES


def test_dump_sizes_freshness():
    """Fails once DUMP_SIZES_AS_OF is older than the window, forcing a re-review
    against https://dumps.wikimedia.org or a knowing date bump."""
    m = re.fullmatch(r"(\d{4})-(\d{2})", DUMP_SIZES_AS_OF)
    assert m, f"DUMP_SIZES_AS_OF must be 'YYYY-MM', got {DUMP_SIZES_AS_OF!r}"
    y, mo = int(m.group(1)), int(m.group(2))
    today = date.today()
    age_months = (today.year - y) * 12 + (today.month - mo)
    assert age_months >= 0, f"DUMP_SIZES_AS_OF {DUMP_SIZES_AS_OF} is in the future"
    # Dump sizes drift slower than the model catalog (9 mo) — re-review yearly.
    assert age_months <= 12, (
        f"Wikipedia dump size estimates are {age_months} months old "
        f"(DUMP_SIZES_AS_OF={DUMP_SIZES_AS_OF}). Re-verify src/wiki/dump_sizes.py "
        f"against https://dumps.wikimedia.org and bump DUMP_SIZES_AS_OF."
    )


def test_every_dump_eligible_edition_has_an_estimate():
    # Every edition the picker offers (the dump scope = APP_LANGUAGE_CODES) must
    # carry an inline estimate, so the picker never shows a blank size.
    missing = set(APP_LANGUAGE_CODES) - estimated_codes()
    assert not missing, f"dump-eligible editions without a size estimate: {sorted(missing)}"


def test_estimates_are_positive_and_english_is_largest():
    sizes = {code: estimate_bytes(code) for code in estimated_codes()}
    assert all(b is not None and b > 0 for b in sizes.values())
    # enwiki is by far the largest edition — a coarse sanity anchor.
    assert sizes["en"] == max(sizes.values())
    # Unknown codes get no estimate (the picker + probe still work).
    assert estimate_bytes("zz") is None
    assert estimate_bytes("") is None


def test_endpoint_includes_inline_size_estimates():
    from src.api.main import app

    with TestClient(app) as client:
        dumps = client.get("/api/wiki/languages?scope=dumps").json()
        watched = client.get("/api/wiki/languages").json()
    # Dumps scope carries the dated estimate per edition + the review date.
    assert dumps["size_estimate_as_of"] == DUMP_SIZES_AS_OF
    by_code = {x["code"]: x for x in dumps["languages"]}
    assert by_code["en"]["size_estimate_bytes"] == estimate_bytes("en")
    assert all("size_estimate_bytes" in x for x in dumps["languages"])
    # The watched-pages scope is unchanged: no inline size machinery there.
    assert "size_estimate_as_of" not in watched
    assert all("size_estimate_bytes" not in x for x in watched["languages"])
