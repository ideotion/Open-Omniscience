"""R123 (maintainer ruling 29b): the evidence that lets "Keyword log (4 MB files)" and "Last keyword files,
again" leave the Diagnostics panel, and what stays.

The ruling keeps "All keywords" as a small text link and takes the other two buttons out *in the PR whose
test shows what the Diagnostics archive's keyword digest carries*. This is that test. It compares the
digest the bundle writes (``keyword-log-digest.json``) with the export the removed "Keyword log" button
built (``format=parts``, whose content is ``format=zip``'s, pinned in ``test_keyword_parts_route.py``), and
it states the one thing the digest does NOT carry, so the removal is not read as a claim it does not make:

* every summary the log held (corpus counts, families, the user's corrections, super-groups, per-source
  concentration, stop-word and ring candidates) is in the digest, equal to the export's, on a corpus whose
  languages fit the window and on one where they exceed it;
* the per-keyword list is a top-``_DIGEST_SAMPLE`` sample by mentions, the export's own entries, with
  ``keywords_digest`` saying how many were left out; the rest of the list is the "All keywords" link, whose
  first files hold the entries the removed button gave (a superset where that button's 9 MB aim trimmed a
  language's tail), but whose own ``summary.json`` is built over every keyword, not over the window;
* on a computer short of memory the families are grouped over the first keywords of each language only,
  the digest says so and points at "All keywords" (R130 = 36a), and the export it replaces is partial in
  the same way, so where the digest runs nothing is lost relative to the button.

WHERE THE DIGEST DOES NOT RUN this proves nothing, and the texts that rely on it say "when the build ran it":
a Quick build on a large corpus can leave it out for time (``skipped-budget`` in the scan table,
``tests/test_diagnostics_modes.py``), it can run past its own member time limit (``skipped-deadline``, the
time the Quick budget had left or ``OO_ALL_DIAG_DB_MEMBER_DEADLINE_S``), and a machine without the memory
declines it (``declined-ram``, ``ram_declined_reason``, ``tests/test_keyword_export_bounded.py``). There
"All keywords" is the way to the keywords. Thorough undoes the first (it runs every scan) and not the memory
gate, which declines the digest on Thorough too, unless ``OO_ALLOW_BIG_SCANS=1`` is set; the time limit
applies on Thorough as well.

No fixed number is asserted that the code does not state itself: the sample size is ``_DIGEST_SAMPLE``, and
the window the digest uses is the constant the module states (patched small here for the corpus whose
languages exceed it, which at the real 5,000 would need a corpus of tens of thousands of keywords).
"""

from __future__ import annotations

import importlib
import inspect
import json
import re
import sqlite3
import zipfile
from pathlib import Path

import pytest

import src.analytics.keyword_log_scan as kls
import src.api.diagnostics.keywords as kw_mod
from src.analytics import keyword_log_export as kle
from src.api.diagnostics._base import _MAX_KEYWORDS_PER_LANG
from src.api.diagnostics.keywords import _DIGEST_SAMPLE
from tests.test_keyword_export_bounded import _build, _drain_body, _session, _zip

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "src" / "static"

#: What the removed button's export held besides the per-keyword files (``summary.json``'s ``data``).
_LOG_SUMMARY_KEYS = {
    "corpus",
    "families",
    "families_provenance",
    "method",
    "overrides",
    "per_source_concentration",
    "ring_candidates",
    "stopword_candidates",
    "supergroups",
}
#: What the digest adds to it.
_DIGEST_ADDS = {"families_summary", "keywords", "keywords_digest"}
#: The two that differ ON PURPOSE, because they describe how the file was made.
_DESCRIBE_THE_FILE = {"method", "families_provenance"}

_CORPORA = {"larger": (11, 220, 1_800), "smaller": (12, 60, 400)}
#: ``name -> (corpus, window)``: the window is the real one (``None``) or a small one that the larger
#: corpus's languages EXCEED, which is the regime of a real install (``capped_languages`` non-empty) and the
#: only one in which the digest's count of what it left out can differ from the corpus's keyword total.
_CASES = {"larger": ("larger", None), "smaller": ("smaller", None), "beyond-the-window": ("larger", 60)}


