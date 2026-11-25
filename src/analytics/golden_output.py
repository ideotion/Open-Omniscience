"""THE OUTPUT DIGEST: what the engine WRITES for a fixed golden corpus (R824 step 1, row 405).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

:mod:`src.analytics.engine_identity` versions the indexer by hand (``INDEXER_VERSION``,
``WWW_INDEXER_VERSION``) and polices the version with a CODE digest: a moved engine file needs a
recorded judgement, ``--bump`` or ``--same``. Its stated weakness is that a ``--same`` is only a
sentence. A wrong one keeps the version while the rows change, and a restore then carries rows the
re-index would no longer produce.

This module is the guard on that sentence. It runs one real indexing pass, ``index_article`` with
``get_extractor("baseline")`` (the extractor the carry compares against), over the golden corpus in
``tests/fixtures/extraction_golden/``, on a throwaway plaintext SQLite file, and hashes the rows each
stage wrote:

* ``"kw"`` (keywords and dates, ``INDEXER_VERSION``): the keyword mention rows, the keyword rows
  they point at, each article's top keyword, sentiment and language columns, and the mentioned-date
  rows;
* ``"www"`` (places and entities, ``WWW_INDEXER_VERSION``): ``article_mentioned_places`` and
  ``article_entities``.

The rows are CANONICALISED before hashing: no autoincrement id and no timestamp, a keyword named by
its text and language rather than its id, an article by its fixture id, a source by its name, floats
at nine significant digits, and the whole sorted. Two passes over the same corpus by the same engine
in the same environment give the same digest; a change to any row gives another.

THE ENVIRONMENT IS PART OF THE ANSWER. The rows depend on more than the code: optional dictionaries
(``simplemma``, ``jieba`` ...), the three operator switches, the interpreter's Unicode tables and the
data files. A digest is only comparable with one computed in the same environment, so each result
carries the environment it ran under -- the parts of the stage's engine identity that are NOT the
code (the code is what is being judged) -- and a caller that finds a different environment must say
it cannot judge, never pass.

Deliberately NOT one of ``ENGINE_MODULES``: no indexing pass imports it, and it shapes no row. It is
the police, and the police must not hash itself (the same rule as ``scripts/indexer_pin.py``).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path

#: The canonical form's own version. Change it only if the canonicalisation below changes shape,
#: since every recorded digest then stops being comparable.
CANON_SCHEMA = "oo-golden-output-1"

STAGES = ("kw", "www")

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "extraction_golden"


def load_fixture(fixture_dir: Path | None = None) -> dict:
    """Every fixture file merged: ``{"sources": [...], "articles": [...]}``, files in name order."""
    base = Path(fixture_dir or FIXTURE_DIR)
    sources: dict[str, dict] = {}
    articles: list[dict] = []
    for f in sorted(base.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        for s in data.get("sources", []):
            if s["name"] in sources and sources[s["name"]] != s:
                raise ValueError(f"{f.name}: source {s['name']!r} defined twice, differently")
            sources[s["name"]] = s
        articles.extend(data.get("articles", []))
    ids = [a["id"] for a in articles]
    if len(ids) != len(set(ids)):
        raise ValueError("golden fixture: duplicate article id")
    missing = sorted({a["source"] for a in articles} - set(sources))
    if missing:
        raise ValueError(f"golden fixture: undefined sources {missing}")
    return {"sources": [sources[k] for k in sorted(sources)], "articles": articles}


#: The scripts of the twelve UI languages, by the prefix ``unicodedata.name`` gives their letters.
SCRIPT_PREFIXES = {
    "ARABIC": "Arabic", "BENGALI": "Bengali", "DEVANAGARI": "Devanagari", "CJK UNIFIED": "Han",
    "HIRAGANA": "Hiragana", "KATAKANA": "Katakana", "CYRILLIC": "Cyrillic", "LATIN": "Latin",
}


def script_counts(text: str) -> dict[str, int]:
    """How many letters of ``text`` each script holds (the scripts above only)."""
    import unicodedata

    out: dict[str, int] = {}
    for ch in text or "":
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        for prefix, script in SCRIPT_PREFIXES.items():
            if name.startswith(prefix):
                out[script] = out.get(script, 0) + 1
                break
    return out


def main_script(text: str) -> str | None:
    """The script most of the text's letters are in, or None for a text with no letters in any of them."""
    counts = script_counts(text)
    return max(sorted(counts), key=lambda k: counts[k]) if counts else None


def scripts_covered(fixture: dict) -> list[str]:
    """Every script that is the main script of at least one article's text, plus kana that appears at all."""
    seen: set[str] = set()
    for a in fixture["articles"]:
        counts = script_counts(a.get("text") or "")
        if counts:
            main = main_script(a["text"])
            if main:
                seen.add(main)
            seen |= {k for k in ("Hiragana", "Katakana") if counts.get(k)}
    return sorted(s for s in seen if s)


