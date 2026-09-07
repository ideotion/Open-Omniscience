#!/usr/bin/env python3
"""Generate cross-language keyword RINGS from Wikidata labels (the pre-translation
program, Step 3).

Pre-translation AT SCALE without an LLM and without fabrication: for each seed
concept, find its Wikidata item (QID) and pull the multilingual LABELS + ALIASES
(all CC0) for the app's UI languages -> one ring carrying the translations AND the
synonyms (the aliases), SOURCED by the QID.

This runs on a NETWORKED machine -- Wikidata is not on the app's local-first fetch
path; the offline app only READS the generated file. The parse functions are pure
and offline-tested; only fetch_json() touches the network (stdlib urllib, no deps).

The output is a COMPLETE REPLACEMENT of whatever ``-o`` names -- it holds only the
rings THIS run produced. It does not append, and it never merges. (The docstring said
"augments" until 2026-09-07; the code has always overwritten, and the default ``-o``
is the live vetted file, so the sentence was one careless run away from deleting
hundreds of hand-vetted rings. Writing over an existing non-empty file is now a loud
refusal -- pass ``--force`` if replacement is genuinely what you want.) Always resolve
``-o`` to a fresh path and splice the result into configs/keyword_rings_generated.yml
as a deliberate, reviewed text append; never a full YAML round-trip, which reorders and
reformats every untouched ring and buries the real diff.

src/analytics/equivalence.py reads that file ALONGSIDE the hand-curated
configs/keyword_equivalents.yml (a curated ring WINS on an id collision). REVIEW
generated rings before trusting them (a wrong QID = a wrong concept); each ring carries
its QID for audit, and the existing language-signature gate still protects against
false merges.

--refresh is the second, cheaper pass (the 2026-07-20 ring-lifecycle ruling): it takes
the QIDs a human ALREADY vetted, re-reads them, and emits ONLY the members Wikidata has
since gained -- the within-concept alias and rename drift (the coronavirus -> COVID-19
class) that a growth pass never sees, at a vetting cost of reading a short list, because
the QID judgement was made once. It proposes; a human reviews; the splice stays manual.
It never re-searches (a re-search could silently re-point a ring at a different concept),
never removes a member (rings are never pruned -- cross-time recall is sacred, and a
label Wikidata dropped still serves the history already in the corpus), and never writes
a ``rings:`` document, so its output cannot be mistaken for a ring file.

Usage:
    python scripts/generate_wikidata_rings.py --seeds seeds.txt -o /tmp/new-rings.yml
    python scripts/generate_wikidata_rings.py --from-log oo-keyword-log.json --top 300 \
        -o /tmp/new-rings.yml
    python scripts/generate_wikidata_rings.py \
        --refresh configs/keyword_rings_generated.yml -o /tmp/ring-additions.yml
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

# The app's UI languages = the pre-translation scope. zh/ja are included for
# completeness though their keyword extraction is segmentation-limited today.
LANGS: tuple[str, ...] = ("ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh")

_API = "https://www.wikidata.org/w/api.php"
_UA = "OpenOmniscience-ring-generator/0.1 (local-first research app)"


def wbsearch_url(term: str, lang: str = "en") -> str:
    # Search in the SEED's own language, so a concept prominent only in ar/zh/ru
    # (surfaced by the ring-gap digest) resolves to a QID too — wbgetentities then
    # pulls labels for all 12 languages regardless of the search language.
    qs = urllib.parse.urlencode(
        {"action": "wbsearchentities", "search": term, "language": lang,
         "format": "json", "limit": 1, "type": "item"}
    )
    return f"{_API}?{qs}"


def wbentities_url(qid: str, langs: tuple[str, ...] = LANGS) -> str:
    qs = urllib.parse.urlencode(
        {"action": "wbgetentities", "ids": qid, "props": "labels|aliases",
         "languages": "|".join(langs), "format": "json"}
    )
    return f"{_API}?{qs}"


def parse_search(payload: dict) -> str | None:
    """The first search result's QID, or None."""
    results = payload.get("search") or []
    return results[0].get("id") if results else None


