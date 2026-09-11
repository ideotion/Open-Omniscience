"""The rows the candidate pipeline appends must reach the app AS SOURCES, and reach it
QUALIFIED -- on a fresh install and on the next boot of an existing one.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

Maintainer, 2026-09-11: "make sure the app's initial list of sources is updated as well as
their qualified status." Two mechanisms already existed and had never been tested TOGETHER,
which is where a gap would hide:

  * ``seed_default_sources`` stamps ``_provenance = "curated"`` on every row of
    ``configs/sources.yml`` -- and the pipeline's splice writes rows with NO ``via:`` tag,
    because provenance is a fact about the ROW, stripped on the way into a catalogue entry.
    So the tag the stamp keys on is added at SEED time, not by the splice.
  * ``stamp_curated_catalog`` admits exactly ``CURATED_PROVENANCES`` by that tag.

If either half drifted -- the splice writing a ``via:`` tag of its own, the seed losing its
provenance default, the stamp's scope narrowing -- the pipeline's whole output would land
in the catalogue and then sit ``unqualified`` forever, collected by nothing. That failure is
silent in both files separately and visible only end to end, so it is pinned end to end.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.catalog.provenance_scope import is_curated
from src.catalog.qualification import STATUS_QUALIFIED, stamp_curated_catalog
from src.database.models import Base, Source
from src.ingest.seed_sources import seed_default_sources

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _catalogue_domains() -> list[str]:
    raw = yaml.safe_load((_ROOT / "configs" / "sources.yml").read_text(encoding="utf-8"))
    return [str(r["domain"]) for r in (raw or {}).get("sources", []) or [] if r.get("domain")]


def test_every_curated_catalogue_row_that_seeds_comes_up_qualified(session):
    """A fresh install: the boot path seeds the catalogue and the stamp qualifies it. Asserted
    over the WHOLE of configs/sources.yml, so a row the pipeline appends is covered by
    construction rather than by a hand-listed sample that would age out."""
    seeded = seed_default_sources(session)
    assert seeded["created"] > 3000, seeded  # the real catalogue, not an empty read

    domains = set(_catalogue_domains())
    rows = session.query(Source).filter(Source.domain.in_(domains)).all()
    # Shadowed duplicates (a domain an earlier catalogue entry already claimed) never
    # register on any install -- that is a known, separately-reported catalogue fact, not a
    # seeding failure, so the assertion is over the rows that DID seed.
    assert len(rows) > 3000

    unstamped = [r.domain for r in rows if not is_curated(r)]
    assert unstamped == [], f"{len(unstamped)} catalogue rows seeded without a via:curated tag"

    stamp_curated_catalog(session)
    not_qualified = [
        r.domain
        for r in session.query(Source).filter(Source.domain.in_(domains)).all()
        if r.status != STATUS_QUALIFIED
    ]
    assert not_qualified == [], f"{len(not_qualified)} catalogue rows stayed unqualified"


def test_a_row_appended_after_an_install_is_added_and_qualified_on_the_next_boot(session):
    """An EXISTING install: the pipeline appends rows to the catalogue, and the next boot
    must ADD them and qualify them without disturbing what is already there. Simulated by
    seeding, then deleting a few rows to stand for an install that predates them, then
    re-running the same boot path."""
    seed_default_sources(session)
    stamp_curated_catalog(session)
    before = session.query(Source).count()

    # Three rows from the end of the catalogue: where the splice appends.
    newest = _catalogue_domains()[-3:]
    for domain in newest:
        session.query(Source).filter_by(domain=domain).delete()
    session.commit()
    assert session.query(Source).filter(Source.domain.in_(newest)).count() == 0

    # A pre-existing row whose status must not be touched by the re-seed.
    untouched = session.query(Source).filter(Source.status == STATUS_QUALIFIED).first()
    untouched_at = untouched.qualified_at

    again = seed_default_sources(session)
    assert again["created"] == len(newest), again  # only the missing rows, nothing duplicated
    assert session.query(Source).count() == before

    stamp_curated_catalog(session)
    readded = session.query(Source).filter(Source.domain.in_(newest)).all()
    assert len(readded) == len(newest)
    for r in readded:
        assert r.status == STATUS_QUALIFIED, r.domain
        assert r.enabled is True, r.domain  # qualified but disabled would collect nothing
        assert is_curated(r), r.domain

    session.refresh(untouched)
    assert untouched.qualified_at == untouched_at  # an existing verdict's clock is not restarted


def test_the_splice_writes_no_provenance_tag_so_the_seed_owns_it(session):
    """The seam itself: catalogue rows carry only descriptive tags on disk, and the ``via:``
    tag appears only after seeding. Pinned because a splice that started writing its own
    provenance tag would look harmless and would silently decide the stamp's scope."""
    raw = yaml.safe_load((_ROOT / "configs" / "sources.yml").read_text(encoding="utf-8"))
    on_disk = [
        t
        for r in (raw or {}).get("sources", []) or []
        for t in (r.get("tags") or [])
        if str(t).startswith("via:")
    ]
    assert on_disk == [], f"configs/sources.yml carries provenance tags on disk: {on_disk[:5]}"

    seed_default_sources(session)
    row = session.query(Source).filter_by(domain=_catalogue_domains()[-1]).one()
    assert "via:curated" in (row.tags or "")
