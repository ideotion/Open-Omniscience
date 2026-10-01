#!/usr/bin/env python3
"""Turn a diagnostics keyword log into a reviewed stoplist batch (R111). OFFLINE, maintainer side.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R111 (2026-09-30): the stoplist is OURS to grow and users are never asked about it. We
curate batches from the keyword logs in the diagnostics a maintainer sends, and ship them in
``configs/stopwords_extra/<lang>.yml`` with each app update. This tool is the part that keeps
that safe. It runs in a checkout, never inside the app, never touches the network or a database, and
never edits a tracked file unless you say ``--apply``. (Importing the app's extraction module
makes the app's logging create the gitignored ``audit/`` directory, which is the one side effect.)

    python scripts/stopword_batch.py LOG --language en                 # the evidence table
    python scripts/stopword_batch.py LOG --language en --words w.txt   # check a decided list
    python scripts/stopword_batch.py LOG --language en --words w.txt --verdicts v.tsv \\
        --apply --batch-id en-2026-10                                  # write the batch

``LOG`` is the keyword-log zip (or the single JSON) the diagnostics export produces. ``w.txt``
is the decided list, one word per line (``#`` comments allowed): the words the curation
accepted. Without ``--words`` the tool prints candidates worth reading, never a decision.

THE VERDICT GATE (R98/R111: only a HIGH-CONFIDENCE "N" is a stoplist candidate; the triage's two
runs of Sonnet agreed on every such row). ``--apply`` REQUIRES ``--verdicts FILE``, the triage
thread's decision rows as tab-separated text, one per line, ``#`` comments allowed::

    language <TAB> word <TAB> verdict <TAB> code <TAB> confidence <TAB> model [<TAB> flags]

with ``verdict`` N (or ``junk``), ``confidence`` H, and ``flags`` a comma list that may hold
``unstable`` (the triage converter sets it on a verdict that did not reproduce between runs or that
sits on an open rubric boundary) or ``single_reader``; the layout is the triage thread's
decision-file format. REPRODUCIBILITY IS THE DECISION FILE'S JOB: the tool trusts the ``unstable``
flag the converter sets and counts no runs itself. Only
``single_reader`` is an accepted flag; ANY OTHER flag blocks the word (an unknown flag is a
reading this tool does not understand, and it must not pass), and a line the reader cannot parse
(no tab, a language column that is not a code, a row of another language with no verdict in its
third column) stops the whole file. A word with no verdict row for the language, a verdict other than N, a confidence other than H, or a blocking flag is refused, and the batch comment records the verdict file's hash and the models named in it.
Without ``--verdicts`` the tool only REPORTS, says so, and its table is not a decision.

WHY THE REFUSALS EXIST. ``configs/stopwords_extra`` is a LANGUAGE-AGNOSTIC union
(``global_stopwords()``): a word added for English hides that spelling in EVERY language. So a
word is refused, with the reason, when adding it would hide signal:

* ``ring_member``      a member of a shipped translation ring (R102), in any language: signal, not grammar;
* ``platform_name``    facebook, twitter and kin COUNT as keywords (R104); the keep-file MUST load, and
                       empty or missing it stops the tool (a guard that fails open is not one);
* ``not_in_log``       the log holds no article for it in this language: nothing was weighed;
* ``no_verdict`` / ``not_junk`` / ``not_high_confidence`` / ``unstable`` / ``unknown_flag``   the verdict gate above;
* ``de_elided``        extraction strips ``d'`` / ``l'`` / ``qu'`` before the stop check, so an entry
                       for ``d'una`` could never match;
* ``content_elsewhere`` another language stores it as a live keyword (evidence from THIS log);
* ``also_an_entity``   the log holds it as a person / place / organisation, which the hide set
                       (a whole-normalized-term match) would hide too;
* ``single_source``    one source holds most of its mentions: that is that source's boilerplate,
                       which a global stopword must not hide (needs ``top_source_share``, which
                       the diagnostics gains in a later update; absent = not judged, and said so);
* ``already_hidden``   nothing to add;
* ``phrase``           multi-word entries are refused until the hide path is verified for them.

A maintainer can override ``content_elsewhere`` and ``also_an_entity`` for a word with
``--allow WORD`` (recorded in the batch comment), and lift ``platform_name`` for the names the
keep-file lists as AMBIGUOUS (signal, threads, x: also ordinary words); ``ring_member``, the
verdict gate and a firm platform name have no override. HOW THIS DIFFERS FROM ``scripts/analyze_keyword_log.py``. That script reads one log and PROPOSES
several kinds of optimisation (stopword candidates, mis-tagged entities, ring candidates,
families) for a human to read; it edits nothing and decides nothing. This tool imports its log
loading and candidate reading (``load_log``, ``stopword_candidates``) and adds the one step it
does not have: checking a DECIDED word list against the evidence and the refusals above, and,
only with ``--apply``, writing the batch into ``configs/stopwords_extra``.

After ``--apply``, declare the added words in
``tests/test_analytics_extract.py::added_since_migration`` (the tool prints the exact lines) and
add a section to ``configs/stopwords_extra/PROVENANCE.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
EXTRA_DIR = ROOT / "configs" / "stopwords_extra"
KEEP_FILE = ROOT / "configs" / "stopword_batches" / "_keep_platform_names.yml"

# A live keyword in another language must carry at least this many articles to count as
# content there; one or two stray rows are extraction noise, not usage.
ELSEWHERE_MIN_ARTICLES = 3
# A source holding at least this share of a term's mentions makes it that source's boilerplate.
SINGLE_SOURCE_SHARE = 0.5
# A language code names a file in configs/stopwords_extra, so it may never carry a path. The
# 16-character ceiling protects only that: it is longer than any BCP 47 language-plus-script tag
# the app stores, and short enough that a code can never be mistaken for a sentence.
LANGUAGE_CODE = re.compile(r"[a-z][a-z0-9_-]{0,15}")
# Windows treats these as devices whatever the extension, so ``con.yml`` is not a file there.
RESERVED_NAMES = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)),
                            *(f"lpt{i}" for i in range(10))})
# The first column of a verdict row: a language code as the diagnostics logs write it (two or three
# letters, an optional script or region part), or the "?" / unknown bucket. A word in this column
# (its language column missing) must stop the file, not be read as a row for another language.
VERDICT_LANGUAGE = re.compile(r"[a-z]{2,3}(?:[-_][a-z0-9]{2,8})?|\?|unknown")
# What the third column of any row must hold (the triage converter writes K, N, W or U).
VERDICT_TOKENS = frozenset({"N", "K", "W", "U", "JUNK"})
# The only verdict flag that does not block a word. Anything else, spelt however, is a reading
# the tool does not understand, so it blocks: a flag list that lets unknown flags through would
# batch the very rows the triage ruled out.
ACCEPTED_FLAGS = frozenset({"single_reader"})
# A batch id lands in a YAML comment; it must never be able to open a new line.
BATCH_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
# How many other-language / entity rows the table prints before saying "and N more": two lines of
# evidence are enough to read a refusal, and the full rows are in the --json report.
SHOWN_ROWS = 4
HIGH = "H"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _straight(term: object) -> str:
    """NFC with the curly apostrophe written straight: the loader derives the curly spelling of
    every listed contraction itself (``extract._EXTRA_STOPWORDS``) and never the reverse, so a
    file holds the straight form and a curly one in a words file or a log means the same word."""
    return unicodedata.normalize("NFC", str(term or "")).replace("\u2019", "'")


def norm(term: object) -> str:
    """The app's KEY for a term (whitespace collapsed, casefolded): how the log, rings and
    platform names are matched. The curly apostrophe is folded to the straight one so a log row
    spelt either way meets the same word."""
    return " ".join(_straight(term).split()).casefold()


def spelling(term: object) -> str:
    """The form a stoplist file holds and extraction tests: ``.lower()``, not casefold.

    Extraction compares each ``.lower()`` token with the stop set, so a Greek word with a final
    sigma (casefold turns ς into σ) or a German one with ß must be written, and recognised as
    already listed, in this form."""
    return " ".join(_straight(term).split()).lower()


def _read_keep(path: Path | None = None) -> tuple[frozenset[str], frozenset[str]]:
    """(firm names, ambiguous names) from the keep-file. A missing, unreadable, malformed or empty
    file STOPS the tool: an empty guard would let ``facebook`` through with no warning."""
    path = path or KEEP_FILE
    try:
        data = yaml.safe_load(path.read_text("utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SystemExit(f"the platform keep-file {path} cannot be read ({exc}); refusing to run without it") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"the platform keep-file {path} is not a mapping; refusing to run without it")
    lists: list[frozenset[str]] = []
    for key in ("platform_names", "ambiguous_platform_names"):
        if key not in data:
            raise SystemExit(f"the platform keep-file {path} has no {key} key (it may be an empty list); "
                             "refusing to run: a missing list would silently let its names through")
        value = data[key]
        if not isinstance(value, list) or not all(isinstance(n, str) for n in value):
            # a bare string would be walked letter by letter, and the guard would pass on single letters
            raise SystemExit(f"the platform keep-file {path}: {key} must be a list of names; refusing to run")
        lists.append(frozenset(norm(n) for n in value if norm(n)))
    firm, ambiguous = lists
    if not firm:
        raise SystemExit(f"the platform keep-file {path} lists no platform names; refusing to run without them")
    return firm, ambiguous


def platform_names(path: Path | None = None) -> frozenset[str]:
    """The firm platform names: refused with no override."""
    return _read_keep(path)[0]


def ambiguous_platform_names(path: Path | None = None) -> frozenset[str]:
    """Platform names that are also ordinary words: refused, but ``--allow`` lifts the refusal."""
    return _read_keep(path)[1]


def read_words(path: Path) -> list[str]:
    words: list[str] = []
    for line in re.split(r"\r\n|\r|\n", path.read_text("utf-8").replace("\ufeff", "")):
        # A comment starts at a line-initial or space-preceded "#"; "c#" is a word.
        line = re.sub(r"(^|\s)#.*$", "", line).strip()
        w = spelling(line)  # also collapses inner whitespace, so "read<TAB>more" is a phrase
        if w and w not in words:
            words.append(w)
    return words


def log_keywords(doc: dict) -> list[dict]:
    """The log's keyword rows, read the way the analyzer reads them (an envelope with ``data``, or
    a flat document). Zero rows STOPS the tool: with none, every guard that weighs evidence is off."""
    data = doc.get("data", doc)
    rows = data.get("keywords") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise SystemExit("the log holds no keyword rows; refusing to judge words without evidence")
    return rows


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def read_verdicts(path: Path, lang: str, skipped: Counter | None = None) -> dict[str, dict[str, Any]]:
    """The triage decisions for ``lang``, keyed by spelling. Several rows for one word merge to the
    STRICTEST reading (any row that is not a high-confidence N, or carries a flag the tool does not
    accept, spoils it), whatever their order. A line the reader cannot parse stops the WHOLE file: a
    row skipped in silence could be the one that dissents."""
    out: dict[str, dict[str, Any]] = {}
    # Only CR, LF and CRLF end a row: str.splitlines() would also cut at U+2028, U+0085 and the like,
    # leaving a fragment of a row that could pass for another language's.
    for number, line in enumerate(re.split(r"\r\n|\r|\n", path.read_text("utf-8")), 1):
        # A BOM can sit mid-file too (two exports joined with cat). Leading SPACES are not a column,
        # but a leading TAB is an empty first column, which the language check below refuses.
        line = line.replace("\ufeff", "").lstrip(" ")
        if not line or line.startswith("#"):
            continue
        # Split BEFORE trimming: stripping would eat the trailing tabs of a row whose last columns are
        # empty ("en rose K" + 3 tabs), and a row that goes missing loses its vote in the merge.
        cols = [c.strip() for c in line.split("\t")]
        if [c.lower() for c in cols[:2]] == ["language", "word"]:
            continue  # the header row
        if len(cols) < 2 or not VERDICT_LANGUAGE.fullmatch(cols[0].lower()):
            raise SystemExit(f"{path}:{number}: not a verdict row (tab-separated, the first column a language "
                             f"code); refusing to skip it, a skipped row could be the dissenting one: {line[:60]!r}")
        if cols[0].lower() != lang:
            # Skipped unread, but it must still LOOK like a row: a row of THIS language that lost its
            # language column shifts left, and its word ("zq", "is") then passes for a language code.
            if len(cols) < 3 or cols[2].upper() not in VERDICT_TOKENS:
                raise SystemExit(f"{path}:{number}: a row for {cols[0]!r} has no verdict in its third column "
                                 f"(its language column may be missing); refusing to skip it: {line[:60]!r}")
            if skipped is not None:
                skipped[cols[0].lower()] += 1
            continue
        if not cols[1] or len(cols) < 3 or not cols[2]:
            raise SystemExit(f"{path}:{number}: a verdict row for {lang!r} with no word or no verdict column; "
                             "refusing to skip it")
        cols += [""] * (7 - len(cols))  # a short row is read as having empty columns: never high, never N
        word = spelling(cols[1])
        verdict = cols[2].upper()
        flags = {f.strip().lower() for f in cols[6].split(",") if f.strip()}
        if any(c for c in cols[7:]):  # a displaced flags column: unreadable, so blocking
            flags.add("extra_columns")
        row = out.setdefault(word, {"junk": True, "high": True, "flags": set(), "single_reader": False,
                                    "models": set()})
        row["junk"] &= verdict in ("N", "JUNK")
        row["high"] &= cols[4].upper() == HIGH and bool(cols[5])  # the converter always names the model
        # a flag in the MODEL column (that column omitted, the flags shifted left) is still a flag
        flags |= {cols[5].lower()} & {"unstable", "single_reader"}
        row["flags"] |= flags
        row["single_reader"] |= "single_reader" in flags
        if cols[5] and cols[5].lower() not in {"unstable", "single_reader"}:
            row["models"].add(cols[5])
        if skipped is not None:
            skipped["\0read"] += 1
    if not out:
        raise SystemExit(f"{path} holds no verdict rows for language {lang!r}")
    return out


def blocking_flags(v: dict[str, Any]) -> set[str]:
    """The flags on a word's verdict that keep it out: every one the tool does not accept."""
    return set(v["flags"]) - ACCEPTED_FLAGS