def parse_entity(payload: dict, qid: str, langs: tuple[str, ...] = LANGS) -> dict[str, list[str]]:
    """``{lang: [label, *aliases]}`` for the languages present (label + synonyms)."""
    ent = (payload.get("entities") or {}).get(qid) or {}
    labels = ent.get("labels") or {}
    aliases = ent.get("aliases") or {}
    out: dict[str, list[str]] = {}
    for lang in langs:
        terms: list[str] = []
        lab = (labels.get(lang) or {}).get("value")
        if lab:
            terms.append(lab)
        for al in aliases.get(lang, []) or []:
            if al.get("value"):
                terms.append(al["value"])
        seen: set[str] = set()
        uniq: list[str] = []
        for t in terms:
            k = t.casefold()
            if k not in seen:
                seen.add(k)
                uniq.append(t)
        if uniq:
            out[lang] = uniq
    return out


def _slug(s: str) -> str:
    return "-".join("".join(c if c.isalnum() else " " for c in s.lower()).split())


def build_ring(seed: str, qid: str, lang_terms: dict[str, list[str]]) -> dict | None:
    """A ring ``{id, qid, members:["lang:term", …]}``, or None if <2 languages."""
    members = [f"{lang}:{t}" for lang, terms in lang_terms.items() for t in terms]
    if len({m.split(":", 1)[0] for m in members}) < 2:
        return None  # a ring needs >=2 languages to merge anything
    en = lang_terms.get("en") or [seed]
    return {"id": _slug(en[0]) or qid.lower(), "qid": qid, "members": members}


def fetch_json(url: str, getter: Callable[[str], bytes] | None = None) -> dict:
    """GET + parse JSON. ``getter`` is injectable so tests never touch the network."""
    if getter is not None:
        return json.loads(getter(url))
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - documented Wikidata API
        return json.loads(r.read())


def generate(seeds, getter=None, sleep=0.2, log=print) -> list[dict]:
    """Build rings for each seed; one seed's failure never aborts the run.

    A seed is either a plain ``"term"`` (searched in English) or a ``(term, lang)``
    pair (searched in that language — for the cross-language ring-gap candidates)."""
    rings: list[dict] = []
    for raw in seeds:
        seed, slang = raw if isinstance(raw, tuple) else (raw, "en")
        try:
            qid = parse_search(fetch_json(wbsearch_url(seed, slang), getter))
            if not qid:
                log(f"  no QID for {seed!r}")
                continue
            lang_terms = parse_entity(fetch_json(wbentities_url(qid), getter), qid)
            ring = build_ring(seed, qid, lang_terms)
            if ring:
                rings.append(ring)
                log(f"  {seed} -> {qid} ({len(ring['members'])} members)")
            else:
                log(f"  {seed} -> {qid} but <2 languages, skipped")
        except Exception as e:  # noqa: BLE001 - per-seed resilience, logged
            log(f"  ERROR {seed!r}: {type(e).__name__}: {e}")
        if sleep:
            time.sleep(sleep)
    return rings


def _yaml_q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def emit_yaml(rings: list[dict], as_of: str) -> str:
    lines = [
        "# Cross-language keyword RINGS generated from Wikidata labels + aliases (CC0).",
        "# GENERATED FILE - regenerate with scripts/generate_wikidata_rings.py; review before trusting.",
        "# Each ring carries its Wikidata QID for audit; a curated ring of the same id wins.",
        f'generated_as_of: "{as_of}"',
        "rings:",
    ]
    for r in rings:
        lines.append(f"  - id: {r['id']}")
        lines.append(f"    qid: {r['qid']}")
        lines.append("    members: [" + ", ".join(_yaml_q(m) for m in r["members"]) + "]")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
#  --refresh: re-read the QIDs a human already vetted, propose only what is NEW
# --------------------------------------------------------------------------- #

