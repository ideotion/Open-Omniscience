"""R24's per-article engine stamp: what it certifies, and what the identity is a hash of.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A restore will CARRY an incoming article's derived rows instead of re-extracting them
exactly when its stamp equals the identity a local re-index would stamp. So the two
failure modes worth a test are both about lying:

  * a stamp on an article whose rows the named engine did NOT fully produce (a
    keyword-only pass, a When x Where x Who failure) -- the restore would then carry
    rows a re-index would not reproduce, which is stale data shown as current;
  * an identity that does NOT change when the extraction does -- the same lie, one
    level up. The closure test at the bottom is what keeps the hashed file list from
    falling behind the code, which is the only way a hash of the code can lie.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.analytics.engine_identity as ei
from src.analytics.extract import ExtractedTerm, get_extractor
from src.analytics.store import index_article
from src.database.models import Article, Base, KeywordMention, Source  # noqa: F401

_REPO = Path(__file__).resolve().parents[1]


def _session():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(name="The Daily Test", domain="dailytest.example"))
    s.commit()
    return s


def _article(s, h="a", text="Chancellor Scholz met President Macron in Berlin on 12 March 2024."):
    a = Article(
        url=f"https://dailytest.example/{h}", canonical_url=f"https://dailytest.example/{h}",
        source_id=1, title="Budget talks", content=text, hash=h, language="en",
        created_at=datetime.now(UTC),
    )
    s.add(a)
    s.commit()
    return a


class _Fixed:
    """An extractor with a fixed vocabulary, so a test controls exactly what is written."""

    name = "baseline"
    gazetteer: dict = {}

    def __init__(self, terms):
        self._terms = terms

    def extract(self, text, **kw):
        return list(self._terms)


_TERMS = [ExtractedTerm(term="budget", normalized="budget", kind="term", count=2, first_offset=0)]


# --- what the stamp certifies ----------------------------------------------- #

def _stamp(s, a):
    from src.database.models import ArticleIndexStamp

    s.expire_all()
    row = s.get(ArticleIndexStamp, a.id)
    return None if row is None else (row.engine, row.inputs)


def _plant(s, a, engine="e1-" + "0" * 32, inputs="i1-" + "0" * 32):
    """A stamp from some other pass -- an older engine, or older inputs."""
    from src.database.models import ArticleIndexStamp

    s.add(ArticleIndexStamp(article_id=a.id, engine=engine, inputs=inputs))
    s.commit()


def test_a_full_pass_stamps_the_article_with_the_baseline_identity():
    s = _session()
    a = _article(s)
    index_article(s, a, extractor=get_extractor("baseline"), country=None)
    engine, inputs = _stamp(s, a)
    assert engine == ei.baseline_engine_id()
    assert inputs.startswith(ei.INPUTS_PREFIX)


def test_a_keyword_only_pass_keeps_a_stamp_from_the_same_engine_and_inputs():
    """Every row the stamp vouches for is still that pass's: the keyword pass just
    rewrote the keywords, and the When x Where x Who rows came from the same engine on
    the same text."""
    s = _session()
    a = _article(s)
    ex = get_extractor("baseline")
    index_article(s, a, extractor=ex, country=None)
    stamped = _stamp(s, a)
    index_article(s, a, extractor=ex, country=None, scope="keywords")
    assert _stamp(s, a) == stamped


def test_a_keyword_only_pass_clears_a_stamp_from_another_engine():
    """Now the article mixes two engines' rows. A stamp naming either would let a restore
    carry rows a re-index would not reproduce."""
    s = _session()
    a = _article(s)
    _plant(s, a)
    index_article(s, a, extractor=get_extractor("baseline"), country=None, scope="keywords")
    assert _stamp(s, a) is None


def test_a_keyword_only_pass_clears_a_stamp_on_different_inputs():
    """Same engine, but the body changed since the full pass: the kept place and entity
    rows describe the OLD text. Engine equality alone is not enough."""
    s = _session()
    a = _article(s)
    ex = get_extractor("baseline")
    index_article(s, a, extractor=ex, country=None)
    a.content = "An entirely new body about Madrid and Lisbon on 3 May 2025."
    s.commit()
    index_article(s, a, extractor=ex, country=None, scope="keywords")
    assert _stamp(s, a) is None


def test_a_full_pass_after_an_edit_re_certifies_on_the_new_inputs():
    s = _session()
    a = _article(s)
    ex = get_extractor("baseline")
    index_article(s, a, extractor=ex, country=None)
    before = _stamp(s, a)
    a.title = "A different headline"
    s.commit()
    index_article(s, a, extractor=ex, country=None)
    after = _stamp(s, a)
    assert after[0] == before[0] and after[1] != before[1]


def test_a_keyword_only_pass_never_invents_a_stamp():
    s = _session()
    a = _article(s)
    index_article(s, a, extractor=get_extractor("baseline"), country=None, scope="keywords")
    assert _stamp(s, a) is None


def test_a_failed_when_where_who_pass_does_not_certify_the_rows_it_kept(monkeypatch):
    """The savepoint puts the PREVIOUS place/entity/date rows back. The keywords are
    fresh, the rest is not, so an older stamp must go -- and the keywords must still land,
    because a bad deduction must never cost an article its keywords."""
    import src.timemap.whostore as whostore

    s = _session()
    a = _article(s)
    _plant(s, a)

    def _boom(*_a, **_k):
        raise ValueError("a place extractor bug")

    monkeypatch.setattr(whostore, "store_places_for_article", _boom)
    out = index_article(s, a, extractor=_Fixed(_TERMS), country=None)
    assert out["mentions"] == 1
    assert s.query(KeywordMention).filter_by(article_id=a.id).count() == 1
    assert _stamp(s, a) is None


def test_a_failed_when_where_who_pass_keeps_a_same_engine_stamp(monkeypatch):
    """The kept rows came from THIS engine's earlier full pass on the same inputs, so the
    article is still wholly that pass's output."""
    import src.timemap.whostore as whostore

    s = _session()
    a = _article(s)
    ex = _Fixed(_TERMS)
    index_article(s, a, extractor=ex, country=None)
    stamped = _stamp(s, a)
    assert stamped[0] == ei.engine_id(ex)

    def _boom(*_a, **_k):
        raise ValueError("a place extractor bug")

    monkeypatch.setattr(whostore, "store_places_for_article", _boom)
    index_article(s, a, extractor=ex, country=None)
    assert _stamp(s, a) == stamped


