#!/usr/bin/env python3
"""Turn a diagnostics keyword log into a reviewed stoplist batch (R111). OFFLINE, maintainer side.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R111 (2026-09-30): the stoplist is OURS to grow and users are never asked about it. We
curate batches from the keyword logs in the diagnostics a maintainer sends, and ship them in
``configs/stopwords_extra/<lang>.yml`` with each app update. This tool is the part that keeps
that safe. It runs in a checkout, never inside the app, never touches the network, and never
edits anything unless you say ``--apply``.

    python scripts/stopword_batch.py LOG --language en                 # the evidence table
    python scripts/stopword_batch.py LOG --language en --words w.txt   # check a decided list
    python scripts/stopword_batch.py LOG --language en --words w.txt --apply --batch-id en-2026-10

``LOG`` is the keyword-log zip (or the single JSON) the diagnostics export produces. ``w.txt``
is the decided list, one word per line (``#`` comments allowed): the words the curation
accepted. Without ``--words`` the tool prints candidates worth reading, never a decision.

WHY THE REFUSALS EXIST. ``configs/stopwords_extra`` is a LANGUAGE-AGNOSTIC union
(``global_stopwords()``): a word added for English hides that spelling in EVERY language. So a
word is refused, with the reason, when adding it would hide signal:

* ``ring_member``      a member of a shipped translation ring (R102), in any language: signal, not grammar;
* ``platform_name``    facebook, twitter and kin COUNT as keywords (R104);
* ``content_elsewhere`` another language stores it as a live keyword (evidence from THIS log);
* ``also_an_entity``   the log holds it as a person / place / organisation, which the hide set
                       (a whole-normalized-term match) would hide too;
* ``single_source``    one source holds most of its mentions: that is that source's boilerplate,
                       which a global stopword must not hide (needs ``top_source_share``, which
                       the diagnostics gains in a later update; absent = not judged, and said so);
* ``already_hidden``   nothing to add;
* ``phrase``           multi-word entries are refused until the hide path is verified for them.

A maintainer can override ``content_elsewhere`` and ``also_an_entity`` for a word with
``--allow WORD`` (recorded in the batch comment); ``ring_member`` and ``platform_name`` have no
override. HOW THIS DIFFERS FROM ``scripts/analyze_keyword_log.py``. That script reads one log and PROPOSES
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
import json
import sys
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
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

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


def norm(term: object) -> str:
    return unicodedata.normalize("NFC", str(term or "").strip()).casefold()


def platform_names(path: Path = KEEP_FILE) -> frozenset[str]:
    try:
        data = yaml.safe_load(path.read_text("utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return frozenset()
    return frozenset(norm(n) for n in (data.get("platform_names") or []) if norm(n))


def read_words(path: Path) -> list[str]:
    words: list[str] = []
    for line in path.read_text("utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and norm(line) not in words:
            words.append(norm(line))
    return words


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
        "already_hidden": word in hidden_in_lang,
    }


def refusals(word: str, ev: dict[str, Any], *, ring_words: frozenset[str], platforms: frozenset[str],
             allow: frozenset[str]) -> list[str]:
    """Why a word may not be added, as stable keys. Empty = addable."""
    out: list[str] = []
    if " " in word:
        out.append("phrase")
    if ev["already_hidden"]:
        out.append("already_hidden")
    if word in platforms:
        out.append("platform_name")
    if word in ring_words:
        out.append("ring_member")
    if ev["content_elsewhere"] and word not in allow:
        out.append("content_elsewhere")
    if ev["entities"] and word not in allow:
        out.append("also_an_entity")
    if ev["top_source_share"] is not None and ev["top_source_share"] >= SINGLE_SOURCE_SHARE:
        out.append("single_source")
    return out


def app_context(lang: str) -> tuple[frozenset[str], frozenset[str]]:
    """(what extraction already drops in ``lang``, every single-word member of a SHIPPED ring).

    The second set is every ring member in every language, not only the ones the union already
    hides (``_ring_member_exemptions``): a word not hidden today is exactly what a batch adds, and
    a translated concept is signal (R102) whichever language's file would hide it.
    """
    from src.analytics.equivalence import shipped_rings
    from src.analytics.extract import _stopset

    ring = {
        (term or "").casefold()
        for r in shipped_rings()
        for _lang, term in r.members
        if term and " " not in term
    }
    return _stopset(lang), frozenset(ring)


def candidates_to_read(log_doc: dict, lang: str, existing: frozenset[str]) -> list[str]:
    """The spellings worth reading for a language: surfaced by the analyzer, net-new only."""
    import analyze_keyword_log as akl

    kws = log_doc.get("data", {}).get("keywords", [])
    by = akl.stopword_candidates(kws, set(existing), 0)
    return [c["normalized"] for c in by.get(lang, []) if c["bucket"] == "high_confidence"] + [
        c["normalized"] for c in by.get(lang, []) if c["bucket"] != "high_confidence"
    ]


def yaml_scalar(term: str) -> str:
    """A list item that survives YAML: quote anything it would read as a bool, number or null."""
    dumped = yaml.safe_dump(term, allow_unicode=True, default_flow_style=True, width=float("inf")).strip()
    return dumped.removesuffix("...").strip()


def append_batch(lang: str, words: list[str], batch_id: str, allowed: list[str], source: str) -> Path:
    """Append ``words`` to ``configs/stopwords_extra/<lang>.yml`` and prove the file still loads."""
    path = EXTRA_DIR / f"{lang}.yml"
    before = path.read_text("utf-8") if path.exists() else "stopwords:\n"
    doc = yaml.safe_load(before) or {}
    if not isinstance(doc.get("stopwords"), list):
        raise SystemExit(f"{path} has no 'stopwords:' list; refusing to edit it")
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [f"  # batch {batch_id} ({stamp}; source: {source})"]
    if allowed:
        lines.append(f"  # maintainer overrides (content elsewhere / entity reviewed): {', '.join(sorted(allowed))}")
    for w in sorted(words):
        lines.append(f"  - {yaml_scalar(w)}")
    after = before.rstrip("\n") + "\n" + "\n".join(lines) + "\n"
    loaded = yaml.safe_load(after)["stopwords"]
    if [str(x) for x in loaded[-len(words):]] != sorted(words):
        raise SystemExit(f"{path}: the appended words did not round-trip through YAML; nothing written")
    path.write_text(after, "utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", type=Path, help="keyword-log zip or JSON from the diagnostics export")
    ap.add_argument("--language", required=True, help="the language whose list the words go into (e.g. en)")
    ap.add_argument("--words", type=Path, help="the decided words, one per line")
    ap.add_argument("--allow", action="append", default=[], help="override content_elsewhere / also_an_entity for a word")
    ap.add_argument("--apply", action="store_true", help="append the addable words to the language's file")
    ap.add_argument("--batch-id", help="the batch's id (required with --apply)")
    ap.add_argument("--json", type=Path, help="also write the full evidence report here")
    args = ap.parse_args(argv)

    import analyze_keyword_log as akl

    lang = args.language.strip().lower()
    doc = akl.load_log(args.log)
    keywords = doc.get("data", {}).get("keywords", [])
    index = index_log(keywords)
    hidden, ring = app_context(lang)
    platforms = platform_names()
    allow = frozenset(norm(a) for a in args.allow)

    words = read_words(args.words) if args.words else candidates_to_read(doc, lang, hidden)
    rows = []
    for w in words:
        ev = evidence(w, lang, index.get(w, []), hidden)
        ev["refused"] = refusals(w, ev, ring_words=ring, platforms=platforms, allow=allow)
        rows.append(ev)

    addable = [r["term"] for r in rows if not r["refused"]]
    print(f"{lang}: {len(rows)} words read, {len(addable)} addable, {len(rows) - len(addable)} refused")
    for r in rows:
        tag = "OK     " if not r["refused"] else "REFUSED"
        extra = ""
        if r["content_elsewhere"]:
            extra += "; also a keyword in " + ", ".join(f"{u['language']} ({u['articles']})" for u in r["content_elsewhere"][:4])
        if r["entities"]:
            extra += "; also an entity in " + ", ".join(f"{u['language']} {u['kind']} ({u['articles']})" for u in r["entities"][:3])
        if r["top_source_share"] is None and not r["refused"]:
            extra += "; source spread not in this log, single-source boilerplate NOT judged"
        print(f"  {tag} {r['term']:<24} articles {r['articles']:>6} mentions {r['mentions']:>7}"
              f"{'  ' + ','.join(r['refused']) if r['refused'] else ''}{extra}")
    if args.json:
        args.json.write_text(json.dumps({"language": lang, "rows": rows}, ensure_ascii=False, indent=2), "utf-8")

    if args.apply:
        if not args.words or not args.batch_id:
            raise SystemExit("--apply needs --words and --batch-id")
        if not addable:
            print("nothing addable; nothing written")
            return 0
        used_allow = [w for w in addable if w in allow]
        path = append_batch(lang, addable, args.batch_id, used_allow, args.log.name)
        print(f"\nappended {len(addable)} words to {path.relative_to(ROOT)}")
        print("next: declare them in tests/test_analytics_extract.py::added_since_migration:")
        print("        " + ", ".join(f'"{w}"' for w in sorted(addable)) + ",")
        print("and add a section to configs/stopwords_extra/PROVENANCE.md with the evidence above.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