def _plant_corrections(path: Path) -> None:
    """The user's own curation, so the comparison of ``overrides`` and ``supergroups`` is not two empty lists:
    a manual merge, a manual split and one super-group of two families."""
    con = sqlite3.connect(path)
    con.executemany(
        "INSERT INTO keyword_family_overrides(normalized_term, family_key, canonical_label, kind) VALUES (?,?,?,?)",
        [("term5", "term5", "Term five", "term"), ("term6", "term5", "Term five", "term"), ("term7", "term7", None, "term")],
    )
    con.execute("INSERT INTO keyword_supergroups(name) VALUES ('A theme of the user')")
    con.executemany(
        "INSERT INTO keyword_supergroup_members(supergroup_id, normalized_term) VALUES (1, ?)", [("term5",), ("term9",)]
    )
    con.commit()
    con.close()


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("kw-buttons")
    out = {}
    for name, (seed, articles, keywords) in _CORPORA.items():
        out[name] = root / f"{name}.db"
        _build(out[name], seed, articles=articles, keywords=keywords)
        _plant_corrections(out[name])
    return out


@pytest.fixture
def data_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    d = tmp_path / "diagnostics"
    d.mkdir(exist_ok=True)
    return d


def _log(db, **kw):
    """What the removed "Keyword log" button asked for: the route's own defaults, nothing passed."""
    from src.api.diagnostics.keywords import keyword_log

    kw.setdefault("digest", False)
    kw.setdefault("fmt", "zip")
    kw.setdefault("per_lang", _MAX_KEYWORDS_PER_LANG)
    kw.setdefault("page", 1)
    kw.setdefault("max_mb", None)
    return keyword_log(db=db, **kw)


def _digest(db) -> dict:
    """The call the bundle makes for ``keyword-log-digest.json`` (checked against its source below)."""
    resp = _log(db, digest=True, fmt="json")
    return json.loads(_drain_body(resp))["data"]


def _case(name, corpus, monkeypatch):
    """``(session, window)`` for a case of ``_CASES``; a small window is patched into the module the digest
    reads it from (the export takes its window from the call, the digest from the module's constant)."""
    source, window = _CASES[name]
    if window is not None:
        monkeypatch.setattr(kw_mod, "_MAX_KEYWORDS_PER_LANG", window)
    return _session(corpus[source]), (_MAX_KEYWORDS_PER_LANG if window is None else window)


def _archive(db, window: int = _MAX_KEYWORDS_PER_LANG) -> tuple[dict, list[dict]]:
    """``(summary data, every per-keyword entry)`` of the export the removed button built."""
    files = _zip(_log(db, per_lang=window))
    summary = json.loads(files["summary.json"])["data"]
    entries = [
        entry
        for name in sorted(files)
        if name.startswith("keywords/")
        for entry in json.loads(files[name])["keywords"]
    ]
    return summary, entries


def _low_memory(monkeypatch, family_rows: int = 60) -> None:
    """A machine whose memory lets the families be grouped over ``family_rows`` keywords in all."""
    monkeypatch.setattr(
        kls, "memory_plan", lambda _a: {"heap_rows": 10**9, "batch": 800, "family_rows": family_rows}
    )
    monkeypatch.setattr(kw_mod, "memory_plan", kls.memory_plan)


# --------------------------------------------------------------------------- what the digest carries