def test_an_uncomputable_identity_clears_the_stamp_and_the_pass_still_lands(monkeypatch):
    s = _session()
    a = _article(s)
    _plant(s, a)

    def _broken(*_a, **_k):
        raise RuntimeError("metadata unreadable")

    monkeypatch.setattr(ei, "engine_id", _broken)
    out = index_article(s, a, extractor=_Fixed(_TERMS), country=None)
    assert out["mentions"] == 1
    assert _stamp(s, a) is None


def test_deleting_the_article_deletes_its_stamp():
    """ON DELETE CASCADE: a stamp outliving its article would certify rows for an id a
    later article could reuse."""
    from sqlalchemy import text

    s = _session()
    s.execute(text("PRAGMA foreign_keys=ON"))  # the app's engine sets it on every connection
    assert s.execute(text("PRAGMA foreign_keys")).scalar() == 1, "FK enforcement did not take"
    a = _article(s)
    index_article(s, a, extractor=_Fixed(_TERMS), country=None)
    assert _stamp(s, a) is not None
    aid = a.id
    s.delete(a)
    s.commit()
    from src.database.models import ArticleIndexStamp

    assert s.get(ArticleIndexStamp, aid) is None


def test_the_stamps_fit_their_columns():
    from src.database.models import ArticleIndexStamp as _T

    assert len(ei.baseline_engine_id()) <= _T.__table__.c.engine.type.length
    probe = ei.index_inputs_digest(
        text="x", raw_content="x", title="t", language="en", detected_language=None,
        observed="2024-03-12", country="fr", self_forms={"daily test"},
    )
    assert len(probe) <= _T.__table__.c.inputs.type.length


# --- what the inputs digest is a hash of ------------------------------------- #

