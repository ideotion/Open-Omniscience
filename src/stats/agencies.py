"""
Curated catalog of official statistical agencies (Group N, official-statistics
ingestion — first data-layer slice).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Government + international statistical producers, to be ingested LATER as
CONTROVERSIAL sources like any other (maintainer ruling, Group N): a figure carries
its producing state + agency + publication date + methodology reference; vintages are
kept; comparability guards (SA/NSA, base years) apply; official machine endpoints
(SDMX / APIs) are preferred over scraping; producers are triangulated SIDE BY SIDE,
never averaged. This module is ONLY the descriptive directory — NO figures, NO scores,
NO ranking, and NO network (the home URLs are metadata, not fetched here).

DELIBERATELY GLOBAL (the ruling): national agencies span every continent, with BRICS,
Africa and "forgotten regions" included on purpose alongside the usual Western + IGO
producers — coverage is measured per continent, not skewed to the loudest publishers.

HONESTY: ``controversial=True`` on every entry states the obvious — an official figure
is a STANCED source (a producing state has interests); presence here is a directory of
WHO publishes, never a credibility verdict.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StatAgency:
    code: str  # short stable key (lowercase, hyphenated)
    name: str  # full agency name
    acronym: str  # common acronym
    scope: str  # "national" | "international"
    country: str | None  # ISO-3166 alpha-2 for national agencies; None for IGOs
    region: str  # continent / "International"
    home_url: str  # official site (descriptive metadata; NOT fetched here)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "acronym": self.acronym,
            "scope": self.scope,
            "country": self.country,
            "region": self.region,
            "home_url": self.home_url,
            # Every official producer is a STANCED source (the ruling): stated, never
            # a score. Surfaced so a figure is never mistaken for neutral ground truth.
            "controversial": True,
        }


# A representative, deliberately global set. National producers span every inhabited
# continent (BRICS + Africa + smaller economies on purpose), plus the major IGOs.
_AGENCIES: tuple[StatAgency, ...] = (
    # --- International / intergovernmental ---------------------------------- #
    StatAgency("worldbank", "World Bank Open Data", "World Bank", "international", None,
               "International", "https://data.worldbank.org"),
    StatAgency("imf", "International Monetary Fund — data", "IMF", "international", None,
               "International", "https://www.imf.org/en/Data"),
    StatAgency("oecd", "OECD Statistics", "OECD", "international", None,
               "International", "https://data.oecd.org"),
    StatAgency("unstats", "United Nations Statistics Division", "UNSD", "international", None,
               "International", "https://unstats.un.org"),
    StatAgency("eurostat", "Eurostat (European Union)", "Eurostat", "international", None,
               "Europe", "https://ec.europa.eu/eurostat"),
    StatAgency("ilo", "International Labour Organization — ILOSTAT", "ILO", "international", None,
               "International", "https://ilostat.ilo.org"),
    StatAgency("fao", "Food and Agriculture Organization — FAOSTAT", "FAO", "international", None,
               "International", "https://www.fao.org/faostat"),
    StatAgency("who", "World Health Organization — Global Health Observatory", "WHO",
               "international", None, "International", "https://www.who.int/data/gho"),
    # --- Americas ----------------------------------------------------------- #
    StatAgency("us-bls", "U.S. Bureau of Labor Statistics", "BLS", "national", "US",
               "North America", "https://www.bls.gov"),
    StatAgency("us-census", "U.S. Census Bureau", "Census", "national", "US",
               "North America", "https://www.census.gov"),
    StatAgency("ca-statcan", "Statistics Canada", "StatCan", "national", "CA",
               "North America", "https://www.statcan.gc.ca"),
    StatAgency("mx-inegi", "Instituto Nacional de Estadística y Geografía", "INEGI",
               "national", "MX", "North America", "https://www.inegi.org.mx"),
    StatAgency("br-ibge", "Instituto Brasileiro de Geografia e Estatística", "IBGE",
               "national", "BR", "South America", "https://www.ibge.gov.br"),
    StatAgency("ar-indec", "Instituto Nacional de Estadística y Censos", "INDEC",
               "national", "AR", "South America", "https://www.indec.gob.ar"),
    # --- Europe ------------------------------------------------------------- #
    StatAgency("fr-insee", "Institut national de la statistique et des études économiques",
               "INSEE", "national", "FR", "Europe", "https://www.insee.fr"),
    StatAgency("de-destatis", "Statistisches Bundesamt", "Destatis", "national", "DE",
               "Europe", "https://www.destatis.de"),
    StatAgency("uk-ons", "Office for National Statistics", "ONS", "national", "GB",
               "Europe", "https://www.ons.gov.uk"),
    StatAgency("ru-rosstat", "Federal State Statistics Service", "Rosstat", "national", "RU",
               "Europe", "https://rosstat.gov.ru"),
    # --- Asia --------------------------------------------------------------- #
    StatAgency("cn-nbs", "National Bureau of Statistics of China", "NBS", "national", "CN",
               "Asia", "https://www.stats.gov.cn"),
    StatAgency("in-mospi", "Ministry of Statistics and Programme Implementation", "MoSPI",
               "national", "IN", "Asia", "https://www.mospi.gov.in"),
    StatAgency("jp-stat", "Statistics Bureau of Japan", "e-Stat", "national", "JP",
               "Asia", "https://www.stat.go.jp"),
    StatAgency("id-bps", "Badan Pusat Statistik", "BPS", "national", "ID",
               "Asia", "https://www.bps.go.id"),
    # --- Africa ------------------------------------------------------------- #
    StatAgency("za-statssa", "Statistics South Africa", "Stats SA", "national", "ZA",
               "Africa", "https://www.statssa.gov.za"),
    StatAgency("ng-nbs", "National Bureau of Statistics (Nigeria)", "NBS", "national", "NG",
               "Africa", "https://www.nigerianstat.gov.ng"),
    StatAgency("ke-knbs", "Kenya National Bureau of Statistics", "KNBS", "national", "KE",
               "Africa", "https://www.knbs.or.ke"),
    StatAgency("eg-capmas", "Central Agency for Public Mobilization and Statistics", "CAPMAS",
               "national", "EG", "Africa", "https://www.capmas.gov.eg"),
    # --- Oceania ------------------------------------------------------------ #
    StatAgency("au-abs", "Australian Bureau of Statistics", "ABS", "national", "AU",
               "Oceania", "https://www.abs.gov.au"),
)

_BY_CODE = {a.code: a for a in _AGENCIES}
_CONTINENTS = ("International", "Europe", "Asia", "Africa", "North America",
               "South America", "Oceania")
_RANK = {r: i for i, r in enumerate(_CONTINENTS)}


def list_agencies() -> list[StatAgency]:
    """The directory, grouped sensibly: international producers first, then by
    continent, then by name. Deterministic ordering."""
    return sorted(_AGENCIES, key=lambda a: (_RANK.get(a.region, 99), a.name))


def get_agency(code: str) -> StatAgency | None:
    return _BY_CODE.get((code or "").strip().lower())


def continents_covered() -> set[str]:
    """The set of continents with at least one NATIONAL producer (coverage metric —
    the ruling measures coverage per continent, never assumes it)."""
    return {a.region for a in _AGENCIES if a.scope == "national"}