# wbgetentities accepts several ids per call. Batching turns a 684-ring refresh from
# 684 requests into ~14, which is both faster and politer -- but a batch that comes
# back SHORT must never be read as "those QIDs were deleted": a truncated response and
# a deleted item are opposite facts, and conflating them would report drift that did
# not happen. Any id absent from a batch response is therefore re-fetched ALONE before
# it is classified, so only a single-id response can ever produce an "unresolved".
_BATCH = 50


def wbentities_batch_url(qids: Sequence[str], langs: tuple[str, ...] = LANGS) -> str:
    qs = urllib.parse.urlencode(
        {"action": "wbgetentities", "ids": "|".join(qids), "props": "labels|aliases",
         "languages": "|".join(langs), "format": "json"}
    )
    return f"{_API}?{qs}"


def _member_key(member: str) -> tuple[str, str] | None:
    """``"de:Wahl"`` -> ``("de", "wahl")``, the identity the APP compares on.

    This MIRRORS src.analytics.equivalence._parse_rings / _norm (casefold + collapsed
    whitespace) and is duplicated rather than imported so the script stays runnable on
    a networked machine that has no app checkout. tests/test_wikidata_ring_gen.py pins
    the two against each other: if they ever drift, a pure re-casing upstream ("Wahl" ->
    "wahl") would be proposed as an ADDITION that adds nothing the app does not already
    have -- a fabricated finding in a tool whose whole output is findings."""
    s = (member or "").strip()
    if ":" not in s:
        return None
    lang, term = s.split(":", 1)
    lang, term = lang.strip().casefold(), " ".join(term.split()).casefold()
    return (lang, term) if lang and term else None


def load_ring_file(path: Path) -> tuple[list[dict], list[str]]:
    """An existing generated rings file -> ``([{id, qid, members}], [ids_without_a_qid])``.

    Read with PyYAML -- the SAME parser the app uses -- never a hand-rolled line
    scanner: this file is hand-edited between runs (each vetting pass drops mis-resolved
    rings and adds comment blocks), so a purpose-built reader would eventually disagree
    with what equivalence.load_rings actually sees. The import is lazy so the --seeds and
    --from-log paths keep the module's stdlib-only property.

    A ring with no QID cannot be refreshed and is RETURNED SEPARATELY rather than
    dropped: silently skipping it would leave it permanently un-refreshed with nothing
    saying so."""
    try:
        import yaml  # noqa: PLC0415 - lazy: only --refresh needs a YAML reader
    except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent
        raise SystemExit(
            "--refresh needs PyYAML to read the existing ring file "
            "(pip install pyyaml, or run this from the project venv)"
        ) from exc
    data = yaml.safe_load(path.read_text("utf-8")) or {}
    rings: list[dict] = []
    no_qid: list[str] = []
    for r in (data.get("rings") or []):
        rid = str(r.get("id") or "").strip()
        qid = str(r.get("qid") or "").strip()
        members = [str(m).strip() for m in (r.get("members") or []) if str(m).strip()]
        if not rid or not members:
            continue
        if not qid:
            no_qid.append(rid)
            continue
        rings.append({"id": rid, "qid": qid, "members": members})
    return rings, no_qid


def _entity_state(payload: dict, qid: str) -> str:
    """``"ok"`` | ``"missing"`` | ``"absent"`` for one id in a wbgetentities payload.

    ``missing`` = Wikidata answered about this id and says it does not exist (deleted or
    merged upstream) -- a real finding about the ring. ``absent`` = the id is not in the
    response at all, which is a fact about the RESPONSE, not about the item; the caller
    re-fetches those singly rather than classifying them."""
    ents = payload.get("entities") or {}
    if qid not in ents:
        return "absent"
    return "missing" if "missing" in (ents.get(qid) or {}) else "ok"