_BASE_INPUTS = {
    "text": "Scholz met Macron in Berlin.", "raw_content": "Scholz met Macron in Berlin.",
    "title": "Talks", "language": "en", "detected_language": None, "observed": "2024-03-12",
    "country": "de", "self_forms": {"daily test", "dailytest"},
}


@pytest.mark.parametrize(
    "field, value",
    [
        ("text", "Scholz met Macron in Paris."),
        ("raw_content", ""),  # stored compressed: the WWW stores see an empty body
        ("title", "Other talks"),
        ("language", "fr"),
        ("detected_language", "de"),
        ("observed", "2024-03-13"),
        ("country", "fr"),
        ("self_forms", {"another outlet"}),
    ],
)
def test_every_input_changes_the_digest(field, value):
    """Each field is in the digest because a reader of it exists in the pass. Dropping
    one would let a restore carry rows computed from a value the local re-index would
    not use."""
    base = ei.index_inputs_digest(**_BASE_INPUTS)
    changed = dict(_BASE_INPUTS, **{field: value})
    assert ei.index_inputs_digest(**changed) != base, f"{field} is not in the inputs digest"


def test_the_digest_does_not_depend_on_self_form_order():
    a = ei.index_inputs_digest(**dict(_BASE_INPUTS, self_forms=["b form", "a form"]))
    b = ei.index_inputs_digest(**dict(_BASE_INPUTS, self_forms=["a form", "b form"]))
    assert a == b


def test_the_two_sides_read_the_same_date_from_their_two_representations():
    """index_article holds the ORM datetime; the restore reads the stored text through
    raw sqlite3. The digest compares them, so they must agree -- a mismatch here would
    make EVERY carry fail closed and nothing would say why."""
    aware = datetime(2024, 3, 12, 23, 30, tzinfo=UTC)
    assert ei.date_part(aware) == "2024-03-12"
    assert ei.date_part("2024-03-12 23:30:00.000000") == "2024-03-12"
    assert ei.date_part("2024-03-12T23:30:00+00:00") == "2024-03-12"
    assert ei.date_part(None) is None
    assert ei.date_part("garbage") is None


def test_the_stored_text_of_a_timestamp_reads_back_to_the_same_date():
    """End to end through the real column type, not a hand-written string."""
    s = _session()
    a = _article(s)
    a.published_at = datetime(2024, 3, 12, 23, 30, tzinfo=UTC)
    s.commit()
    raw = s.execute(
        __import__("sqlalchemy").text("SELECT published_at FROM articles WHERE id = :i"),
        {"i": a.id},
    ).scalar()
    assert ei.date_part(raw) == ei.date_part(a.published_at) == "2024-03-12"


# --- what the identity is a hash of ------------------------------------------ #

def test_each_switch_changes_the_identity(monkeypatch):
    base = ei.baseline_engine_id()
    monkeypatch.setenv("OO_CODE_TOKEN_FILTER", "0")
    assert ei.baseline_engine_id() != base
    monkeypatch.setenv("OO_CODE_TOKEN_FILTER", "1")
    monkeypatch.setenv("OO_SEGMENTATION", "0")
    assert ei.baseline_engine_id() != base
    monkeypatch.setenv("OO_SEGMENTATION", "1")
    assert ei.baseline_engine_id() == base


def test_the_lemma_switch_changes_the_identity_when_lemmatisation_is_possible(monkeypatch):
    from src.analytics.lemma import extraction_lemma_enabled

    monkeypatch.setenv("OO_EXTRACT_LEMMA", "1")
    if not extraction_lemma_enabled():
        pytest.skip("simplemma is not installed, so the switch cannot change extraction")
    base = ei.baseline_engine_id()
    monkeypatch.setenv("OO_EXTRACT_LEMMA", "0")
    assert ei.baseline_engine_id() != base


def test_an_optional_dictionary_version_changes_the_identity(monkeypatch):
    base = ei.baseline_engine_id()
    real = ei._dist_version

    def _other(dist):
        return "0.0.0-elsewhere" if dist == "simplemma" else real(dist)

    monkeypatch.setattr(ei, "_dist_version", _other)
    assert ei.baseline_engine_id() != base


