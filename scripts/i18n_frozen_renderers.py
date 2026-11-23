#!/usr/bin/env python3
"""Which renderers leave translated text that a language switch can never change? (Lane O, row 352.)

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT CLASS. The i18n walker (``src/static/i18n.js`` ``doText``) records the first text it
sees on a node as "the English" and looks every later language up from it. It keeps out of any
node under ``[data-i18n-dyn]`` or ``[translate="no"]``. A renderer that writes ``t()``/``tf()``
output into an ordinary node therefore leaves ALREADY-TRANSLATED text there: that text matches
no key, so the next language switch leaves it as it is, and it stays in the first language until
the renderer happens to run again. Rows 347-351 fixed five such surfaces by hand; this script
finds the rest, and ``tests/test_i18n_frozen_renderers.py`` keeps the count from growing.

METHOD (source only; nothing is executed):

* Files: every ``src/static/*.js`` except ``i18n.js`` (the walker itself) and ``sw.js`` (the
  service worker). Sub-folders (vendor code, simple mode, the GUI skins) are not scanned.
* Lexing: comments are blanked before anything is matched, so a comment that SAYS
  ``data-i18n-dyn`` exempts nothing. String, template and regex TEXT is blanked for the call graph
  and for bracket matching, so ``onclick="showTab(...)"`` inside an HTML string is not a call;
  ``${...}`` inside a template stays code. A regex is told from a division by the token before it.
* Unit: a named function -- ``function f(``, ``async function f(``, ``const f = function(`` or an
  arrow with a braced body, ``const f = (...) => {`` / ``const f = x => {``. Its OWN body is its
  body with nested named units cut out, so each line belongs to one unit.
* Hit: a unit whose own code has BOTH a sink (``.innerHTML``/``.textContent``/``.innerText``/
  ``.outerHTML`` assigned with ``=`` or ``+=``, or ``.insertAdjacentHTML(``) AND a translator call
  (``t(``, ``tf(``, ``tr(``, ``trf(``, ``_t(``, ``_tf(``, ``_custT(``, ``OOI18N.t(``, ``OOI18N.tf(``).
* Exempt, any one of:
  1. the unit marks its output: ``setAttribute("data-i18n-dyn"``, ``dataset.i18nDyn``, or
     ``data-i18n-dyn`` inside an HTML tag in a string;
  2. the unit looks up an element that ``index.html`` marks ``data-i18n-dyn`` -- ``$("id")``,
     ``getElementById("id")`` or a ``"#id..."`` selector;
  3. the unit is REPAINTED: it is called within ``REPAINT_DEPTH`` (3) steps of a
     ``document.addEventListener("oo:langchange", ...)`` listener -- by the listener, by a function
     the listener calls, or one step beyond that. A listener registered by reference
     (``addEventListener("oo:langchange", paint)``) counts as calling it. Names resolve by scope,
     approximately: a name declared in the caller's own file means that file's unit(s), otherwise
     only TOP-LEVEL units of other files -- so a local ``paint()`` repainted in one file exempts
     nothing called ``paint`` in another.

WHY DEPTH 3 (measured on main ec444f9fa): depths 1-4 leave 363 / 314 / 299 / 292 hits. Depth 3
adds real repaint chains (``repaintLawEvolutionFromCache`` -> ``renderLawWeek``, ``renderBriefing``
-> ``renderCorpusTier``); depth 4 starts crediting paths that repaint nothing (``api()`` ->
``_noteReachable`` -> ``_paintHealth``, ``toggleNetwork`` -> ``ensureOnline``); the full closure
collapses into one cycle of ~390 functions through ``showTab``/``openAnalysis*`` (225 hits).

BLIND SPOTS -- absence of a hit is weaker evidence than a hit:

* Anonymous or method-style renderers (``x.render = function``, object and class methods),
  expression-bodied arrows and top-level code are not units; their sinks are charged to the
  enclosing named unit, if any, and otherwise not seen.
* A hit is unit-wide too: a sink and a ``t()`` call anywhere in the same unit count, even when
  they touch different things (``x.textContent = n; toast(t("Saved"))``) -- a false-positive
  source, so a listed unit may need reading before it is "fixed".
* Two same-named units in ONE file share their repaint credit (scope inside a file is not
  modelled), and a ``setAttribute("data-i18n-dyn")`` on some other element still exempts the unit.
* Translator aliases other than the ones listed are not seen, nor is output from a helper that
  calls ``t()`` itself (``custodyActionHtml(e.action, tr)``) unless a listed call is also in the unit.
* Exemption 2 is unit-wide: a unit that names one dyn id and also writes another, unmarked node
  is wrongly exempt.
* Exemption 3 is static reachability, not runtime: a repaint that reaches the unit only while a
  dialog is open is still credited, and a repaint deeper than 3 steps is missed (which COUNTS the
  unit -- the strict direction).
* Attributes (``title``, ``placeholder``, ``aria-label`` set from ``t()``) are not sinks; attribute
  freezes are a separate class.
* Sentences welded from fragments (row 347's class) are not detected, only frozen ones.
* A regex literal that fools the division heuristic (a regex right after ``)``, as in
  ``if (x) /re/.test(s)``, or a division right after ``++``) could misalign the lexer. That fails
  loudly -- the test asserts per-file bracket balance, and an unbalanced span raises -- but a
  misread span that happens to stay balanced would be blanked silently.

Usage:
    python scripts/i18n_frozen_renderers.py      # one "file name" line per hit, sorted
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "src" / "static"
SKIPPED_FILES = ("i18n.js", "sw.js")
REPAINT_DEPTH = 3

_REGEX_PREV = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_KEYWORDS = frozenset(
    (
        "return",
        "typeof",
        "case",
        "do",
        "else",
        "in",
        "of",
        "void",
        "delete",
        "throw",
        "new",
        "yield",
        "await",
    )
)
# Three declaration shapes: function f( / const f = function( / const f = (...) => {  (or x => {).
_DECL = re.compile(
    r"(?<![\w$.])(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\("
    r"|(?<![\w$.])(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?function\b[^(]*\("
    r"|(?<![\w$.])(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(\(|[A-Za-z_$][\w$]*\s*=>)"
)
_ARROW_BODY = re.compile(r"\s*=>\s*\{")
_DECL_HEADER = re.compile(r"function\s+[A-Za-z_$][\w$]*\s*\(")
_SINK = re.compile(
    r"\.(?:innerHTML|textContent|innerText|outerHTML)\s*\+?=(?!=)|\.insertAdjacentHTML\s*\("
)
_TRANSLATOR = re.compile(r"(?<![\w$.])(?:t|tf|tr|trf|_t|_tf|_custT)\s*\(|OOI18N\.tf?\s*\(")
# The tag form must also start inside string text (checked against the skeleton), so a
# comparison such as i<3 followed by a "[data-i18n-dyn]" selector is not read as a tag.
_MARKS_DYN = re.compile(r"setAttribute\(\s*[\"']data-i18n-dyn|dataset\.i18nDyn\s*=(?!=)")
_DYN_TAG = re.compile(r"<[A-Za-z][\w-]*\b[^<>`]*\bdata-i18n-dyn\b")
_CALL = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")
_WORD = re.compile(r"[A-Za-z_$][\w$]*")
_LISTENER = re.compile(r"addEventListener\(\s*[\"']oo:langchange[\"']")


@dataclass(frozen=True)
class Hit:
    file: str
    name: str
    line: int

    @property
    def key(self) -> str:
        return f"{self.file} {self.name}"


def lex(js: str) -> tuple[str, str]:
    """``(code, skel)`` of one JS source, both the same length as ``js`` with newlines kept.

    ``code`` has comments blanked. ``skel`` also has string, template and regex TEXT blanked
    (``${...}`` code inside a template is kept), so brackets and calls can be read from it.
    """
    n = len(js)
    code, skel = list(js), list(js)

    def wipe(arr: list[str], a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if arr[k] != "\n":
                arr[k] = " "

    def template(i: int, holes: list[int]) -> int:
        start = i
        while i < n:
            d = js[i]
            if d == "\\":
                i += 2
                continue
            if d == "`":
                wipe(skel, start, i)
                return i + 1
            if d == "$" and js[i + 1 : i + 2] == "{":
                wipe(skel, start, i)
                holes.append(0)
                return i + 2
            i += 1
        wipe(skel, start, n)
        return n

    def regex_may_start(i: int) -> bool:
        k = i - 1
        while k >= 0 and skel[k] in " \t\r\n":
            k -= 1
        if k < 0 or skel[k] in _REGEX_PREV:
            return True
        word = re.search(r"([A-Za-z_$][\w$]*)$", "".join(skel[max(0, k - 12) : k + 1]))
        return bool(word and word.group(1) in _REGEX_KEYWORDS)

    holes: list[int] = []  # brace depth inside each open ${ } of an enclosing template
    i = 0
    while i < n:
        c = js[i]
        if holes and c == "}" and holes[-1] == 0:
            holes.pop()
            i = template(i + 1, holes)
            continue
        if holes and c == "{":
            holes[-1] += 1
        elif holes and c == "}":
            holes[-1] -= 1
        if c in "'\"":
            j = i + 1
            while j < n and js[j] != c and js[j] != "\n":
                j += 2 if js[j] == "\\" else 1
            wipe(skel, i + 1, j)
            i = j + 1
            continue
        if c == "`":
            i = template(i + 1, holes)
            continue
        if js.startswith("//", i):
            j = js.find("\n", i)
            j = n if j == -1 else j
            wipe(code, i, j)
            wipe(skel, i, j)
            i = j
            continue
        if js.startswith("/*", i):
            j = js.find("*/", i + 2)
            j = n if j == -1 else j + 2
            wipe(code, i, j)
            wipe(skel, i, j)
            i = j
            continue
        if c == "/" and regex_may_start(i):
            j, in_class = i + 1, False
            while j < n and js[j] != "\n":
                if js[j] == "\\":
                    j += 2
                    continue
                if js[j] == "[":
                    in_class = True
                elif js[j] == "]":
                    in_class = False
                elif js[j] == "/" and not in_class:
                    break
                j += 1
            wipe(skel, i + 1, j)
            i = j + 1
            continue
        i += 1
    return "".join(code), "".join(skel)


def bracket_balance(skel: str) -> tuple[int, int, int]:
    """Open-minus-close counts of ``{``, ``(`` and ``[`` -- all zero when the lexer stayed aligned."""
    return (
        skel.count("{") - skel.count("}"),
        skel.count("(") - skel.count(")"),
        skel.count("[") - skel.count("]"),
    )


def _close(skel: str, at: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    for j in range(at, len(skel)):
        if skel[j] == open_ch:
            depth += 1
        elif skel[j] == close_ch:
            depth -= 1
            if depth == 0:
                return j
    raise ValueError(f"unbalanced {open_ch}{close_ch} from offset {at}")


def dyn_ids(index_html: str) -> set[str]:
    """Element ids that ``index.html`` marks ``data-i18n-dyn``."""
    tags = re.findall(r"<[^<>]*\bdata-i18n-dyn\b[^<>]*>", index_html)
    return {m.group(1) for t in tags for m in [re.search(r'\bid="([\w-]+)"', t)] if m}


def scan_sources(
    sources: dict[str, str], index_html: str = "", depth: int = REPAINT_DEPTH
) -> list[Hit]:
    """Every hit in ``sources`` (file name -> JS text), sorted by key."""
    units: list[dict] = []
    roots: set[int] = set()
    listener_bodies: list[tuple[str, str]] = []
    for fname, js in sources.items():
        code, skel = lex(js)
        for d in _DECL.finditer(skel):
            name = d.group(1) or d.group(2) or d.group(3)
            if d.group(1) or d.group(2):
                body_at = skel.index("{", _close(skel, d.end() - 1, "(", ")"))
            else:  # an arrow: only a braced body makes a unit
                after = _close(skel, d.start(4), "(", ")") + 1 if d.group(4) == "(" else d.end() - 2
                body = _ARROW_BODY.match(skel, after)
                if not body:
                    continue
                body_at = body.end() - 1
            units.append(
                {
                    "file": fname,
                    "name": name,
                    "a": body_at,
                    "e": _close(skel, body_at, "{", "}") + 1,
                    "line": js.count("\n", 0, d.start()) + 1,
                    "code": code,
                    "skel": skel,
                }
            )
        for m in _LISTENER.finditer(code):
            listener_bodies.append(
                (fname, skel[m.end() : _close(skel, code.index("(", m.start()), "(", ")")])
            )

    by_file: dict[str, list[dict]] = defaultdict(list)
    for u in units:
        by_file[u["file"]].append(u)
    for us in by_file.values():
        for u in us:
            inner = sorted(
                (v for v in us if v is not u and v["a"] > u["a"] and v["e"] <= u["e"]),
                key=lambda v: v["a"],
            )
            own_code, own_skel, cur = [], [], u["a"]
            for v in inner:
                if v["a"] < cur:
                    continue
                own_code.append(u["code"][cur : v["a"]])
                own_skel.append(u["skel"][cur : v["a"]])
                cur = v["e"]
            own_code.append(u["code"][cur : u["e"]])
            own_skel.append(u["skel"][cur : u["e"]])
            u["own_code"], u["own_skel"] = "".join(own_code), "".join(own_skel)

    # Names resolve by scope, approximately: a name declared in the caller's own file means that
    # file's unit(s); otherwise only TOP-LEVEL units of other files (a nested helper is local to
    # its file and can never be what another file calls). So a local paint() repainted in one
    # file exempts nothing called paint elsewhere.
    for i, u in enumerate(units):
        u["id"] = i
        u["nested"] = any(
            v is not u and v["a"] < u["a"] and u["e"] <= v["e"] for v in by_file[u["file"]]
        )
    local: dict[tuple[str, str], list[int]] = defaultdict(list)
    shared: dict[str, list[int]] = defaultdict(list)
    for u in units:
        local[(u["file"], u["name"])].append(u["id"])
        if not u["nested"]:
            shared[u["name"]].append(u["id"])

    def resolve(name: str, fname: str) -> list[int]:
        return local.get((fname, name)) or shared.get(name, [])

    calls: dict[int, set[int]] = defaultdict(set)
    for u in units:
        skel_calls = _DECL_HEADER.sub(lambda m: " " * len(m.group(0)), u["own_skel"])
        for c in set(_CALL.findall(skel_calls)):
            calls[u["id"]].update(resolve(c, u["file"]))
    for fname, listener in listener_bodies:  # a call, or a function handed over by reference
        for w in set(_WORD.findall(listener)):
            roots.update(resolve(w, fname))
    repainted, frontier = set(roots), set(roots)
    for _ in range(depth - 1):
        frontier = set().union(*(calls[x] for x in frontier)) - repainted if frontier else set()
        repainted |= frontier

    ids = dyn_ids(index_html)
    hits = []
    for u in units:
        own_code, own_skel = u["own_code"], u["own_skel"]
        if not (_SINK.search(own_skel) and _TRANSLATOR.search(own_skel)):
            continue
        if u["id"] in repainted or _MARKS_DYN.search(own_code):
            continue
        if any(own_skel[m.start()] == " " for m in _DYN_TAG.finditer(own_code)):
            continue
        if any(
            re.search(
                rf"(?:\$|getElementById)\(\s*[\"']{re.escape(i)}[\"']\s*\)|[\"']#{re.escape(i)}(?![\w-])",
                own_code,
            )
            for i in ids
        ):
            continue
        hits.append(Hit(u["file"], u["name"], u["line"]))
    return sorted(hits, key=lambda h: (h.key, h.line))


def static_sources(static_dir: Path = STATIC) -> dict[str, str]:
    """The scanned files: ``src/static/*.js`` minus ``SKIPPED_FILES``."""
    return {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted(static_dir.glob("*.js"))
        if p.name not in SKIPPED_FILES
    }


def scan(static_dir: Path = STATIC) -> list[Hit]:
    """Every hit in the shipped UI."""
    return scan_sources(
        static_sources(static_dir), (static_dir / "index.html").read_text(encoding="utf-8")
    )


def main() -> int:
    for h in scan():
        print(h.key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