def test_the_bundle_member_is_the_call_this_evidence_makes():
    """The evidence is about ``keyword-log-digest.json``: the member must be the digest, with the
    route's own window, and nothing else."""
    bundle = (_ROOT / "src" / "api" / "diagnostics" / "bundle.py").read_text(encoding="utf-8")
    call = re.search(r'\("keyword-log-digest\.json",.*?lambda: keyword_log\((.*?)\)\),', bundle, re.S)
    assert call, "the digest member moved: re-point this evidence at the new call"
    args = re.sub(r"\s+", " ", call.group(1)).strip().rstrip(",")
    assert args == 'db=db, digest=True, fmt="json", per_lang=_MAX_KEYWORDS_PER_LANG, page=1, max_mb=None'
    # ...and the window it asks for is the one the removed button asked for: the route's own default, which
    # is also the first round of every numbered set (so the first files of "All keywords" are the log).
    from src.api.diagnostics.keywords import keyword_log

    default = inspect.signature(keyword_log).parameters["per_lang"].default
    assert default.default == _MAX_KEYWORDS_PER_LANG == kle.PARTS_ROUND_RECORDS


@pytest.mark.parametrize("name", list(_CASES))
def test_the_digest_carries_every_summary_the_keyword_log_held_unchanged(name, corpus, data_dir, monkeypatch):
    db, window = _case(name, corpus, monkeypatch)
    log, _entries = _archive(db, window)
    digest = _digest(db)
    db.close()
    # The two key sets are PINNED, so a key the export gains (or the digest loses) fails here and asks
    # for a decision instead of slipping through an "everything it had" comparison.
    assert set(log) == _LOG_SUMMARY_KEYS
    assert set(digest) == _LOG_SUMMARY_KEYS | _DIGEST_ADDS
    for key in sorted(_LOG_SUMMARY_KEYS - _DESCRIBE_THE_FILE):
        assert digest[key] == log[key], f"{key}: the digest no longer carries what the log held"
    # Not a vacuous comparison: what each summary is about is POPULATED on this corpus. (The dicts with fixed
    # keys -- corpus, per_source_concentration, stopword_candidates, ring_candidates -- are always truthy, so
    # the lists inside them are what is asserted.)
    assert log["corpus"]["keywords_total"] > 0 and log["families"]
    assert log["per_source_concentration"]["suspects"]
    for key in ("stopword_candidates", "ring_candidates"):
        assert any(v["candidates"] for v in log[key]["by_language"].values()), key
    assert [o["normalized_term"] for o in log["overrides"]] == ["term5", "term6", "term7"]
    assert log["supergroups"] == [{"name": "A theme of the user", "members": ["term5", "term9"]}]
    # The two regimes really are two: where a language exceeds the window the export names it as capped (and
    # so does the digest, being equal), where none does the list is empty.
    assert bool(log["corpus"]["capped_languages"]) is (name == "beyond-the-window")


@pytest.mark.parametrize("name", list(_CASES))
def test_the_two_descriptions_that_differ_say_how_the_file_was_made(name, corpus, data_dir, monkeypatch):
    db, window = _case(name, corpus, monkeypatch)
    log, _entries = _archive(db, window)
    digest = _digest(db)
    db.close()
    # method: the export's text, then the digest's own sentence naming the sample and the count of the rest.
    # The window clause in front says how each file was made, so it may differ (the removed button's zip had
    # the 9 MB attachment cap and says a cap may trim; the digest has none and holds every keyword of a
    # language that fits the window); everything after it is the same text.
    window_clause = re.compile(r"^All gathered keywords \((.*?); the quota is PER dominant signature language")
    log_window, digest_window = (window_clause.match(m).group(1) for m in (log["method"], digest["method"]))
    cap_clause = "; the byte cap may trim the lowest-mention entries of every language"
    if name == "beyond-the-window":
        assert digest_window == f"top {window:,}"
        assert log_window.startswith(f"top {window:,}{cap_clause}")
    else:
        assert digest_window.startswith("every keyword, the largest language holds ")
        assert log_window.startswith("no language exceeds the window, the largest holds ") and cap_clause in log_window
    rest = log["method"].split("; the quota is PER", 1)[1]
    assert digest["method"].split("; the quota is PER", 1)[1].startswith(rest)
    tail = digest["method"].split("; the quota is PER", 1)[1][len(rest) :]
    assert "DIGEST MODE" in tail and f"top {_DIGEST_SAMPLE} keywords by mentions" in tail
    assert "keywords_digest" in tail
    # families_provenance: the same measured facts, the digest adding that its list is not a sample to reason from.
    measured = ("shown", "total", "omitted", "sorted_by", "basis_per_language", "basis_keywords", "basis_is_whole_window")
    assert {k: digest["families_provenance"][k] for k in measured} == {
        k: log["families_provenance"][k] for k in measured
    }
    assert digest["families_provenance"]["sample_is_representative"] is False
    assert digest["families_provenance"]["selection_bias"]
    # Both state the memory budget they were grouped under (the value moves with the memory available,
    # so only that it is stated is pinned).
    for doc in (log, digest):
        assert isinstance(doc["families_provenance"]["basis_budget_keywords"], int)