#: The gazetteer files an install GENERATES (from its own OSM data, or a full city build) and the repo does not track: they change
#: the www rows per machine, so their presence and bytes are part of the environment. Every other data file the stages read
#: (stoplists, rings, the shipped sample gazetteer) is in the repository and is judged by the output digest itself, never treated
#: as "another environment": an edit to one is a change to what the stage writes, a --bump or a checked --same.
INSTALL_GENERATED_DATA: tuple[str, ...] = ("configs/cities.yml", "configs/places_gazetteer.yml")


def _generated_data_digest() -> str | None:
    root = Path(__file__).resolve().parents[2]
    present = [(rel, (root / rel).read_bytes()) for rel in INSTALL_GENERATED_DATA if (root / rel).is_file()]
    if not present:
        return None
    h = hashlib.sha256()
    for rel, data in present:
        h.update(rel.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


def _letter_script(ch: str) -> str:
    import unicodedata

    name = unicodedata.name(ch, "")
    for prefix, script in SCRIPT_PREFIXES.items():
        if name.startswith(prefix):
            return script
    return "other:" + (name.split(" ")[0] if name else "unnamed")


def www_rule_scripts() -> list[str]:
    """The scripts the places-and-entities stage's SHIPPED rules can match (R824 addition 2): the letters of every place pattern the
    locator builds, and every non-ASCII letter in the two extractors' sources (the entity rules are character classes there). On
    2026-11-24 this is ``["Latin"]``: the 161 place patterns and the entity rules are Latin-script only, so a Cyrillic, Arabic or Han
    text yields no www row, and the golden corpus, which holds texts in every UI script, covers the stage only as far as these
    scripts go. Run without an install-generated gazetteer (that is the environment, judged separately)."""
    import inspect

    from src.timemap import entextract, locextract

    seen: set[str] = set()
    for _i, _rx, name, _kind in locextract._dispatch()[0]:
        seen |= {_letter_script(ch) for ch in name if ch.isalpha()}
    for mod in (entextract, locextract):
        seen |= {_letter_script(ch) for ch in inspect.getsource(mod) if ch.isalpha() and ord(ch) > 127}
    return sorted(seen)


def www_golden_scripts(rows: dict[str, list]) -> list[str]:
    """The scripts the golden www rows themselves hold names in: what the golden corpus actually exercises for that stage."""
    seen: set[str] = set()
    for table in ("article_mentioned_places", "article_entities"):
        for row in rows.get(table, []):
            seen |= {_letter_script(ch) for ch in str(row[1]) if ch.isalpha()}
    return sorted(seen)


def environment(stage: str) -> dict:
    """What the stage's rows depend on besides the code and the repository's own data files: the dictionaries, switches,
    interpreter and Unicode tables, and the gazetteer files this install generated (:data:`INSTALL_GENERATED_DATA`). Two digests
    are comparable only when these are equal."""
    from src.analytics import engine_identity as ei

    keep: tuple[str, ...]
    if stage == "kw":
        comp = ei.engine_components(extractor_name="baseline")
        keep = ("distributions", "switches", "python", "unicode")
    elif stage == "www":
        comp = ei.www_engine_components()
        keep = ("python", "unicode")
    else:
        raise ValueError(f"unknown stage {stage!r}")
    out = {k: comp[k] for k in keep}
    out["generated_gazetteers"] = _generated_data_digest()
    return out


def _num(v):
    if isinstance(v, float):
        return format(v, ".9g")
    return v


def _rows(conn, sql: str) -> list[tuple]:
    from sqlalchemy import text

    return [tuple(_num(x) for x in r) for r in conn.execute(text(sql)).all()]


def _canonical(conn) -> dict[str, dict[str, list]]:
    """The rows each stage wrote, with every id replaced by a natural key and every timestamp dropped."""
    art = "(SELECT hash FROM articles a WHERE a.id = {col})"
    kw_text = "(SELECT k.normalized_term || '|' || COALESCE(k.language, '') FROM keywords k WHERE k.id = {col})"
    src = "(SELECT s.name FROM sources s WHERE s.id = {col})"
    kw = {
        "keyword_mentions": _rows(
            conn,
            f"SELECT {art.format(col='m.article_id')}, {kw_text.format(col='m.keyword_id')}, m.count, m.first_offset, "  # noqa: S608  # nosec B608 # module-local literals, never input
            f"m.observed_on, m.country, m.city, m.language, {src.format(col='m.source_id')}, m.extractor "
            "FROM keyword_mentions m",
        ),
        "keywords": _rows(
            conn,
            "SELECT term, normalized_term, language, frequency, is_ngram, ngram_size, is_entity, entity_type, "
            "relevance_score, extractor, mention_count, article_count FROM keywords",
        ),
        "articles": _rows(
            conn,
            f"SELECT hash, language, detected_language, sentiment_score, sentiment_label, "  # noqa: S608  # nosec B608 # module-local literals, never input
            f"{kw_text.format(col='top_keyword_id')}, top_keyword_count, top_keyword_tied_n FROM articles",
        ),
        "article_mentioned_dates": _rows(
            conn,
            f"SELECT {art.format(col='d.article_id')}, d.mentioned_on, d.precision, d.snippet, d.confidence, "  # noqa: S608  # nosec B608 # module-local literals, never input
            "d.extractor, d.status FROM article_mentioned_dates d",
        ),
    }
    www = {
        "article_mentioned_places": _rows(
            conn,
            f"SELECT {art.format(col='p.article_id')}, p.name, p.country, p.kind, p.mentions, p.snippet, "  # noqa: S608  # nosec B608 # module-local literals, never input
            "p.lat, p.lon, p.note, p.extractor FROM article_mentioned_places p",
        ),
        "article_entities": _rows(
            conn,
            f"SELECT {art.format(col='e.article_id')}, e.name, e.entity_class, e.mentions, e.snippet, e.note, "  # noqa: S608  # nosec B608 # module-local literals, never input
            "e.extractor FROM article_entities e",
        ),
    }
    out = {"kw": kw, "www": www}
    for stage in out.values():
        for name, rows in stage.items():
            stage[name] = sorted(rows, key=lambda r: json.dumps(r, ensure_ascii=False, default=str))
    return out


def run_pass(fixture: dict | None = None) -> dict[str, dict[str, list]]:
    """One full baseline indexing pass over the fixture on a fresh database; the canonical rows per stage."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker

    from src.analytics.extract import get_extractor
    from src.analytics.store import index_article
    from src.database.country_form import writing_in
    from src.database.models import Article, Base, Source

    fx = fixture or load_fixture()
    # The pass writes a side file, so it says which country form it writes in: without this it took the LIVE store's form, and the
    # digest moved with whatever corpus the machine (or a parallel test's data directory) held -- alpha-3 there, alpha-2 here. The
    # golden form is alpha-2, the form of a fresh install's store (the marker's absence).
    with writing_in("alpha2"), tempfile.TemporaryDirectory(prefix="oo-golden-") as tmp:
        eng = create_engine(f"sqlite:///{Path(tmp) / 'golden.db'}", future=True, hide_parameters=True)  # as the corpus engine

        def _fk(dbapi_connection, _record):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            # A throwaway file: durability buys nothing here, and a sync per article's commit was most of the time.
            cur.execute("PRAGMA synchronous=OFF")
            cur.execute("PRAGMA journal_mode=MEMORY")
            cur.close()

        event.listen(eng, "connect", _fk)
        try:
            Base.metadata.create_all(eng)
            s = sessionmaker(bind=eng, future=True)()
            try:
                ids: dict[str, int] = {}
                for so in fx["sources"]:
                    src_row = Source(
                        name=so["name"], domain=so["domain"], language=so.get("language"), country=so.get("country")
                    )
                    s.add(src_row)
                    s.flush()
                    ids[so["name"]] = src_row.id
                domains = {so["name"]: so["domain"] for so in fx["sources"]}
                arts = []
                for a in fx["articles"]:
                    url = f"https://{domains[a['source']]}/{a['id']}"
                    published = datetime.fromisoformat(a["published"])
                    row = Article(
                        url=url, canonical_url=url, source_id=ids[a["source"]], title=a.get("title") or "",
                        content=a.get("text") or "", hash=a["id"], language=a.get("language"),
                        country=a.get("country"), published_at=published, created_at=published,
                    )
                    s.add(row)
                    arts.append(row)
                s.commit()
                ex = get_extractor("baseline")
                for row in arts:
                    index_article(s, row, extractor=ex, country=None)
                with eng.connect() as conn:
                    return _canonical(conn)
            finally:
                s.close()
        finally:
            eng.dispose()


def digest_of(rows: dict[str, list]) -> str:
    blob = json.dumps({"canon": CANON_SCHEMA, "rows": rows}, ensure_ascii=False, sort_keys=True, default=str,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8", "surrogatepass")).hexdigest()


@lru_cache(maxsize=1)
def _cached_pass() -> dict[str, dict[str, list]]:
    return run_pass()


def golden_output(stage: str, *, fresh: bool = False) -> dict:
    """``{"output_digest", "environment", "articles", "rows"}`` for one stage (``"kw"`` or ``"www"``).

    One pass serves both stages; ``fresh=True`` re-runs it instead of reusing this process's last one."""
    if stage not in STAGES:
        raise ValueError(f"unknown stage {stage!r}")
    if fresh:
        _cached_pass.cache_clear()
    rows = _cached_pass()[stage]
    return {
        "output_digest": digest_of(rows),
        "environment": environment(stage),
        "articles": len(load_fixture()["articles"]),
        "rows": {k: len(v) for k, v in rows.items()},
    }


def environment_differences(recorded: dict, current: dict) -> list[str]:
    """The names of the environment components that differ (a distribution or switch by its own name)."""
    diffs: list[str] = []
    for key in sorted(set(recorded) | set(current)):
        a, b = recorded.get(key), current.get(key)
        if isinstance(a, dict) and isinstance(b, dict):
            diffs += [f"{key}.{k}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
        elif a != b:
            diffs.append(key)
    return diffs