def refresh_rings(rings, getter=None, sleep=0.2, log=print) -> dict:
    """Re-read each ring's QID and report ONLY what Wikidata has gained.

    Returns ``{"checked", "unchanged", "additions", "unresolved", "errors"}`` where the
    four outcome buckets partition the checked rings exactly (pinned by a test): a ring
    whose fetch FAILED is an ``error``, never folded into ``unchanged`` -- "we looked and
    nothing was new" and "we could not look" are different facts, and a refresh whose
    network flaked would otherwise report a clean bill of health."""
    additions: list[dict] = []
    unresolved: list[dict] = []
    errors: list[dict] = []
    unchanged = 0
    by_qid = {r["qid"]: r for r in rings}

    for start in range(0, len(rings), _BATCH):
        chunk = rings[start:start + _BATCH]
        qids = [r["qid"] for r in chunk]
        try:
            payload = fetch_json(wbentities_batch_url(qids), getter)
        except Exception as e:  # noqa: BLE001 - per-batch resilience, recorded not swallowed
            log(f"  ERROR batch {qids[0]}..{qids[-1]}: {type(e).__name__}: {e}")
            errors.extend({"id": r["id"], "qid": r["qid"], "reason": f"{type(e).__name__}: {e}"}
                          for r in chunk)
            if sleep:
                time.sleep(sleep)
            continue

        for qid in qids:
            ring = by_qid[qid]
            state = _entity_state(payload, qid)
            single = payload
            if state == "absent":
                # Not in the batch response -> ask about this id ALONE before deciding.
                try:
                    single = fetch_json(wbentities_batch_url([qid]), getter)
                    state = _entity_state(single, qid)
                except Exception as e:  # noqa: BLE001
                    log(f"  ERROR {ring['id']} ({qid}): {type(e).__name__}: {e}")
                    errors.append({"id": ring["id"], "qid": qid,
                                   "reason": f"{type(e).__name__}: {e}"})
                    continue
                if state == "absent":
                    errors.append({"id": ring["id"], "qid": qid, "reason":
                                   "no entity for this id even when asked alone — "
                                   "an unreadable response, not a verdict about the item"})
                    continue
            if state == "missing":
                unresolved.append({"id": ring["id"], "qid": qid, "reason":
                                   "Wikidata reports this id as missing (deleted or merged "
                                   "upstream) — the ring's identity needs re-vetting"})
                log(f"  {ring['id']} ({qid}) MISSING upstream")
                continue

            lang_terms = parse_entity(single, qid)
            fresh = [f"{lang}:{t}" for lang, terms in lang_terms.items() for t in terms]
            if not fresh:
                unresolved.append({"id": ring["id"], "qid": qid, "reason":
                                   "the item resolves but now carries no label or alias in "
                                   "the app's 12 languages — the ring's identity needs "
                                   "re-vetting"})
                log(f"  {ring['id']} ({qid}) resolves but has no label in our languages")
                continue

            have = {k for k in (_member_key(m) for m in ring["members"]) if k}
            new: list[str] = []
            seen: set[tuple[str, str]] = set()
            for m in fresh:
                k = _member_key(m)
                if k and k not in have and k not in seen:
                    seen.add(k)
                    new.append(m)
            if new:
                additions.append({"id": ring["id"], "qid": qid, "new_members": new})
                log(f"  {ring['id']} ({qid}) +{len(new)}")
            else:
                unchanged += 1
        if sleep:
            time.sleep(sleep)

    return {
        "checked": len(rings),
        "unchanged": unchanged,
        "additions": additions,
        "unresolved": unresolved,
        "errors": errors,
    }