def index_log(keywords: list[dict]) -> dict[str, list[dict]]:
    """Every log row by normalized term."""
    by_term: dict[str, list[dict]] = defaultdict(list)
    for k in keywords:
        n = norm(k.get("normalized") or k.get("term"))
        if n:
            by_term[n].append(k)
    return by_term


def _articles(k: dict) -> int:
    return int(k.get("articles") or 0)


def _de_elided(word: str) -> bool:
    """A token extraction strips (``d'una`` -> ``una``) before the stop check: an entry for it
    could never match, so adding it would do nothing."""
    from src.analytics.extract import _deelide

    return _deelide(word) != word


def _is_listed(word: str, hidden_in_lang: frozenset[str]) -> bool:
    """Whether extraction already drops ``word``. The loader gives only the extras a curly copy,
    so a contraction listed in a vendored list with a straight apostrophe still lets the curly
    token through: it counts as listed only when both forms are."""
    if word not in hidden_in_lang:
        return False
    return "'" not in word or word.replace("'", "\u2019") in hidden_in_lang


def evidence(word: str, lang: str, rows: list[dict], hidden_in_lang: frozenset[str]) -> dict[str, Any]:
    """What the log says about one spelling, with nothing decided."""
    own = [k for k in rows if (k.get("language") or "?") == lang and k.get("kind") == "term"]
    elsewhere = sorted(
        (
            {"language": k.get("language") or "?", "articles": _articles(k)}
            for k in rows
            if (k.get("language") or "?") != lang
            and k.get("kind") == "term"
            and not k.get("hidden")
            and _articles(k) >= ELSEWHERE_MIN_ARTICLES
        ),
        key=lambda u: (-int(u["articles"]), str(u["language"])),
    )
    entities = [
        {"language": k.get("language") or "?", "kind": k.get("kind"), "articles": _articles(k)}
        for k in rows
        if k.get("kind") not in (None, "term") and _articles(k) >= ELSEWHERE_MIN_ARTICLES
    ]
    spreads = [k for k in own if k.get("top_source_share") is not None]
    return {
        "term": word,
        "articles": sum(_articles(k) for k in own),
        "mentions": sum(int(k.get("mentions") or 0) for k in own),
        "sources": max((int(k["sources"]) for k in own if k.get("sources") is not None), default=None),
        "top_source_share": max((float(k["top_source_share"]) for k in spreads), default=None),
        "content_elsewhere": elsewhere,
        "entities": entities,
        "de_elided": _de_elided(spelling(word)),
        "already_hidden": not _de_elided(spelling(word)) and _is_listed(spelling(word), hidden_in_lang),
    }


