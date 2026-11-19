"""The autouse ``_empty_curated_domains_not_cached`` fixture (tests/conftest.py) drops an EMPTY cached read of the curated
catalogue domains at the end of the test that made it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

On #2140 a worker cached ``frozenset()`` (configs/ read while another test had renamed it away, row 180) and three later
tests in that worker failed. The second test runs after the first in this file (pytest keeps file order): it is red if
the first test's empty read was still cached.
"""

from __future__ import annotations

from src.catalog import provenance_scope as ps


def test_a_test_that_caches_an_empty_read(monkeypatch):
    monkeypatch.setattr(ps, "CURATED_CATALOGUE_FILES", ())
    ps._curated_catalogue_domains.cache_clear()
    assert ps._curated_catalogue_domains() == frozenset()
    assert ps._curated_catalogue_domains.cache_info().currsize == 1


def test_the_next_test_does_not_inherit_it():
    info = ps._curated_catalogue_domains.cache_info()
    assert info.currsize == 0 or ps._curated_catalogue_domains(), "an empty read outlived the test that made it"
