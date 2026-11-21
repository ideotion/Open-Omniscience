#!/usr/bin/env python3
"""Read the law coverage report back from a returned Field data file (row 267, 0.6 gate row C).

Usage:
    python3 scripts/law_coverage_readback.py oo-field-YYYYMMDD-HHMM-<instance>-law-coverage.json [--json]

The file is what the Field data button saved from ``/api/diagnostics/law-coverage`` (``src/law/coverage.py:law_coverage_report``
in its export envelope), the same report the Diagnostics zip carries as ``law-coverage.json`` and Living sources draws. A file the
button cut into numbered pieces (``...-part-001-of-002.json``) can be given as any one of its pieces: the set is joined in memory,
and a missing piece is named rather than guessed at. The member taken out of a Diagnostics zip is read the same way, and so is the
zip itself (only that one member is read from it).

Prints what gate row C closes on: every country on the language floor with its state (tracked, verified-not-yet-tracked,
unverified, no eligible source), the order within a state and what it was read from, the twelve-language tally with zh on its
own line, then the many-country sources, the documents credited to no country, the countries off the floor (the world block) and
the catalogue's official counts. A figure the report does not have is printed with its reason, never as 0. Country and language
codes, states, counts and dates only: no source address, host, title or document is printed. No verdict, no score, no fraction.

Stdlib only; reads the file it is given and writes nothing; no network.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
#: The member's name inside a Diagnostics zip (src/api/diagnostics/bundle.py).
MEMBER = "law-coverage.json"
#: The largest member read out of a zip. The report is tens of kilobytes; anything far past that is not the member.
_MAX_MEMBER_BYTES = 5_000_000
#: The floor's states, in the report's own order (src/law/coverage.py FLOOR_STATES, then the unreadable-catalogue state).
STATES = ("tracked", "verified-not-yet-tracked", "unverified", "no-eligible-source", "unchecked")
_STATE_WORDS = {
    "tracked": "tracked",
    "verified-not-yet-tracked": "verified but not yet tracked",
    "unverified": "unverified",
    "no-eligible-source": "no eligible source",
    "unchecked": "unchecked (the catalogue could not be read)",
}
_BASES = ("official", "de-facto", "regional")
#: Words this script prints from the file: the code's fixed sentences and the floor file's dated labels. Nothing that could be an
#: address: no slash, @, ?, =, & or #. A value outside it (a hand-edited or foreign file) is not printed (R734/R736).
_WORDS = re.compile(r"[A-Za-z0-9_ ,;:'()\-.]{1,400}")
_CODE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{1,3})?")  # a country or language code, or a subdivision (us-ca)
#: A host name inside otherwise plain words (a population table's source, a hand-edited reason): never printed.
_HOST = re.compile(r"\b[\w-]+(\.[\w-]+)*\.(org|com|net|int|gov|edu|io|info|eu|uk|fr|de|un)\b", re.IGNORECASE)
#: The repository folders the report's fixed sentences name a file in ("the floor file (configs/language_countries.yml) ...").
#: The folder is dropped and the file's name kept, so the reason is shown without a path.
_REPO_DIRS = re.compile(r"\b(configs|src|docs|scripts)/")


def _pieces() -> Any:
    """``src/monitoring/field_pieces.py`` loaded by path (stdlib only), as the other read-back scripts do."""
    if "oo_field_pieces" in sys.modules:
        return sys.modules["oo_field_pieces"]
    spec = importlib.util.spec_from_file_location("oo_field_pieces", _HERE.parent / "src" / "monitoring" / "field_pieces.py")
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load src/monitoring/field_pieces.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["oo_field_pieces"] = mod
    spec.loader.exec_module(mod)
    return mod


def _from_zip(path: Path) -> bytes:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n == MEMBER or n.endswith("/" + MEMBER)]
        if not names:
            raise ValueError(f"{path.name}: a zip without {MEMBER}")
        info = zf.getinfo(names[0])
        if info.file_size > _MAX_MEMBER_BYTES:
            raise ValueError(f"{path.name}: {MEMBER} is {info.file_size:,} bytes, far past the report's size; not read")
        return zf.read(info)


def load(path: Path) -> dict[str, Any]:
    """The report in ``path`` (a piece of a set is joined first), out of its export envelope. ValueError says what is wrong."""
    if zipfile.is_zipfile(path):
        data = _from_zip(path)
    elif _pieces().piece_of(path) is not None:
        _name, data = _pieces().join_set(path)
    else:
        data = path.read_bytes()
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name}: not a JSON file ({type(exc).__name__})") from exc
    if not isinstance(doc, dict):
        raise ValueError(f"{path.name}: not a law coverage report (a JSON object was expected)")
    if doc.get("kind") == "law-coverage" and isinstance(doc.get("data"), dict):
        return {**doc["data"], "_envelope": {k: doc.get(k) for k in ("generated_at", "app_version")}}
    if "kind" in doc and doc.get("kind") != "law-coverage":
        raise ValueError(f"{path.name}: an export of another kind, not the law coverage report")
    return doc


def _int(value: Any) -> int | None:
    """A count, or None for anything that is not one (a bool, a string, a missing key): never coerced into a 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _n(value: Any) -> str:
    v = _int(value)
    return "—" if v is None else f"{v:,}"


