"""Ruling Q309 = a: a filename carrying a country uses UPPERCASE alpha-3.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

No file in the tree carries a country code TODAY. ``osm_filename`` keys on a
Geofabrik REGION and ``dump_filename`` on a Wikipedia EDITION, and neither is a
country. So this guards a rule for the files the briefs put next on it -- the
per-country OSM extracts of ``S05-04``, the law bundles of ``S04-10`` -- which is
precisely the kind of rule each of them would otherwise re-invent differently.

TWO INSTRUMENTS, BECAUSE NEITHER IS COMPLETE ALONE. The ledger records both halves
of this trap: "a detector keyed to NAMES is defeated by a rename", and, from the
translation-harvest pass, "a union of two incomplete instruments is still a guess
about the next string somebody adds -- ship a guard that fails on the next addition".

* The **NAME sweep** enumerates functions whose name says filename. Cheap, and it is
  what Q309's own wording asks for ("a repo test over ``data/`` naming helpers"). It
  is blind to a helper called something else.
* The **ARGUMENT sweep** enumerates functions that interpolate a COUNTRY-SHAPED
  parameter into a returned string. It is blind to a country arriving under a name
  nobody thought of.

Each sweep's blind spot is the other's subject, and both are asserted non-empty, so
a parser that stops resolving is a red test rather than a clean one. A general
"anything that returns a name with an extension" detector was tried first and
abandoned with the measurement written down: it resolves ~50 fixed state-file paths
(``data_dir() / "collect_perf.jsonl"``) that take no code at all and can never carry
a country, and a registry with fifty noise rows is one nobody reads.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.catalog.countries import country_display_code, country_filename

_SRC = Path(__file__).resolve().parent.parent / "src"

#: Builds a filename from a code that is deliberately NOT a country. Registering
#: these -- rather than letting them go unmatched -- is what stops this file passing
#: just as well against a tree where the sweeps found nothing.
_NON_COUNTRY_FILENAME_HELPERS = {
    # Geofabrik region codes: "europe", "north-america". A region is not a country
    # and several regions span many of them.
    ("src/geo/osm_downloads.py", "osm_filename"),
    # Wikipedia edition codes: "en", "simple", "zh-yue". An edition names a WIKI;
    # `simple` and `zh-yue` have no ISO 639-1 code at all, so reading one as a
    # language -- let alone as a country -- would assert something false.
    ("src/wiki/dumps.py", "dump_filename"),
    # Bulletin artifacts, keyed on the EDITION's period and an article's ordinal.
    # An edition covers whatever the corpus collected, which is many countries or
    # none; naming one for a country would assert a scope it does not have.
    ("src/bulletin/annexes.py", "annexes_filename"),
    ("src/bulletin/annexes.py", "article_filename"),
    ("src/bulletin/annexes.py", "contents_filename"),
    ("src/bulletin/store.py", "edition_filename"),
    ("src/bulletin/annexes.py", "report_filename"),
    # A language code in a downloadable report's stem. Languages are ruling Q306's
    # business; this one does not even return an extension (the call site adds
    # `.json`), which is why the extension-based sweep cannot see it and the NAME
    # sweep is what registers it.
    ("src/api/diagnostics/keywords.py", "_safe_lang_filename"),
    # A SANITISER, not a builder: it takes a name somebody else composed and makes it
    # safe. It never chooses a code, so it can never choose the wrong one.
    ("src/utils/security.py", "validate_and_sanitize_filename"),
}

#: The builder the rule is enforced BY. Listed apart from both sets: asking it to
#: call itself would be circular, and leaving it unregistered would make the
#: completeness assertion below fail on the one function that implements the rule.
_THE_BUILDER = {("src/catalog/countries.py", "country_filename")}

#: Builds a filename keyed on a COUNTRY. Empty is the correct state today, asserted
#: as such below, so the day something joins it the change is deliberate.
_COUNTRY_FILENAME_HELPERS: set[tuple[str, str]] = set()

#: Parameter names that carry a country. Small on purpose: a wider list starts
#: matching `region` and `area`, which are the two things Q309 is NOT about.
_COUNTRY_ARG_NAMES = {"country", "country_code", "cc", "iso2", "iso3", "jurisdiction"}

#: FILE extensions, not "anything after a dot". The argument sweep's first cut used
#: a generic `\.[a-z0-9]{1,6}` and flagged `src/law/corpus.py::_law_domain`, which
#: returns the synthetic HOSTNAME `law.<jurisdiction>.local` -- a fabricated FAIL is
#: exactly as dishonest as a fabricated pass, and this one accused a function that
#: builds no file at all. An allowlist's blind spot is a NEW file type, which is
#: precisely what the name sweep beside it catches.
_FILE_EXTS = (
    "json", "jsonl", "csv", "tsv", "md", "txt", "zip", "pbf", "xml", "html",
    "yml", "yaml", "db", "log", "bz2", "gz", "png", "svg", "pdf", "sqlite",
)
_EXT_RE = re.compile(r"\.(?:" + "|".join(_FILE_EXTS) + r")(?![a-z0-9])")
_FILENAME_NAME_RE = re.compile(r"(?:^|_)(?:filename|file_name)(?:$|_)")


def _modules() -> list[tuple[str, ast.Module]]:
    out = []
    for path in sorted(_SRC.rglob("*.py")):
        try:
            out.append((path.relative_to(_SRC.parent).as_posix(),
                        ast.parse(path.read_text(encoding="utf-8"))))
        except SyntaxError:  # pragma: no cover - a broken file is another test's job
            continue
    return out


def _by_name() -> set[tuple[str, str]]:
    """Functions whose NAME says they build a filename."""
    return {
        (rel, n.name)
        for rel, tree in _modules()
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and _FILENAME_NAME_RE.search(n.name)
    }


def _by_country_argument() -> set[tuple[str, str]]:
    """Functions that interpolate a COUNTRY-shaped parameter into a returned name.

    Follows one hop through a local: ``cc = normalize_country(country)`` then
    ``return f"{cc}.json"`` is the same composition one variable along, and refusing
    to follow it would miss the shape every real helper here actually uses.
    """
    found: set[tuple[str, str]] = set()
    for rel, tree in _modules():
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            params = {
                a.arg
                for a in fn.args.args + fn.args.kwonlyargs
                if a.arg in _COUNTRY_ARG_NAMES
            }
            if not params:
                continue
            derived = {
                t.id
                for a in ast.walk(fn)
                if isinstance(a, ast.Assign)
                for t in a.targets
                if isinstance(t, ast.Name)
                and any(
                    isinstance(n, ast.Name) and n.id in params for n in ast.walk(a.value)
                )
            }
            for node in ast.walk(fn):
                if not isinstance(node, ast.Return) or node.value is None:
                    continue
                has_ext = any(
                    isinstance(c, ast.Constant)
                    and isinstance(c.value, str)
                    and _EXT_RE.search(c.value)
                    for c in ast.walk(node.value)
                )
                names = {n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
                if has_ext and (names & (params | derived)):
                    found.add((rel, fn.name))
    return found


def test_the_name_sweep_still_sees_the_helpers_it_is_registered_against() -> None:
    """ANTI-VACUITY. Without this a parser that matched nothing would pass every
    assertion below for free -- which is how a ratchet reads 0 while the real count
    is 276."""
    found = _by_name()
    missing = _NON_COUNTRY_FILENAME_HELPERS - found
    assert not missing, (
        "the name sweep no longer finds these registered helpers, so every other "
        f"assertion in this file is passing vacuously: {sorted(missing)}"
    )
    assert len(found) >= len(_NON_COUNTRY_FILENAME_HELPERS)


def test_the_argument_sweep_can_see_a_country_bearing_helper_at_all() -> None:
    """The second instrument's OWN anti-vacuity check. It finds nothing in the tree
    today, which is the correct answer and is indistinguishable from a broken parser
    -- so it is driven against a synthetic module that genuinely has the shape."""
    sample = ast.parse(
        "def laws_bundle_filename(country):\n"
        "    cc = country_display_code(country)\n"
        '    return f"laws_{cc}.jsonl"\n'
    )
    fn = next(n for n in ast.walk(sample) if isinstance(n, ast.FunctionDef))
    params = {a.arg for a in fn.args.args if a.arg in _COUNTRY_ARG_NAMES}
    assert params, "the country-argument vocabulary no longer matches `country`"
    derived = {
        t.id
        for a in ast.walk(fn)
        if isinstance(a, ast.Assign)
        for t in a.targets
        if isinstance(t, ast.Name)
        and any(isinstance(n, ast.Name) and n.id in params for n in ast.walk(a.value))
    }
    assert "cc" in derived, "the one-hop local rule no longer follows an assignment"


def test_no_unregistered_function_builds_a_country_bearing_filename() -> None:
    """Every filename builder is deliberately classified. A new one joins the country
    set (and adopts ``country_filename``) or the non-country set (and says why)."""
    registered = _NON_COUNTRY_FILENAME_HELPERS | _COUNTRY_FILENAME_HELPERS | _THE_BUILDER
    unregistered = (_by_name() | _by_country_argument()) - registered
    assert not unregistered, (
        "these functions build a filename and are classified neither as "
        "country-bearing nor as deliberately non-country. Ruling Q309 = a: a "
        f"filename carrying a country uses uppercase alpha-3. {sorted(unregistered)}"
    )


def test_the_tree_carries_no_country_bearing_filename_today() -> None:
    """Stated as an assertion rather than left implied, so the day it stops being
    true somebody has to change this line on purpose."""
    assert _by_country_argument() == set(), (
        "a country-bearing filename builder appeared; register it in "
        f"_COUNTRY_FILENAME_HELPERS: {sorted(_by_country_argument())}"
    )
    assert _COUNTRY_FILENAME_HELPERS == set()


def test_every_country_bearing_filename_goes_through_the_one_builder() -> None:
    """The rule is enforced by a BUILDER, not by each caller remembering it."""
    for rel, name in sorted(_COUNTRY_FILENAME_HELPERS):
        tree = ast.parse((_SRC.parent / rel).read_text(encoding="utf-8"))
        fn = next(
            n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name
        )
        calls = {
            n.func.id
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "country_filename" in calls, (
            f"{rel}::{name} builds a country-bearing filename by hand; it must call "
            "country_filename so the rule cannot be re-derived per call site"
        )


def test_the_builder_emits_uppercase_alpha3() -> None:
    assert country_filename("laws", "de", ".jsonl") == "laws_DEU.jsonl"
    assert country_filename("osm", "fr", "pbf") == "osm_FRA.pbf"
    # Q303's named case: the law catalogue's `uk` is GBR, not UKG or GB.
    assert country_filename("laws", "uk", ".jsonl") == "laws_GBR.jsonl"
    # The whole point, as its own assertion: never the alpha-2, in either case.
    built = country_filename("laws", "de", ".jsonl")
    assert "_DE." not in built and "_de." not in built


def test_the_builder_refuses_rather_than_guessing() -> None:
    """A filename is permanent, so an unresolvable country is a refusal and not a
    best effort. The aggregate case is the one that matters: ``WLD`` looks exactly
    like an alpha-3 and is not a country."""
    for junk in ("WLD", "HIC", "XD", "", "floop"):
        with pytest.raises(ValueError):
            country_filename("laws", junk, ".jsonl")
    with pytest.raises(ValueError):
        country_filename("la/ws", "de", ".jsonl")
    with pytest.raises(ValueError):
        country_filename("laws", "de", "")


def test_a_fake_alpha2_helper_would_be_caught() -> None:
    """MUTATION-CHECK, in the file, as the brief asks: a helper emitting
    ``laws_de.jsonl`` must be distinguishable from one emitting ``laws_DEU.jsonl``
    by the property this rule is about, or the rule is unfalsifiable."""

    def fake_laws_filename(country: str) -> str:
        return f"laws_{(country or '').lower()}.jsonl"

    fake = fake_laws_filename("de")
    real = country_filename("laws", "de", ".jsonl")
    assert fake != real
    code = country_display_code("de")
    assert code is not None and code in real and code not in fake, (
        "the rule must be able to tell the two apart; if this ever holds for both, "
        "the assertion above is testing nothing"
    )
    # And the name sweep must SEE a helper of that shape, or a real `laws_de.jsonl`
    # would ship unregistered: the detector's reach is part of the guarantee.
    sample = ast.parse(
        "def laws_filename(country):\n    return f\"laws_{country}.jsonl\"\n"
    )
    fn = next(n for n in ast.walk(sample) if isinstance(n, ast.FunctionDef))
    assert _FILENAME_NAME_RE.search(fn.name)