def test_a_changed_engine_file_changes_the_identity(monkeypatch):
    """Any byte, in code or in data -- a generated cities.yml shadowing the sample is a
    different engine, and so is a one-word stoplist edit."""
    base = ei.baseline_engine_id()
    real = ei._read
    # stopwords_iso has NO en.txt or fr.txt -- those languages' stopwords are constants
    # in src/services/stopwords.py, which ENGINE_MODULES hashes -- so a vendored list is
    # exercised through de.txt. The first two drafts of this test named en.txt, then
    # fr.txt; a target outside the hashed list is never read and proves nothing, so the
    # membership is now asserted FIRST and a wrong target fails as a wrong target.
    targets = (
        "src/analytics/extract.py",
        "src/services/stopwords.py",
        "configs/cities.yml",
        "configs/stopwords_iso/de.txt",
        "configs/stopwords_extra/de.yml",
    )
    listed = set(ei.engine_files())
    assert set(targets) <= listed, f"test targets outside the hashed list: {set(targets) - listed}"
    for target in targets:
        def _edited(rel, _t=target):
            data = real(rel)
            return (data or b"") + b"\n# edited" if rel == _t else data

        monkeypatch.setattr(ei, "_read", _edited)
        ei.code_digest.cache_clear()
        try:
            assert ei.baseline_engine_id() != base, f"{target} is not in the identity"
        finally:
            monkeypatch.setattr(ei, "_read", real)
            ei.code_digest.cache_clear()
    assert ei.baseline_engine_id() == base


def test_an_absent_file_is_not_an_empty_file(monkeypatch):
    real = ei._read
    monkeypatch.setattr(ei, "_read", lambda rel: None if rel == "configs/cities.yml" else real(rel))
    ei.code_digest.cache_clear()
    absent = ei.code_digest()
    monkeypatch.setattr(ei, "_read", lambda rel: b"" if rel == "configs/cities.yml" else real(rel))
    ei.code_digest.cache_clear()
    empty = ei.code_digest()
    ei.code_digest.cache_clear()
    assert absent != empty


def test_a_gazetteer_changes_the_identity():
    from src.analytics.extract import BaselineExtractor

    assert ei.engine_id(BaselineExtractor()) == ei.baseline_engine_id()
    assert ei.engine_id(BaselineExtractor(gazetteer={"acme": "org"})) != ei.baseline_engine_id()


def test_every_named_engine_module_exists():
    """A renamed module would otherwise hash as '<absent>' for ever and stop tracking the
    code it was meant to follow -- a silent un-listing."""
    missing = [m for m in ei.ENGINE_MODULES if not (_REPO / m).is_file()]
    assert not missing, f"engine modules that no longer exist: {missing}"


def test_the_identity_is_the_same_in_two_fresh_interpreters():
    """Stamps are compared ACROSS MACHINES, so nothing in the identity may depend on
    per-process state -- hash randomisation, set order, a cache warmed differently."""
    code = "import src.analytics.engine_identity as e; print(e.baseline_engine_id())"
    env = dict(os.environ, PYTHONHASHSEED="random")
    runs = {
        subprocess.run(
            [sys.executable, "-c", code], cwd=_REPO, env=env, capture_output=True, text=True,
            check=True,
        ).stdout.strip()
        for _ in range(2)
    }
    assert len(runs) == 1, f"the identity differs between processes: {runs}"
    assert runs == {ei.baseline_engine_id()}


# --- the closure: the hashed list cannot fall behind the code ---------------- #