def _code(value: Any) -> str:
    """A country, language or jurisdiction code as the report writes it; anything else reads ``?``."""
    return value if isinstance(value, str) and _CODE.fullmatch(value) else "?"


def _codes(values: Any) -> str:
    codes = [_code(v) for v in _list(values)]
    return ", ".join(codes) if codes else "none"


def _words(value: Any, fallback: str) -> str:
    if not isinstance(value, str) or not value:
        return fallback
    text = _REPO_DIRS.sub("", value)
    if not _WORDS.fullmatch(text) or _HOST.search(text):
        return "a value not in the report's own words (not printed)"
    return text


def _counts(states: Any, reason: str | None) -> str:
    """One row's counts per state. Where the catalogue was not read (an ``unchecked`` count is present), the states that needed it
    were not looked up: they read so, with the reason, never as a 0 (the report writes null for them since row 272)."""
    st = _dict(states)
    if not st:
        return "states not recorded"
    if "unchecked" in st:
        return (f"tracked {_n(st.get('tracked'))}, not looked up {_n(st.get('unchecked'))}"
                f" (the other states need the catalogue: {reason or 'it could not be read'})")
    # A null count is a state the report did not look up (row 272): said so, never a dash that could pass for a figure.
    return ", ".join(f"{_STATE_WORDS[s]} {'not looked up' if st.get(s) is None else _n(st.get(s))}" for s in STATES if s in st)


def _when(iso: Any) -> str | None:
    """An ISO date or time cut to the minute, or None for anything that is not one."""
    if not isinstance(iso, str) or len(iso) < 10 or not re.fullmatch(r"\d{4}-\d\d-\d\d", iso[:10]):
        return None
    out = iso[:16].replace("T", " ")
    return out + " UTC" if len(out) > 10 else out


def _order_line(order: Any, label: str) -> str:
    o = _dict(order)
    if not o:
        return f"{label}: not recorded in this file"
    if o.get("by") == "population":
        line = (f"{label}: by population reached, from {_words(o.get('source'), 'an unnamed table')}"
                f" dated {_when(o.get('as_of')) or 'with no date'}")
        missing = _list(o.get("missing"))
        return line + (f"; not in the table, so listed by code after the rest: {_codes(missing)}" if missing else "")
    if o.get("by") == "code":
        return f"{label}: by code ({_words(o.get('reason'), 'no reason given')})"
    return f"{label}: not stated in this file"


def _state_lines(by_state: Any, indent: str = "  ", reason: str | None = None) -> list[str]:
    """Each state's countries by code, in the report's order. A state the file does not list says so, never 0; where the
    catalogue was not read, the states that need it say they were not looked up (null in the report since row 272)."""
    bs = _dict(by_state)
    out = []
    if "unchecked" in bs:
        for st in ("tracked", "unchecked"):
            codes = _list(bs.get(st))
            out.append(f"{indent}{_STATE_WORDS[st]}: {len(codes)}" + (f" ({_codes(codes)})" if codes else ""))
        out.append(f"{indent}verified but not yet tracked, unverified, no eligible source: not looked up ({reason or 'the catalogue could not be read'})")
        return out
    for st in STATES:
        if st not in bs:
            if st != "unchecked":
                out.append(f"{indent}{_STATE_WORDS[st]}: not listed in this file")
            continue
        if bs[st] is None:  # row 272: null is a state nothing looked up, never an empty one
            out.append(f"{indent}{_STATE_WORDS[st]}: not looked up")
            continue
        codes = _list(bs[st])
        out.append(f"{indent}{_STATE_WORDS[st]}: {len(codes)}" + (f" ({_codes(codes)})" if codes else ""))
    return out


#: The floor file's read states (row 279), as the report states them; the error is printed only when it is a plain token.
_FLOOR_READ_WORDS = {
    "absent": "no language-to-country list (configs/language_countries.yml) on that machine",
    "empty": "the language-to-country list was read and lists no country",
    "unreadable": "the language-to-country list could not be read",
}