# --------------------------------------------------------------------------- what it does not carry


@pytest.mark.parametrize("name", list(_CASES))
def test_the_per_keyword_list_is_a_labelled_top_sample_of_the_entries_the_log_held(
    name, corpus, data_dir, monkeypatch
):
    db, window = _case(name, corpus, monkeypatch)
    log_summary, entries = _archive(db, window)
    digest = _digest(db)
    db.close()
    sample, meta = digest["keywords"], digest["keywords_digest"]
    assert len(entries) > _DIGEST_SAMPLE, "the corpus must be larger than the sample for this to mean anything"
    # The label states the sample, its size, the whole and what was left out, and how it was cut.
    assert meta == {
        "sample": True,
        "shown": _DIGEST_SAMPLE,
        "total": len(entries),
        "omitted": len(entries) - _DIGEST_SAMPLE,
        "sort": "mentions desc",
    }
    assert len(sample) == _DIGEST_SAMPLE
    # The whole is what the LOG held (the window), not the corpus's keyword total: where a language exceeds
    # the window the two differ, and the label must count the first.
    corpus_total = log_summary["corpus"]["keywords_total"]
    if name == "beyond-the-window":
        assert log_summary["corpus"]["capped_languages"] and len(entries) < corpus_total
    else:
        assert not log_summary["corpus"]["capped_languages"] and len(entries) == corpus_total
    # Each is the log's own entry (same term, counts, dates, language signature), not a rewrite.
    by_key = {(e["language"], e["normalized"], e["kind"]): e for e in entries}
    assert len(by_key) == len(entries)
    for entry in sample:
        assert by_key[(entry["language"], entry["normalized"], entry["kind"])] == entry
    # ...and they are the highest by mentions: nothing left out outranks anything shown.
    shown = [e["mentions"] for e in sample]
    assert shown == sorted(shown, reverse=True)
    assert shown == sorted((e["mentions"] for e in entries), reverse=True)[:_DIGEST_SAMPLE]


def _parts_in_order(data_dir: Path, listing: dict) -> list[tuple[str, int, int, list[dict]]]:
    """``(language, slice_from, slice_to, entries)`` of every keyword member of a numbered set, in the order a
    person who saves the files in number order meets them."""
    out = []
    for f in listing["files"]:
        if f["kind"] != "part":
            continue
        with zipfile.ZipFile(data_dir / listing["set"] / f["name"]) as z:
            for member in z.namelist():
                if member.startswith("keywords/"):
                    doc = json.loads(z.read(member))
                    out.append((doc["language"], doc["slice_from"], doc["slice_to"], doc["keywords"]))
    return out


def _set_summary(data_dir: Path, listing: dict) -> dict:
    """The ``summary.json`` ``data`` a numbered set carries (in one of its files)."""
    for f in listing["files"]:
        if f["kind"] != "part":
            continue
        with zipfile.ZipFile(data_dir / listing["set"] / f["name"]) as z:
            if "summary.json" in z.namelist():
                return json.loads(z.read("summary.json"))["data"]
    raise AssertionError("the numbered set carries no summary.json")


def _per_language(parts) -> dict[str, list[dict]]:
    """The entries of ``parts`` per language, in the order the files meet them."""
    out: dict[str, list[dict]] = {}
    for lang, _from, _to, entries in parts:
        out.setdefault(lang, []).extend(entries)
    return out