def emit_additions_yaml(result: dict, as_of: str, source: str, no_qid: Sequence[str] = ()) -> str:
    """The review artifact: what to splice, what to re-vet, and what was not checked.

    The top-level key is ``ring_additions``, NEVER ``rings`` -- equivalence._parse_rings
    reads ``rings:``, so if this file is ever pointed at the app by accident it yields
    zero rings instead of REPLACING a full ring with the handful of members listed here
    (load_rings merges by id, last one wins)."""
    lines = [
        "# Wikidata RING ADDITIONS — a proposal, not a ring file.",
        "# Generated by scripts/generate_wikidata_rings.py --refresh: the members the",
        "# already-vetted QIDs have GAINED upstream since the source file was written.",
        "# Review each line, then splice the accepted ones into the source file by hand.",
        "# Nothing here is removed from the source: rings are never pruned.",
        f'generated_as_of: "{as_of}"',
        f"source_file: {_yaml_q(source)}",
        f"checked: {result['checked']}",
        f"unchanged: {result['unchanged']}",
        f"rings_with_additions: {len(result['additions'])}",
        f"members_proposed: {sum(len(a['new_members']) for a in result['additions'])}",
        f"unresolved_count: {len(result['unresolved'])}",
        f"not_checked_count: {len(result['errors'])}",
        f"rings_without_a_qid: {len(no_qid)}",
        "ring_additions:",
    ]
    # Ids are QUOTED here, unlike emit_yaml's: there the id comes from _slug() and is
    # alphanumeric by construction, here it is read back out of a HAND-EDITED file, so a
    # colon in one would silently emit a document that no longer parses.
    for a in result["additions"]:
        lines.append(f"  - id: {_yaml_q(a['id'])}")
        lines.append(f"    qid: {_yaml_q(a['qid'])}")
        lines.append("    new_members: [" + ", ".join(_yaml_q(m) for m in a["new_members"]) + "]")
    lines.append("unresolved:")
    for u in result["unresolved"]:
        lines.append(f"  - id: {_yaml_q(u['id'])}")
        lines.append(f"    qid: {_yaml_q(u['qid'])}")
        lines.append(f"    reason: {_yaml_q(u['reason'])}")
    lines.append("not_checked:")
    for e in result["errors"]:
        lines.append(f"  - id: {_yaml_q(e['id'])}")
        lines.append(f"    qid: {_yaml_q(e['qid'])}")
        lines.append(f"    reason: {_yaml_q(e['reason'])}")
    lines.append("without_a_qid: [" + ", ".join(_yaml_q(r) for r in no_qid) + "]")
    return "\n".join(lines) + "\n"