def _floor_read(block: dict[str, Any]) -> str | None:
    """Words for a floor file that was not read (row 279), or None when it was read or the file does not say."""
    read = _dict(block.get("floor"))
    state = read.get("state")
    if state in (None, "present"):
        return None
    words = _FLOOR_READ_WORDS.get(state) if isinstance(state, str) else None
    if words is None:
        return "the floor file's read state is not one this script knows (not printed)"
    error = read.get("error")
    if state == "unreadable" and isinstance(error, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", error):
        words += f" ({error})"
    return f"{state}: {words}"


def floor_lines(floor: Any) -> list[str]:
    f = _dict(floor)
    if not f:
        return ["floor: absent from this file (a build before the floor report)"]
    lines = []
    countries = _int(f.get("countries"))
    unread = _floor_read(f)
    if unread is not None:
        head = f"floor: {unread}, so no floor country was counted"
    elif countries is None:
        head = "floor: country count not recorded"
    elif countries == 0 and f.get("state") != "checked":
        head = "floor: no country listed"  # the report's 0 for a floor file it could not read: not a floor of no countries
    else:
        head = f"floor: {_n(countries)} countries"
    as_of = _when(f.get("as_of"))
    head += f", floor file dated {as_of}" if as_of else ", floor file undated"
    head += f" ({_words(f.get('verification_status'), 'its verification is not stated')})"
    lines.append(head)
    if f.get("state") != "checked":
        lines.append(f"  not checked: {_words(f.get('reason'), 'no reason given')}")
        if f.get("by_state") is None:
            return lines
    why = _words(f.get("reason"), "the catalogue could not be read")
    lines += _state_lines(f.get("by_state"), reason=why)
    lines.append("  " + _order_line(f.get("order"), "order within a state"))
    rows = [r for r in _list(f.get("languages")) if isinstance(r, dict)]
    if f.get("languages") is None:
        lines.append("  languages: not recorded in this file")
    else:
        lines.append(f"  the {len(rows)}-language tally:")
    zh_row = None
    for r in rows:
        code = _code(r.get("language"))
        if code == "zh":
            zh_row = r
        bases = ", ".join(f"{b} {len(_list(r.get(b)))}" for b in _BASES if b in r) or "no country listed"
        st = _dict(r.get("states"))
        counts = _counts(st, why)
        docs = _int(r.get("documents"))
        contested = _list(r.get("contested"))
        lines.append(f"    {code}: {bases} · {counts} · " + (f"{docs:,} documents" if docs is not None else "documents not recorded")
                     + (f" · contested: {_codes(contested)}" if contested else ""))
    beyond = _dict(f.get("zh_beyond_floor"))
    if zh_row is None and beyond == {}:
        lines.append("  zh: not in this file")
    else:
        zh_states = _dict(_dict(zh_row).get("states"))
        listed = _counts(zh_states, why)
        named = ", ".join(f"{_code(cc)} {_STATE_WORDS.get(str(s), '?')}" for cc, s in sorted(beyond.items())) or "none"
        lines.append(f"  zh (its own line): floor countries {listed}; named by the seed row beyond the floor: {named}")
    many = f.get("many_country_sources")
    if many is None:
        lines.append("  many-country sources: not read (the catalogue could not be read)" if f.get("state") != "checked"
                     else "  many-country sources: not recorded in this file")
    else:
        for code, domains in sorted(_dict(many).items()):
            d = _dict(domains)
            verified = sum(1 for v in d.values() if v is True)
            lines.append(f"  many-country sources under {_code(code)}: {len(d)} listed, {verified} verified (credited to no single country)")
    unplaced = _dict(f.get("unplaced_documents"))
    lines.append("  documents that state no country: "
                 + (", ".join(f"{_code(j)} {_n(v)}" for j, v in sorted(unplaced.items())) if unplaced else "none")
                 if f.get("unplaced_documents") is not None else "  documents that state no country: not recorded in this file")
    non_law = _dict(f.get("non_law_documents"))
    lines.append("  documents that are not law (credit no country): "
                 + (", ".join(f"{_words(k, '?')} {_n(v)}" for k, v in sorted(non_law.items())) if non_law else "none")
                 if f.get("non_law_documents") is not None else "  documents that are not law: not recorded in this file")
    invalid = f.get("invalid_rows")
    if invalid is None:
        lines.append("  floor file rows set aside: not recorded in this file")
    elif _list(invalid):
        lines.append(f"  floor file rows set aside as invalid: {len(_list(invalid))}")
    return lines


def world_lines(world: Any) -> list[str]:
    w = _dict(world)
    if not w:
        return ["off the floor (world): absent from this file (a build before the world block)"]
    lines = [f"off the floor (world): {_n(w.get('countries'))} countries"
             + ("" if w.get("state") == "checked" else f"; not checked: {_words(w.get('reason'), 'no reason given')}")]
    unread = _floor_read(w)
    if unread is not None:
        # Row 279: no floor was read, so no country was set aside for the floor block; the floor's own countries are in here.
        lines.append(f"  the floor was not read ({unread}), so no country is set aside for the floor block and every "
                     "country is listed here")
    unchecked = w.get("state") != "checked"
    lines.append("  " + _counts(w.get("states"), _words(w.get("reason"), "the catalogue could not be read")))
    research, empty = _int(w.get("no_eligible_source_to_research")), _int(w.get("no_eligible_source_no_permanent_population"))
    if research is not None and not unchecked:
        lines.append(f"  no eligible source, research to do: {research:,}"
                     + (f"; no permanent population: {empty:,}" if empty is not None else ""))
    lines.append("  " + _order_line(w.get("order"), "order within a state"))
    odd = _list(w.get("tracked_codes_not_listed"))
    if odd:
        lines.append(f"  codes a tracked document states that no block lists: {_codes(odd)}")
    return lines


def json_floor(doc: dict[str, Any]) -> dict[str, Any]:
    """The floor block for ``--json``: its codes, states, counts and dates, through the same filters as the text. The method and
    caveat sentences, the many-country sources' hosts and the floor file's invalid-row texts are left out."""
    f = _dict(doc.get("floor"))
    order = _dict(f.get("order"))
    return {
        "state": f.get("state") if f.get("state") in ("checked", "unchecked") else None,
        "floor_read": _floor_read(f),  # row 279: words for a floor file that was not read, else None
        "reason": _words(f.get("reason"), "") or None,
        "as_of": _when(f.get("as_of")),
        "countries": _int(f.get("countries")),
        "by_state": {st: (None if v is None else [_code(c) for c in _list(v)]) for st, v in _dict(f.get("by_state")).items() if st in STATES},
        "languages": [
            {"language": _code(r.get("language")), **{b: [_code(c) for c in _list(r.get(b))] for b in _BASES if b in r},
             "states": {st: _int(v) for st, v in _dict(r.get("states")).items() if st in STATES}, "documents": _int(r.get("documents"))}
            for r in _list(f.get("languages")) if isinstance(r, dict)
        ],
        "zh_beyond_floor": {_code(cc): (st if st in STATES else None) for cc, st in _dict(f.get("zh_beyond_floor")).items()},
        "order": {"by": order.get("by") if order.get("by") in ("population", "code") else None,
                  "source": _words(order.get("source"), "") or None, "as_of": _when(order.get("as_of")),
                  "missing": [_code(c) for c in _list(order.get("missing"))]},
    }


def report(doc: dict[str, Any]) -> list[str]:
    """The read-back, one line per fact. A report that could not be read whole says why instead of printing figures."""
    env = _dict(doc.get("_envelope"))
    lines = [f"read at {_when(env.get('generated_at')) or 'an unrecorded time'}"
             + (f", app {env['app_version']}" if isinstance(env.get("app_version"), str) and _WORDS.fullmatch(env["app_version"]) else "")]
    docs, base = _int(doc.get("documents")), _int(doc.get("baselined"))
    lines.append(f"documents tracked: {_n(docs)}, with a baseline text: {_n(base)}" if docs is not None
                 else "documents tracked: not recorded in this file")
    cat = _dict(doc.get("catalog"))
    if cat.get("readable") is False:
        lines.append(f"catalogue: could not be read ({_words(cat.get('error'), 'no reason given')})")
    elif not cat:
        lines.append("catalogue: its state is not recorded in this file")
    lines += floor_lines(doc.get("floor"))
    lines += world_lines(doc.get("world"))
    en = _dict(doc.get("enumeration"))
    if not en:
        lines.append("official counts in the catalogue: absent from this file")
    elif en.get("state") == "unchecked":
        lines.append(f"official counts in the catalogue: not read: {_words(en.get('reason'), 'no reason given')}")
    else:
        lines.append(f"official counts in the catalogue: {_n(en.get('figures'))} for {_n(en.get('countries_with_an_official_count'))} countries,"
                     f" {_n(en.get('countries_enumerated_but_untracked'))} of them with nothing tracked")
    jur = doc.get("jurisdictions")
    if isinstance(jur, list):
        lines.append(f"jurisdictions with tracked documents: {len(jur)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("file", type=Path)
    ap.add_argument("--json", action="store_true", help="print the floor block as read (without the many-country sources' host names)")
    args = ap.parse_args(argv)
    try:
        doc = load(args.file)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"cannot read {args.file.name}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(json_floor(doc), indent=2, ensure_ascii=False))
    else:
        print("\n".join(report(doc)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