def test_all_keywords_begins_with_the_entries_the_removed_button_gave(corpus, data_dir, monkeypatch):
    """The per-keyword list beyond the digest's sample is not lost with the button: the files of "All
    keywords" are numbered rank-major, round one being every language's default window, which is what
    "Keyword log (4 MB files)" built. A small window stands for the default one here (that the real round IS
    the default window is pinned in ``test_keyword_parts_route.py``, and the route's default above). The
    entries are the same; the SUMMARY is not: the first files' ``summary.json`` is built over every keyword
    of the corpus, which is why the texts send a person to the digest, where the build ran it, for the log's summary."""
    window = 40
    monkeypatch.setattr(kle, "PARTS_ROUND_RECORDS", window)
    db = _session(corpus["larger"])
    log_listing = json.loads(_log(db, fmt="parts", per_lang=window).body)
    all_listing = json.loads(_log(db, fmt="parts", per_lang=1_000_000_000, max_mb=0).body)
    db.close()
    log_parts, all_parts = _parts_in_order(data_dir, log_listing), _parts_in_order(data_dir, all_listing)
    # the removed button's set is one round: every slice starts inside the window
    assert log_parts and all(f < window and t <= window for _l, f, t, _e in log_parts)
    # ...All keywords is several: the files meet round one first (in NUMBER order, not re-sorted here), and the
    # set goes on beyond it
    rounds = [f // window for _l, f, _t, _e in all_parts]
    assert rounds == sorted(rounds), "a record of round two is met before the last of round one"
    assert max(rounds) >= 1, "the all-keywords set must go beyond the window"
    round_one = [part for part in all_parts if part[1] < window]
    log_set, first_round = _per_language(log_parts), _per_language(round_one)
    assert set(log_set) == set(first_round)
    for lang, entries in log_set.items():
        assert first_round[lang][: len(entries)] == entries, f"{lang}: the first files of All keywords differ"
    # ...and the SUMMARY is the part that is not the same, as the docstring says: the window's set cut the
    # languages that exceed it and says so, the all-keywords set cut none and says that it holds every
    # keyword (so its summary is not read as the window's).
    window_summary, all_summary = _set_summary(data_dir, log_listing), _set_summary(data_dir, all_listing)
    assert window_summary["corpus"]["capped_languages"], "the window must cut a language for this to mean anything"
    assert window_summary["corpus"]["keywords_exported"] < window_summary["corpus"]["keywords_total"]
    assert f"top {window}" in window_summary["method"]
    assert all_summary["corpus"]["capped_languages"] == []
    assert all_summary["corpus"]["keywords_exported"] == all_summary["corpus"]["keywords_total"]
    assert all_summary["corpus"]["keywords_total"] == window_summary["corpus"]["keywords_total"]
    assert "(every keyword, the largest language holds " in all_summary["method"]
    assert f"top {_MAX_KEYWORDS_PER_LANG:,}" not in all_summary["method"]


def test_a_later_page_names_the_ranks_it_holds_not_a_top(corpus, data_dir):
    """Page two of a window holds ranks 41 to 80 of each language: a summary that said "top 40" over it
    would describe the first page's files."""
    db = _session(corpus["larger"])
    files = _zip(_log(db, per_lang=40, page=2, max_mb=0))
    summary = json.loads(files["summary.json"])["data"]
    assert summary["corpus"]["exported_per_language"], "page two must hold something for this to mean anything"
    assert "(ranks 41 to 80, page 2; the quota is PER dominant signature language" in summary["method"]
    assert "top 40" not in summary["method"] and "byte cap" not in summary["method"], "max_mb=0 is no cap"
    # ...and under the 9 MB default cap the same page says the cap may trim it
    files = _zip(_log(db, per_lang=40, page=2))
    assert "(ranks 41 to 80, page 2; the byte cap may trim" in json.loads(files["summary.json"])["data"]["method"]
    db.close()


@pytest.mark.parametrize("fmt", ["zip", "parts"])
def test_a_summary_does_not_claim_every_keyword_where_the_byte_cap_trimmed_the_files(fmt, corpus, data_dir):
    """No language reaches the window, so the window cuts nothing, but the attachment cap (the 9 MB default
    of a zip or parts build, made small here) then drops the lowest-mention entries of every language AFTER the
    summary's text is fixed: that text must state the window and the cap, not "every keyword" over files that
    hold fewer (the files and the manifest count what was omitted)."""
    db = _session(corpus["larger"])
    resp = _log(db, fmt=fmt, per_lang=1_000_000, max_mb=0.03)
    if fmt == "zip":
        files = _zip(resp)
        summary = json.loads(files["summary.json"])["data"]
        held = sum(len(json.loads(files[n])["keywords"]) for n in files if n.startswith("keywords/"))
    else:
        listing = json.loads(resp.body)
        summary = _set_summary(data_dir, listing)
        held = sum(len(e) for _l, _f, _t, e in _parts_in_order(data_dir, listing))
    db.close()
    total = summary["corpus"]["keywords_total"]
    assert not summary["corpus"]["capped_languages"], "the window must cut nothing for this to be the byte cap's doing"
    assert held < total, "the cap must have trimmed for this to mean anything"
    assert "every keyword" not in summary["method"]
    assert "no language exceeds the window" in summary["method"] and "byte cap may trim" in summary["method"]
    assert "keywords_omitted_to_fit in the export manifest" in summary["method"]


# --------------------------------------------------------------------------- low memory (R130 = 36a)


@pytest.mark.parametrize("name", list(_CORPORA))
def test_on_a_computer_short_of_memory_the_summary_says_it_covers_only_the_first_keywords(
    name, corpus, data_dir, monkeypatch
):
    db = _session(corpus[name])
    whole = _digest(db)["families_provenance"]
    assert whole["basis_is_whole_window"] is True and whole["basis_per_language"] is None
    _low_memory(monkeypatch)
    log, _entries = _archive(db)
    digest = _digest(db)
    db.close()
    prov, summary = digest["families_provenance"], digest["families_summary"]
    # The digest says it is partial, over how many keywords of each language, and under what budget...
    assert prov["basis_is_whole_window"] is False
    assert prov["basis_per_language"] >= 1
    assert prov["basis_keywords"] <= prov["basis_budget_keywords"] == 60
    assert f"first {prov['basis_per_language']} keywords of each language's window" in prov["note"]
    # ...the summary repeats it where the counts are read, and says what a keyword beyond that is...
    assert summary["basis_is_whole_window"] is False
    assert summary["basis_per_language"] == prov["basis_per_language"]
    assert "a keyword beyond that prefix is in no family" in summary["method"]
    # ...and points at the link that covers the rest.
    assert "'All keywords'" in prov["selection_bias"]
    # The export it replaces was partial in the same way: no loss against the removed button.
    for key in ("basis_is_whole_window", "basis_per_language", "basis_keywords", "basis_budget_keywords"):
        assert log["families_provenance"][key] == prov[key]
    assert log["families"] == digest["families"]


# --------------------------------------------------------------------------- what stays, what goes


def test_the_panel_keeps_one_text_link_and_the_routes_stay():
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    for gone in ("Keyword log (4 MB files)", "Last keyword files, again", "downloadKeywordParts(this, 'default')",
                 "downloadKeywordParts(this, 'again')"):
        assert gone not in html, gone
    assert re.search(
        r'<button type="button" class="linkish" data-on-click="downloadKeywordParts\(this, \'all\'\)"[^>]*>All keywords</button>',
        html,
    )
    assert html.count("downloadKeywordParts(") == 1, "the link is the only control that calls the routine"
    # The Diagnostics button's own hover text still tells where the full dump is.
    button = re.search(r'<button id="all-diag-btn"[^>]*title="([^"]*)"', html)
    assert button and "keyword digest" in button.group(1) and "'All keywords'" in button.group(1)
    # ...and says the digest is there WHEN THE BUILD RAN IT (the evidence calls the route; the build's Quick
    # budget and its memory gate sit in front of it), never that it always is.
    assert "when the build ran it" in button.group(1)
    # The three ways the build leaves it out (the Quick time, its own time limit, the memory) are the three the
    # hover names; a fourth reason would have to be added here and in the 12 locales together.
    assert "did not fit the Quick time, its own time limit or the memory" in button.group(1)
    # The routes the buttons called stay (R123: "the routes stay"), and so does the routine and its whitelist entry.
    for module in ("keyword_parts", "keywords"):  # importing a module registers its routes
        importlib.import_module(f"src.api.diagnostics.{module}")
    from src.api.diagnostics._base import router

    paths = {getattr(r, "path", "") for r in router.routes}
    assert any(p.endswith("/keywords") for p in paths)
    assert any(p.endswith("/keywords/parts/latest") for p in paths)
    js = (_STATIC / "app-diagnostics.js").read_text(encoding="utf-8")
    assert "/api/diagnostics/keywords?format=parts" in js and "/api/diagnostics/keywords/parts/latest" in js
    assert '"downloadKeywordParts"' in (_STATIC / "oo-on.js").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- the keys nothing renders any more

#: The beginnings of the locale keys of the keyword-log buttons and hovers (this PR's two labels and their
#: hover texts, and the same buttons' earlier 1 MB wordings, "Download ... (.zip/.json)" labels and hover
#: texts that earlier Diagnostics PRs left behind), the "All diagnostics" labels and the status lines that
#: named them, the 1 MB hover of the All keywords link and the parts-ready line with the old size slot, plus
#: two Diagnostics hover texts no control carries since the button is one. Each was grepped across ``src``
#: before it went: no source renders it.
_ORPHAN_KEY_PREFIXES = (
    "All diagnostics (1 MB files)",
    "All diagnostics, again (last build, 1 MB files)",
    "All keywords (.zip)",
    "All keywords (1 MB files)",
    "Download ALL keywords (.zip)",
    "Download keyword log (.json)",
    "Download keyword log (.zip)",
    "Every diagnostics log in one archive — one click instead of nine.",
    "Every diagnostics log, built as a BACKGROUND job",
    "Every keyword in the corpus (not just the top 5000 per language), as numbered .zip files of at most 1 MB each",
    "Keyword log (1 MB files)",
    "Keyword log (4 MB files)",
    "Last keyword files, again",
    "No archive to split yet \u2014 build one with the All diagnostics button first.",
    "The archive is ready. Press \u201cAll diagnostics, again\u201d to save it as numbered files.",
    "{n} files of at most 1 MB each are ready",
    "Saves the diagnostics archive built last as numbered .zip files of at most 1 MB each, again",
    "Saves the numbered keyword files built last time again",
    "The top 5,000 keywords per language, as numbered .zip files of at most 1 MB each (about ten files",
    "The top 5,000 keywords per language, as numbered .zip files of at most 4 MB each, five to a click",
)


def test_the_locale_keys_of_the_removed_buttons_are_gone_and_nothing_renders_them():
    """Removing a control removes its keys: a key left in the 12 locales is a reviewed translation nothing
    shows (and, for the old Diagnostics hover, an unconditional claim about the digest that the live text
    no longer makes). The precedent is ``test_clickthrough_b14_fixes.py``'s orphan-key test."""
    locales = sorted((_STATIC / "locales").glob("*.json"))
    assert len(locales) == 12
    for path in locales:
        keys = json.loads(path.read_text(encoding="utf-8")).keys()
        for prefix in _ORPHAN_KEY_PREFIXES:
            left = [k for k in keys if k.startswith(prefix)]
            assert not left, f"{path.stem}.json still carries the orphan key {left[0][:80]!r}"
    for path in [*_STATIC.rglob("*.js"), *_STATIC.rglob("*.html")]:
        src = path.read_text(encoding="utf-8")
        for prefix in _ORPHAN_KEY_PREFIXES:
            assert prefix not in src, f"{path.relative_to(_STATIC)} renders {prefix!r}, so it was not an orphan"