_PROBE = textwrap.dedent(
    r'''
    import builtins, io, json, os, sys
    from datetime import UTC, datetime
    from pathlib import Path
    os.environ.setdefault("OO_DB_PLAINTEXT", "1")
    opened = set()
    _open = builtins.open
    def _spy(file, *a, **k):
        try:
            opened.add(str(Path(os.fspath(file)).resolve()))
        except Exception:
            pass
        return _open(file, *a, **k)
    builtins.open = _spy
    io.open = _spy
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from src.database.models import Article, Base, Source
    before = set(sys.modules)
    from src.analytics.extract import get_extractor
    from src.analytics.store import index_article
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    s.add(Source(name="The Daily Test", domain="dailytest.example")); s.commit()
    texts = [
        ("en", "President Macron met Chancellor Scholz in Berlin on 12 March 2024 to discuss the budget."),
        ("fr", "Le président Macron a rencontré le chancelier à Berlin le 12 mars 2024."),
        ("de", "Bundeskanzler Scholz traf Präsident Macron am 12. März 2024 in Berlin."),
        ("zh", "中国政府在北京宣布了新的经济政策。"),
        (None, "An article with no stated language about the United Nations in New York."),
    ]
    for i, (lang, t) in enumerate(texts):
        a = Article(url=f"https://d.example/{i}", canonical_url=f"https://d.example/{i}",
                    source_id=1, title=f"T{i}", content=t, hash=f"h{i}", language=lang,
                    created_at=datetime.now(UTC))
        s.add(a); s.commit()
        index_article(s, a, extractor=get_extractor("baseline"), country=a.country)
    mods = {}
    for name in set(sys.modules) - before:
        f = getattr(sys.modules[name], "__file__", None)
        if name.startswith("src.") and f:
            mods[name] = f
    print(json.dumps({"modules": mods, "opened": sorted(opened)}))
    '''
)


def _probe() -> dict:
    out = subprocess.run(
        [sys.executable, "-c", _PROBE], cwd=_REPO, capture_output=True, text=True, check=True,
        env=dict(os.environ, OO_DB_PLAINTEXT="1"),
    ).stdout
    return json.loads(out.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def probe():
    return _probe()


def test_every_module_a_pass_loads_is_hashed_or_triaged(probe):
    """A module that shapes the output and is missing from ENGINE_MODULES is a code path
    the identity cannot see change. Triage each new one: hash it, or say why not."""
    known = set(ei.ENGINE_MODULES) | set(ei.NOT_OUTPUT_AFFECTING)
    loaded = {
        str(Path(f).resolve().relative_to(_REPO)) for f in probe["modules"].values()
        if _REPO in Path(f).resolve().parents
    }
    untriaged = sorted(loaded - known)
    assert not untriaged, (
        "a full index pass loads modules the engine identity neither hashes nor exempts: "
        f"{untriaged} -- add each to ENGINE_MODULES, or to NOT_OUTPUT_AFFECTING with the "
        "reason it cannot change what a pass writes"
    )


def test_every_repo_file_a_pass_opens_is_hashed_or_triaged(probe):
    """The same rule for data: a stoplist, a gazetteer, a lemma table in the repo."""
    covered = set(ei.engine_files())
    exempt = tuple(ei.NOT_OUTPUT_AFFECTING_FILES)
    untriaged = []
    for f in probe["opened"]:
        p = Path(f)
        if _REPO not in p.parents or "site-packages" in p.parts or p.suffix == ".py":
            continue
        rel = str(p.relative_to(_REPO))
        if rel in covered or rel.startswith(exempt):
            continue
        untriaged.append(rel)
    assert not untriaged, (
        f"a full index pass reads repo files the engine identity does not cover: {untriaged}"
    )


def test_every_installed_dictionary_a_pass_opens_is_versioned(probe):
    """Files inside an installed distribution are identified by its version, so the
    distribution must be one the identity records."""
    dists = {d.casefold() for d in ei.ENGINE_DISTRIBUTIONS} | {"open_omniscience"}
    unknown = set()
    for f in probe["opened"]:
        parts = Path(f).parts
        if "site-packages" not in parts:
            continue
        top = parts[parts.index("site-packages") + 1]
        name = top.split("-")[0].casefold()
        if name.endswith(".dist-info"):
            name = name[: -len(".dist-info")]
        if name not in dists:
            unknown.add(top)
    assert not unknown, (
        f"a pass reads data from distributions the identity does not version: {sorted(unknown)}"
    )


def test_the_closure_probe_is_not_vacuous(probe):
    """If the probe stopped running a pass, every closure test above would pass on an
    empty set. Prove it saw the extraction."""
    names = set(probe["modules"])
    assert {"src.analytics.extract", "src.timemap.whostore", "src.analytics.store"} <= names
    assert any("stopwords" in f for f in probe["opened"])