def verdict_refusals(word: str, verdicts: dict[str, dict[str, Any]]) -> list[str]:
    """The verdict gate: only a high-confidence, reproducible N is a stoplist candidate."""
    v = verdicts.get(spelling(word))
    if v is None:
        return ["no_verdict"]
    out: list[str] = []
    if not v["junk"]:
        out.append("not_junk")
    if not v["high"]:
        out.append("not_high_confidence")
    blocked = blocking_flags(v)
    if "unstable" in blocked:
        out.append("unstable")
    if blocked - {"unstable"}:
        out.append("unknown_flag")
    return out


def refusals(word: str, ev: dict[str, Any], *, ring_words: frozenset[str], platforms: frozenset[str],
             allow: frozenset[str], ambiguous: frozenset[str] = frozenset(),
             verdicts: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Why a word may not be added, as stable keys. Empty = addable. ``verdicts`` None means no
    verdict file was given (report mode); ``--apply`` never runs without one."""
    out: list[str] = []
    if " " in word:
        out.append("phrase")
    if ev["already_hidden"]:
        out.append("already_hidden")
    if ev.get("de_elided"):
        out.append("de_elided")
    key = norm(word)
    if key in platforms or (key in ambiguous and key not in allow):
        out.append("platform_name")
    if key in ring_words:
        out.append("ring_member")
    if not ev["articles"]:
        out.append("not_in_log")
    if ev["content_elsewhere"] and key not in allow:
        out.append("content_elsewhere")
    if ev["entities"] and key not in allow:
        out.append("also_an_entity")
    if ev["top_source_share"] is not None and ev["top_source_share"] >= SINGLE_SOURCE_SHARE:
        out.append("single_source")
    if verdicts is not None:
        out.extend(verdict_refusals(word, verdicts))
    return out


def trimmed_log_notice(path: Path) -> str | None:
    """Say so when the zip was trimmed to fit its size cap or paged: absence from a trimmed log
    is not evidence that a word is absent from the corpus (the lowest-mention keywords go first)."""
    import zipfile

    try:
        if not zipfile.is_zipfile(path):
            return None
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read("manifest.json"))
    except (OSError, KeyError, ValueError):
        return None
    omitted = int(manifest.get("keywords_omitted_to_fit") or 0)
    paged = bool(manifest.get("has_more"))
    # The LAST page of a paged export holds only the lowest-ranked keywords, so it is partial too.
    later_page = int(manifest.get("page") or 1) > 1 or int(manifest.get("pages_total") or 1) > 1
    if not (omitted or paged or later_page):
        return None
    return (
        f"NOTICE: this log is incomplete ({omitted} keywords omitted to fit its size cap"
        f"{'; this is one page of a paged export' if (paged or later_page) else ''}). \"Not found elsewhere / not an entity\" below only "
        "means not found IN WHAT THE LOG HOLDS; read the rows with that in mind."
    )


def app_context(lang: str) -> tuple[frozenset[str], frozenset[str]]:
    """(what extraction already drops in ``lang``, every single-word member of a SHIPPED ring).

    The second set is every ring member in every language, not only the ones the union already
    hides (``_ring_member_exemptions``): a word not hidden today is exactly what a batch adds, and
    a translated concept is signal (R102) whichever language's file would hide it.
    """
    from src.analytics.equivalence import shipped_rings
    from src.analytics.extract import _stopset

    ring = {
        norm(term)
        for r in shipped_rings()
        for _lang, term in r.members
        if term and " " not in term
    }
    return _stopset(lang), frozenset(ring)


def candidates_to_read(log_doc: dict, lang: str, existing: frozenset[str]) -> list[str]:
    """The spellings worth reading for a language: surfaced by the analyzer, net-new only."""
    import analyze_keyword_log as akl

    kws = log_keywords(log_doc)
    by = akl.stopword_candidates(kws, set(existing), 0)
    # ``term`` keeps the surface form; the casefold key cannot give back a final sigma or an eszett.
    return [c["term"] for c in by.get(lang, []) if c["bucket"] == "high_confidence"] + [
        c["term"] for c in by.get(lang, []) if c["bucket"] != "high_confidence"
    ]


def yaml_scalar(term: str) -> str:
    """A list item that survives YAML: quote anything it would read as a bool, number or null."""
    dumped = yaml.safe_dump(term, allow_unicode=True, default_flow_style=True, width=float("inf")).strip()
    return dumped.removesuffix("...").strip()


def _symlink_on_path(path: Path) -> bool:
    """A symlink on the file or any directory above it, up to the checkout (outside it, up to the
    file's own directory: a system path such as /tmp may legitimately be a link)."""
    stop = ROOT if path.is_relative_to(ROOT) else path.parent
    for p in (path, *path.parents):
        if p.is_symlink():
            return True
        if p == stop:
            break
    return False


def check_language(lang: str) -> str:
    """A language code names a file in configs/stopwords_extra and nothing else."""
    if not LANGUAGE_CODE.fullmatch(lang) or lang in RESERVED_NAMES:
        raise SystemExit(f"{lang!r} is not a language code (a letter, then letters, digits, - or _; "
                         "no device names); refusing to build a path from it")
    return lang


def append_batch(lang: str, words: list[str], batch_id: str, allowed: list[str], source: str) -> Path:
    """Append ``words`` to ``configs/stopwords_extra/<lang>.yml`` and prove the file still loads.

    The comment is deterministic (no date, no file name): the same decision gives the same bytes
    on any day. ``batch_id`` carries the date, and ``source`` is hashes and model names only."""
    check_language(lang)
    if not BATCH_ID.fullmatch(batch_id):
        raise SystemExit(f"--batch-id {batch_id!r} may hold only letters, digits, . _ - (1 to 64): it "
                         "is written into a YAML comment and must not be able to open a new line")
    # Letters and their combining marks survive in any script; a newline or line separator never does.
    source = "".join(c if c.isalnum() or c in "_ .;:,-" or unicodedata.category(c).startswith("M") else "_"
                     for c in source)
    path = EXTRA_DIR / f"{lang}.yml"
    if _symlink_on_path(path) or path.resolve().parent != EXTRA_DIR.resolve():
        raise SystemExit(f"{path} is a symlink, sits behind one, or leaves {EXTRA_DIR}; refusing to write through it")
    if path.exists() and path.stat().st_nlink > 1:
        raise SystemExit(f"{path} has several hard links; refusing to append through it")
    new_file = not path.exists()
    before = "stopwords:\n" if new_file else path.read_text("utf-8")
    try:
        doc = yaml.safe_load(before) or {}
    except yaml.YAMLError as exc:
        raise SystemExit(f"{path} does not parse as YAML ({exc}); refusing to edit it") from exc
    listed = doc.get("stopwords")
    # A language with no file yet starts from an empty list; an existing file must already hold one.
    if not (isinstance(listed, list) or (new_file and listed is None)):
        raise SystemExit(f"{path} has no 'stopwords:' list; refusing to edit it")
    prior = [str(x) for x in (listed or [])]
    lines = [f"  # batch {batch_id} ({source})"]
    if allowed:
        lines.append(f"  # maintainer overrides (content elsewhere / entity / ambiguous platform name reviewed): "
                     f"{', '.join(sorted(allowed))}")
    for w in sorted(words):
        lines.append(f"  - {yaml_scalar(w)}")
    after = before.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    try:
        loaded = yaml.safe_load(after)["stopwords"]
    except yaml.YAMLError as exc:
        raise SystemExit(
            f"{path}: appending a 2-space block list item does not parse here ({exc}) -- the file "
            "uses another layout (unindented or flow list); edit it by hand. Nothing written."
        ) from exc
    if [str(x) for x in loaded] != prior + sorted(words):
        raise SystemExit(f"{path}: the list after the append is not the old list plus exactly the "
                         "decided words; nothing written")
    path.write_text(after, "utf-8")
    return path


def _more(items: list[str], shown: int = SHOWN_ROWS) -> str:
    return ", ".join(items[:shown]) + (f" and {len(items) - shown} more" if len(items) > shown else "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", type=Path, help="keyword-log zip or JSON from the diagnostics export")
    ap.add_argument("--language", required=True, help="the language whose list the words go into (e.g. en)")
    ap.add_argument("--words", type=Path, help="the decided words, one per line")
    ap.add_argument("--verdicts", type=Path, help="the triage decision rows (required with --apply)")
    ap.add_argument("--allow", action="append", default=[],
                    help="override content_elsewhere / also_an_entity / an ambiguous platform name for a word")
    ap.add_argument("--apply", action="store_true", help="append the addable words to the language's file")
    ap.add_argument("--batch-id", help="the batch's id, e.g. en-2026-10 (required with --apply)")
    ap.add_argument("--json", type=Path,
                    help="also write the full evidence report here: a NEW .json file, outside configs/, never the input log")
    args = ap.parse_args(argv)

    import analyze_keyword_log as akl

    lang = check_language(args.language.strip().lower())
    if args.apply and not (args.words and args.batch_id and args.verdicts):
        raise SystemExit("--apply needs --words, --batch-id and --verdicts (the triage decision rows)")
    if args.json is not None:
        target = args.json.resolve()
        if (target.suffix != ".json" or args.json.is_symlink()
                or target.is_relative_to((ROOT / "configs").resolve())):
            raise SystemExit("--json must name a .json file outside configs/ and not through a symlink")
        inputs = {args.log.resolve(), *(p.resolve() for p in (args.verdicts, args.words) if p)}
        if target in inputs or (target.exists() and (target.is_relative_to(ROOT) or any(
                p.exists() and target.samefile(p) for p in (args.log, args.verdicts, args.words) if p))):
            raise SystemExit("--json would overwrite an input file (the log, the verdicts or the words) or an existing file in the checkout "
                             "(a tracked file is one); name a new file or one outside the checkout")
    doc = akl.load_log(args.log)
    keywords = log_keywords(doc)
    index = index_log(keywords)
    hidden, ring = app_context(lang)
    firm, ambiguous = _read_keep()
    seen: Counter = Counter()
    verdicts = read_verdicts(args.verdicts, lang, seen) if args.verdicts else None
    if verdicts is not None:
        rows_read = seen.pop("\0read")
        others = ", ".join(f"{k} {v}" for k, v in seen.most_common(6))
        print(f"verdicts: read {rows_read} rows for {lang}; skipped {sum(seen.values())} rows for "
              f"{len(seen)} other languages ({others}{', ...' if len(seen) > 6 else ''}).")
    note = trimmed_log_notice(args.log)
    if note:
        print(note)
    if verdicts is None:
        print("NOTICE: no --verdicts file: this table is evidence, not a decision, and --apply will refuse.")
    allow = frozenset(norm(a) for a in args.allow)

    if args.words:
        words = read_words(args.words)
    elif verdicts is not None:
        words = sorted(w for w, v in verdicts.items() if v["junk"] and v["high"] and not blocking_flags(v))
    else:
        words = [spelling(w) for w in candidates_to_read(doc, lang, hidden)]
    rows = []
    for w in words:
        ev = evidence(w, lang, index.get(norm(w), []), hidden)
        ev["refused"] = refusals(w, ev, ring_words=ring, platforms=firm, allow=allow,
                                 ambiguous=ambiguous, verdicts=verdicts)
        rows.append(ev)

    addable = [r["term"] for r in rows if not r["refused"]]
    print(f"{lang}: {len(rows)} words read, {len(addable)} addable, {len(rows) - len(addable)} refused")
    for r in rows:
        tag = "OK     " if not r["refused"] else "REFUSED"
        extra = ""
        if r["content_elsewhere"]:
            extra += "; also a keyword in " + _more([f"{u['language']} ({u['articles']})" for u in r["content_elsewhere"]])
        if r["entities"]:
            extra += "; also an entity in " + _more([f"{u['language']} {u['kind']} ({u['articles']})" for u in r["entities"]], 3)
        if r["top_source_share"] is None and not r["refused"]:
            extra += "; source spread not in this log, single-source boilerplate NOT judged"
        print(f"  {tag} {r['term']:<24} articles {r['articles']:>6} mentions {r['mentions']:>7}"
              f"{'  ' + ','.join(r['refused']) if r['refused'] else ''}{extra}")
    if args.json:
        args.json.write_text(json.dumps({"language": lang, "rows": rows}, ensure_ascii=False, indent=2), "utf-8")

    if args.apply:
        if not addable:
            print("nothing addable; nothing written")
            return 0
        used_allow = [w for w in addable if norm(w) in allow]
        models = sorted({m for w in addable for m in verdicts[spelling(w)]["models"]}) if verdicts else []
        single = sorted(w for w in addable if verdicts and verdicts[spelling(w)]["single_reader"])
        source = f"log sha256 {file_hash(args.log)}; verdicts sha256 {file_hash(args.verdicts)}"
        if models:
            source += f"; models {', '.join(models)}"
        if single:
            source += f"; single reader: {', '.join(single)}"
        existed = (EXTRA_DIR / f"{lang}.yml").exists()
        path = append_batch(lang, addable, args.batch_id, used_allow, source)
        print(f"\nappended {len(addable)} words to {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
        # The loader adds a curly copy of every listed contraction, so the digest test needs both.
        declare = sorted(set(addable) | {w.replace("'", "\u2019") for w in addable if "'" in w})
        print("next: declare them in tests/test_analytics_extract.py::added_since_migration:")
        print("        " + ", ".join(f'"{w}"' for w in declare) + ",")
        if not existed:
            print(f"{path.name} is a NEW file: if its script is not Latin, also add it to "
                  "_NON_LATIN_FILES in tests/test_stopword_file_scripts.py (that guard fails until it is).")
        print("and add a section to configs/stopwords_extra/PROVENANCE.md with the evidence above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