def load_seeds(args):
    """Return seeds as ``(term, search_language)`` pairs.

    With ``--from-log`` it PREFERS the ``ring_candidates`` gap digest (concepts NOT
    yet in any ring, every language), so a generation pass resolves NEW concepts
    instead of re-resolving the ones we already have, and a concept prominent only
    in ar/zh/ru is seedable too. It falls back to the legacy full ``keywords`` list
    (English terms by spread) for older logs without the digest."""
    if args.seeds:
        return [
            (ln.strip(), "en")
            for ln in Path(args.seeds).read_text("utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]
    if args.from_log:
        data = json.loads(Path(args.from_log).read_text("utf-8"))
        data = data.get("data", data)
        by_lang = (data.get("ring_candidates") or {}).get("by_language") or {}
        if by_lang:
            pool = [
                (c.get("normalized") or c.get("term"), lang, int(c.get("articles", 0) or 0))
                for lang, blk in by_lang.items()
                for c in (blk.get("candidates") or [])
                if (c.get("normalized") or c.get("term"))
            ]
            pool.sort(key=lambda t: -t[2])  # highest article spread first, across languages
            return [(term, lang) for term, lang, _a in pool[: args.top]]
        # Legacy fallback: the full per-keyword list (English terms by spread).
        kws = data.get("keywords", [])
        en = [k for k in kws if k.get("language") == "en" and k.get("kind") == "term"]
        en.sort(key=lambda k: -int(k.get("articles", 0) or 0))
        return [((k.get("normalized") or k.get("term")), "en") for k in en[: args.top]]
    return []


_LIVE_RINGS = Path("configs/keyword_rings_generated.yml")


def _refuse_overwrite(out: Path, force: bool) -> str | None:
    """The message refusing to clobber an existing non-empty file, or None to proceed.

    Every write this script performs is a full replacement, and ``-o`` defaults to the
    live vetted ring file, so an ordinary-looking seed run could delete hundreds of
    hand-vetted rings with no error and no diff to notice. The check is deliberately on
    "exists and is non-empty" rather than on "parses as rings": a narrower test would
    read as precision it does not have, and there is no file at an output path that a
    replacement should be silent about."""
    if force or not out.exists():
        return None
    try:
        if out.stat().st_size == 0:
            return None
    except OSError:
        return None
    return (
        f"refusing to overwrite {out}: this script REPLACES its output, it never merges, "
        "so writing here would drop everything the file already holds. Write to a fresh "
        "path and splice the result in as a reviewed text append, or pass --force if "
        "replacement is genuinely what you want."
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--seeds", type=str, help="file of English seed terms (one per line)")
    ap.add_argument("--from-log", type=str, help="a keyword-diagnostics log; use its top English terms")
    ap.add_argument("--top", type=int, default=300, help="with --from-log, how many top terms")
    ap.add_argument(
        "--refresh", type=Path,
        help="an existing generated rings file: re-read its already-vetted QIDs and emit "
             "ONLY the members Wikidata has since gained (a review artifact, never a ring file)",
    )
    ap.add_argument(
        "--force", action="store_true",
        help="allow the output to replace an existing non-empty file (it is never merged)",
    )
    ap.add_argument(
        "-o", "--out", type=Path, default=None,
        help=f"output path (growth passes default to {_LIVE_RINGS}; --refresh requires one)",
    )
    args = ap.parse_args(argv)

    if args.refresh and (args.seeds or args.from_log):
        print("--refresh re-reads known QIDs and --seeds/--from-log resolve new ones; "
              "run them as separate passes", file=sys.stderr)
        return 2

    if args.refresh:
        # No default: a --refresh document uses a `ring_additions:` key, so writing it to
        # the live ring path would leave the app with ZERO rings (equivalence reads
        # `rings:`) — a silent, total loss of the translation layer.
        if args.out is None:
            print("--refresh writes a review artifact, not a ring file: name it with "
                  "-o (e.g. -o /tmp/ring-additions.yml)", file=sys.stderr)
            return 2
        if args.out.resolve() == args.refresh.resolve():
            print(f"--refresh cannot write over its own input ({args.refresh})", file=sys.stderr)
            return 2
        if (msg := _refuse_overwrite(args.out, args.force)):
            print(msg, file=sys.stderr)
            return 2
        rings, no_qid = load_ring_file(args.refresh)
        if not rings:
            print(f"no rings with a QID in {args.refresh} — nothing to refresh", file=sys.stderr)
            return 2
        print(f"re-reading {len(rings)} vetted QIDs via Wikidata...", file=sys.stderr)
        result = refresh_rings(rings, log=lambda m: print(m, file=sys.stderr))
        args.out.write_text(
            emit_additions_yaml(result, date.today().strftime("%Y-%m"), str(args.refresh), no_qid),
            encoding="utf-8",
        )
        proposed = sum(len(a["new_members"]) for a in result["additions"])
        print(
            f"[{proposed} member(s) proposed across {len(result['additions'])} ring(s); "
            f"{result['unchanged']} unchanged, {len(result['unresolved'])} need re-vetting, "
            f"{len(result['errors'])} NOT checked -> {args.out}]",
            file=sys.stderr,
        )
        return 0

    out = args.out if args.out is not None else _LIVE_RINGS
    seeds = load_seeds(args)
    if not seeds:
        print("no seeds (use --seeds FILE, --from-log LOG.json or --refresh RINGS.yml)",
              file=sys.stderr)
        return 2
    if (msg := _refuse_overwrite(out, args.force)):
        print(msg, file=sys.stderr)
        return 2
    print(f"generating rings for {len(seeds)} seeds via Wikidata...", file=sys.stderr)
    rings = generate(seeds, log=lambda m: print(m, file=sys.stderr))
    out.write_text(emit_yaml(rings, date.today().strftime("%Y-%m")), encoding="utf-8")
    print(f"[wrote {len(rings)} rings -> {out}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
