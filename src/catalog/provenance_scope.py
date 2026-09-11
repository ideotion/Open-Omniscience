"""Which sources SHIPPED with the app, as opposed to the ones it found for itself.

The distinction is already recorded, in the seed-time ``via:<origin>`` provenance tag, so
this needs no new column -- only a definition kept in ONE place, because the naive version
of it is wrong in a way that is invisible.

⚠ THE TRAP. ``via:wikidata`` and ``via:wikidata-discovery`` are DIFFERENT THINGS:

  * ``via:wikidata``           the committed ``world_news_sources.yml`` that ships with the app
  * ``via:wikidata-discovery`` what the RUNNING app found for itself (``catalog.discover``)

A prefix or substring match on ``via:wikidata`` silently captures both, which defeats the
"only the sources that came with the app" toggle entirely -- and it would do so quietly,
because the result still looks like a plausible subset. So the match is on the EXACT tag,
delimited, on both the Python and the SQL side.

The app-provided set is the five seed-time provenances (``src/ingest/seed_sources.py``);
the runtime channels are ``wikidata-discovery``, ``legal-generated`` and citation-promoted
sources. A source with no ``via:`` tag at all is treated as NOT app-provided: it was either
added by hand or predates the tagging, and claiming it shipped with the app would be a
guess about its origin.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

# Exactly the provenances `seed_sources.load_and_seed` stamps for catalogs COMMITTED to the
# repository. Kept as an exact set, never a prefix rule -- see the module docstring.
APP_PROVIDED_PROVENANCES: frozenset[str] = frozenset({
    "curated",    # configs/sources.yml, the hand-maintained catalogue
    "markets",    # the worldwide markets catalogue
    "spectrum",   # the source-diversification batch
    "wikidata",   # configs/world_news_sources.yml -- NOT wikidata-discovery
    "legal",      # the worldwide law & IP official portals
    "academic",   # configs/academic_sources.yml -- scholarly journals (2026-09-11 ruling)
    "official",   # configs/official_sources.yml -- primary-source bodies (2026-09-11 ruling)
})

APP_PROVIDED_TAGS: frozenset[str] = frozenset(
    f"via:{p}" for p in APP_PROVIDED_PROVENANCES
)

# THE CURATED CATALOGUE (maintainer ruling 2026-09-10: "make the curated catalogue qualified,
# and as with any other qualified sources, they should go through the same periodic
# re-qualification process"). A deliberately NARROWER set than the app-provided one: the
# catalogues a human assembled and vetted, whose entries the ruling admits without waiting
# for a trial. ``wikidata`` is app-provided but GENERATED -- a Wikidata query, never a
# person's judgement -- so it is not curated and keeps waiting its turn; ``legal-generated``
# is generated FROM the hand-vetted law catalogue (``configs/legal.yml``, the vetting
# board), which is why it is in. Exact tags, never a prefix, for the reason above.
CURATED_PROVENANCES: frozenset[str] = frozenset({
    "curated",          # configs/sources.yml
    "spectrum",         # configs/sources_spectrum.yml
    "markets",          # configs/markets_sources.yml
    "legal",            # configs/legal_sources.yml
    "legal-generated",  # configs/legal_sources_generated.yml, built from the vetted law catalogue
    # The 2026-09-11 ruling's two catalogues. They are here for the SAME reason the pipeline's
    # rows in sources.yml are: leaving them unqualified would park them behind the never-attempted
    # discovered rows (finding F2) and they would never be collected at all -- and qualification
    # is an extraction-validity check (this module's siblings measure it), never a quality gate,
    # so "earning" it would decide nothing. Same basis pill, same six-month re-check, same
    # disqualification on a failed one.
    "academic",         # configs/academic_sources.yml
    "official",         # configs/official_sources.yml
})

CURATED_TAGS: frozenset[str] = frozenset(f"via:{p}" for p in CURATED_PROVENANCES)


def _tags(raw: str | None) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def is_app_provided(source) -> bool:
    """True when this source came WITH the app rather than being found by it.

    Takes the source object (or anything with a ``.tags`` string) so callers do not each
    re-derive the tag parsing.
    """
    return any(t in APP_PROVIDED_TAGS for t in _tags(getattr(source, "tags", None)))


def is_curated(source) -> bool:
    """True when this source came from one of the hand-vetted catalogues (see
    ``CURATED_PROVENANCES``) -- the set the 2026-09-10 ruling stamps qualified at seed."""
    return any(t in CURATED_TAGS for t in _tags(getattr(source, "tags", None)))


def _tag_filter(column, tags: frozenset[str]):
    from sqlalchemy import literal, or_

    delimited = literal(",") + column + literal(",")
    return or_(*[delimited.like(f"%,{tag},%") for tag in sorted(tags)])


def app_provided_filter(column):
    """A SQLAlchemy predicate for the same definition, for use in a query.

    ``Source.tags`` is a comma-joined string, so an ``ILIKE '%via:wikidata%'`` would match
    ``via:wikidata-discovery`` as well -- the exact trap above. Wrapping the column in
    delimiters and matching ``%,via:wikidata,%`` makes the comparison token-exact, which is
    the same rule ``is_app_provided`` applies in Python.
    """
    return _tag_filter(column, APP_PROVIDED_TAGS)


def curated_filter(column):
    """The SQL twin of :func:`is_curated`, token-exact for the same reason."""
    return _tag_filter(column, CURATED_TAGS)
