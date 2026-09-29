"""Licence lines for the points where data leaves the machine (Q1008 = a).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

An export, a bulletin and an evidence ZIP all carry content this project did not
write, under terms this project did not set. Q1008 rules that each of them carries
"the attribution lines that APPLY" -- which is the whole design constraint, because
the lazy reading is a fixed block of every licence we have ever touched, pasted onto
everything. A CC BY-SA line on a ZIP holding no Wikipedia text is not caution, it is
a false statement about the contents, and it teaches the reader to skip the block.

So a line here is emitted only against a MEASURED SIGNAL, and it carries the signal
that produced it (``because``) so a reader can check the claim rather than trust it.
The signals are cheap strings the carrier already knows:

  * ``table:<name>`` -- a corpus table with rows > 0 (the export already counts
    every table for the completion panel, so this costs nothing extra);
  * ``source_type:<t>`` / ``domain:<d>`` -- a Source that actually CONTRIBUTED to
    the carrier (the evidence ZIP already collects exactly this set while it
    streams; the bulletin gets it from the edition's contributing sources);
  * ``files:<category>`` -- a large-data category copied beside the artifact.

ONE REFUSAL, and one line that used to be a refusal:

1. **A gap is published as a gap.** ``law_documents`` carries no licence column --
   the model has ``official_url`` and nothing about terms. So the law line does not
   guess a licence per jurisdiction (public-domain-by-default is FALSE in most of
   the world and expensively so); it states that this corpus recorded no licence
   metadata and points at the official source. A missing fact reads as a missing
   fact.

2. **OpenStreetMap carries its credit and the ODbL (Q823 = a, ruled 2026-09-29).** OSM
   data may leave the machine, and wherever it does it carries OSM's credit and the Open
   Database License line with its share-alike term, exactly as Wikipedia text carries
   CC BY-SA. Until that ruling this module REFUSED any carrier holding OSM-derived rows
   rather than render a block silently short of a line nobody had decided; the line now
   exists, so the refusal is gone and the line rides on the same measured signals as
   every other: the ``osm_*`` corpus tables, the ``places`` gazetteer (its ids are OSM
   ids), and a copied Geofabrik extract (``files:osm_regions``), which is upstream ODbL
   data leaving the machine as much as a derived row is.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

#: Corpus tables whose rows are OSM-DERIVED: the lane's ``osm_*`` tables, and ``places``,
#: the gazetteer whose ids are OSM ids (S05-03).
OSM_DERIVED_TABLE_PREFIXES = ("osm_",)
OSM_DERIVED_TABLES = ("places",)


class PendingRulingError(RuntimeError):
    """Raised when a carrier's contents need a licence line no ruling has settled.

    Nothing raises it today: its one case, OSM-derived rows, was ruled (Q823 = a). The
    carriers keep catching it, so the day a new source arrives whose line waits on a
    ruling, refusing is still one ``raise`` away and every carrier already reports it."""


@dataclass(frozen=True)
class AttributionLine:
    """One licence line, with the measured reason it applies."""

    key: str
    text: str
    because: str

    def to_dict(self) -> dict[str, str]:
        return {"key": self.key, "text": self.text, "because": self.because}


def table_signal(name: str) -> str:
    return f"table:{name}"


def source_type_signal(source_type: str) -> str:
    return f"source_type:{source_type}"


def domain_signal(domain: str) -> str:
    return f"domain:{domain}"


def files_signal(category: str) -> str:
    return f"files:{category}"


def signals_from_tables(tables: dict[str, int] | None) -> set[str]:
    """``table:<name>`` for every table that actually holds rows.

    A table present but EMPTY is not a signal: an export of a corpus whose
    ``wiki_pages`` table exists and is empty carries no Wikipedia text, and saying
    otherwise is the false-statement failure this module exists to avoid.
    """
    return {table_signal(n) for n, c in (tables or {}).items() if int(c or 0) > 0}


def signals_from_sources(rows: Iterable[dict]) -> set[str]:
    """``source_type:``/``domain:`` for the sources that CONTRIBUTED to a carrier."""
    out: set[str] = set()
    for r in rows or ():
        st = (r.get("source_type") or "").strip().lower()
        dom = (r.get("domain") or "").strip().lower()
        if st:
            out.add(source_type_signal(st))
        if dom:
            out.add(domain_signal(dom))
    return out


def _wikipedia_because(signals: set[str]) -> str | None:
    hits = sorted(
        s
        for s in signals
        if s in (table_signal("wiki_pages"), table_signal("wiki_revisions"))
        or (s.startswith("domain:") and s.endswith(".wikipedia.org"))
    )
    return ", ".join(hits) if hits else None


def _law_because(signals: set[str]) -> str | None:
    hits = sorted(
        s
        for s in signals
        if s in (table_signal("law_documents"), table_signal("law_revisions"))
        or s in (source_type_signal("law"), source_type_signal("legal"))
        or (s.startswith("domain:law.") and s.endswith(".local"))
    )
    return ", ".join(hits) if hits else None


def _db_ip_because(signals: set[str]) -> str | None:
    # The bundled DB-IP country table lives in the PACKAGE, not the data directory,
    # and its lookups are done at query time and never written to a corpus row -- so
    # no DB-IP content rides an export, a bulletin or an evidence ZIP today, and no
    # line is emitted. The signal is declared anyway (rather than the line being
    # dropped from the registry) so the day a DB-IP-derived value is stored or the
    # table is carried as a member, the line appears on its own.
    hits = sorted(
        s
        for s in signals
        if s in (table_signal("ip_geo_ranges"), "member:geo/dbip_country_lite.csv")
    )
    return ", ".join(hits) if hits else None


def _open_meteo_because(signals: set[str]) -> str | None:
    # ``files:weather_context``: cached reanalysis slices carried as members (the Claim
    # Workspace's trail bundle carries the ones this machine already held).
    hits = sorted(
        s for s in signals
        if s in (table_signal("weather_observations"), files_signal("weather_context"))
    )
    return ", ".join(hits) if hits else None


def _openstreetmap_because(signals: set[str]) -> str | None:
    hits = sorted(
        s
        for s in signals
        if (s.startswith("table:") and (
            any(s[len("table:"):].startswith(p) for p in OSM_DERIVED_TABLE_PREFIXES)
            or s[len("table:"):] in OSM_DERIVED_TABLES))
        or s == files_signal("osm_regions")
    )
    return ", ".join(hits) if hits else None


def _wikipedia_text() -> str:
    return (
        "Wikipedia text — CC BY-SA 4.0 "
        "(https://creativecommons.org/licenses/by-sa/4.0/). Attribute Wikipedia and "
        "its contributors, and share any work derived from this text alike."
    )


def _law_text() -> str:
    return (
        "Tracked legal documents — this corpus records NO licence metadata for them. "
        "Each document's terms are those of the official source it was mirrored from "
        "(the official URL stored with the document); check them before "
        "redistributing. That is a gap in what was recorded, never a grant."
    )


def _openstreetmap_text() -> str:
    # Q823 = a: OSM's own requested credit ("© OpenStreetMap contributors", with its
    # copyright page) and the licence line with its share-alike term.
    return (
        "Map data — © OpenStreetMap contributors (https://www.openstreetmap.org/copyright), "
        "available under the Open Database License 1.0 (ODbL, "
        "https://opendatacommons.org/licenses/odbl/1-0/). Credit OpenStreetMap, and share "
        "any database derived from this data alike, under the ODbL."
    )


def _db_ip_text() -> str:
    from src.geo.ip_geo import ATTRIBUTION

    return ATTRIBUTION


def _open_meteo_text() -> str:
    from src.weather.openmeteo import LICENSE_NOTE

    return LICENSE_NOTE


#: key -> (line text, the predicate that measures whether it applies). Ordered, so
#: every carrier renders the same lines in the same order.
_REGISTRY: tuple[tuple[str, object, object], ...] = (
    ("wikipedia", _wikipedia_text, _wikipedia_because),
    ("law", _law_text, _law_because),
    ("openstreetmap", _openstreetmap_text, _openstreetmap_because),
    ("db_ip", _db_ip_text, _db_ip_because),
    ("open_meteo", _open_meteo_text, _open_meteo_because),
)


def attribution_lines(signals: Iterable[str]) -> list[AttributionLine]:
    """The licence lines that APPLY to a carrier holding ``signals``."""
    sig = set(signals)
    lines: list[AttributionLine] = []
    for key, text_fn, because_fn in _REGISTRY:
        because = because_fn(sig)  # type: ignore[operator]
        if because:
            lines.append(AttributionLine(key=key, text=text_fn(), because=because))  # type: ignore[operator]
    return lines


def attribution_dicts(signals: Iterable[str]) -> list[dict[str, str]]:
    """:func:`attribution_lines` as plain dicts, for JSON payloads and manifests."""
    return [line.to_dict() for line in attribution_lines(signals)]


def attribution_markdown(lines: Iterable[AttributionLine], *, heading: str | None = None) -> str:
    """The lines as a Markdown block. Empty when nothing applies — an "Attribution"
    heading over no lines reads as a failure to compute, which is a different fact."""
    items = list(lines)
    if not items:
        return ""
    out: list[str] = []
    if heading:
        out += [heading, ""]
    for line in items:
        out.append(f"- {line.text}")
    return "\n".join(out) + "\n"
