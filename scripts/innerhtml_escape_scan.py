#!/usr/bin/env python3
"""Which HTML sinks in the static UI take a value that does not pass through ``esc()``? (Lane I, row 376, SEC-4.)

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE DEFECT CLASS. A value that reaches ``innerHTML`` (or ``outerHTML``, or ``insertAdjacentHTML``) is parsed as
HTML. Text that came from a feed, a page, a backup or the user, written there unescaped, can carry markup: an
``<img onerror>`` runs script in the app's origin, which holds the unlocked corpus and every local route. The app's
rule is to escape every such value with ``esc()`` (``app-core.js``; ``reader.js``, ``taskmanager.js`` and the GUI
gallery keep their own, ``unlock.js`` has ``escHtml``). Audit 17 (SEC-4) counted the sinks and could not say that
each one escapes. This scan cannot prove that either; what it does is name every sink whose right-hand side still
holds a value after the known-safe forms are taken out, so ``tests/test_innerhtml_escape_scan.py`` can hold that list
exactly (``configs/innerhtml_unescaped_sinks.txt``): a NEW sink with a raw value, in a new place or one more in a
listed place, fails, and a fixed one has to leave the list.

METHOD (source only; nothing is executed):

* Files: every ``.js`` under ``src/static`` (sub-folders included).
* Lexing: the row 352 lexer (``scripts/i18n_frozen_renderers.py`` ``lex``): comments are blanked, and string,
  template and regex TEXT is blanked, ``${...}`` code inside a template kept. So a comment or a string that SAYS
  ``esc(`` exempts nothing, and markup inside a string literal is never a value.
* Files: ``simple/vendor`` and ``guis/vendor`` (vendored, sha256-pinned) and the top-level ``sw.js`` are left out,
  by exact path.
* Sink: ``ooLiveHtml(el, render)`` (app-core.js, row 361), whose second argument is read like a right-hand side, an
  arrow's parameter list left out and its body (expression or block, every name in it) read whole; and
  ``.innerHTML`` / ``.outerHTML`` assigned with ``=``, ``+=``, ``||=``, ``&&=`` or ``??=``, or the arguments of
  ``.insertAdjacentHTML(``. The right-hand side runs to a ``;`` or ``,`` at its own depth, a bracket that closes past
  it, or a line end outside a template literal where the expression does not go on (neither the line's last character
  nor the next line's first is an operator); a template's own line breaks never end it (a security read of row 376).
* Taken out as safe, and nothing else:
  1. a call to an escaper, ``esc(...)`` or ``escHtml(...)`` (whatever its argument);
  2. ``t("...")`` / ``OOI18N.t("...")`` with one string literal: a translation of the app's own text (the locale
     files are repository content, as trusted as this source);
  3. ``.length`` and ``.toFixed(...)``, which give a number, with the expression they are read from
     (``rows.length``, ``(v * 100).toFixed(1)``).
  String and number literals are no values (their text is blanked by the lexer).
* Hit: a sink whose right-hand side still holds a name (an identifier other than a keyword or ``true``/``false``/
  ``null``/``undefined``). Hits are counted per unit -- the innermost named function around the sink (the row 352
  declaration shapes), or ``(top level)`` -- and the list holds one ``file unit count`` line per unit.

WHY A LIST AND NOT A PROOF. Most listed sinks are safe: the value is a string built a few lines up from escaped
parts (``el.innerHTML = rows``), a helper that escapes inside (``ooFetchedOffSiteNote(a)``), or a number. Reading that
needs data flow this scan does not do, so it stays strict -- it COUNTS what it cannot clear. The list is the record of
what has not been cleared by reading; a sink rewritten to escape at the point of writing leaves it.

BLIND SPOTS -- absence of a hit is weaker evidence than a hit:

* THE COUNT IS PER SINK, NOT PER VALUE: a raw value added to a sink that is already counted, or upstream into the
  variable a listed ``el.innerHTML = html`` writes, changes nothing. That is most listed units: the ratchet catches a
  new SINK with a raw value, not a new raw value in an old one.
* An escaper is recognised by its name: a parameter or local named ``esc`` that does not escape clears too. The test
  pins where ``esc``/``escHtml`` are defined, so a new definition is seen in review.

* A value escaped in the wrong context passes: ``esc()`` inside ``href="..."`` does not stop a ``javascript:`` URL,
  and ``escHtml`` (unlock.js) leaves ``'``, so it is not safe inside a single-quoted attribute. Context is not read.
* Any argument of ``esc()`` clears the call, and any ``t("...")`` clears, even where a locale string carries markup.
* ``tf(...)`` is always a value (its variables are inserted raw), even when every variable is a number.
* Sinks reached another way are not seen: ``document.write`` (one today, the print view in ``app-analysis.js``),
  ``DOMParser``, ``Range.createContextualFragment``, ``setHTMLUnsafe``/``setHTML``, ``srcdoc``, ``setAttribute("on...")``,
  ``Object.assign(el, {innerHTML})``, Alpine ``x-html`` or Preact ``dangerouslySetInnerHTML`` (none today), inline
  ``<script>`` in the ``.html`` files, or a property set through a computed name.
* ``t("...")`` clears however ``t`` is reached (``obj.t("a")`` too); the receiver's name is still counted.
* A name used only to choose between literals (``bad ? "<b>x</b>" : ""``) is counted like a value (the strict side).
* Attribute sinks (``href``, ``src``) and ``textContent`` are not sinks here: ``textContent`` cannot parse markup.
* The right-hand-side end is a heuristic; a statement continued in an unusual way (a line ending in a name and the
  next starting with ``[``) is cut short, which can only drop names (the lenient direction).
* The lexer's regex-versus-division guess can misalign on rare code; the test asserts per-file bracket balance.
* Units are named functions only; methods and anonymous callbacks are charged to the enclosing named function.

Usage:
    python scripts/innerhtml_escape_scan.py      # one "file unit count" line per unit, sorted
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from i18n_frozen_renderers import _DECL, _close, bracket_balance, lex  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "src" / "static"
#: Vendored code, sha256-pinned and read upstream (simple mode's Preact + htm, the GUI gallery's Alpine): exactly these
#: folders, so a hand-written file put in a new folder named "vendor" is still read. And the service worker.
VENDOR_DIRS = ("simple/vendor", "guis/vendor")
SKIPPED_FILES = ("sw.js",)
TOP = "(top level)"

_SINK = re.compile(r"\.(?:innerHTML|outerHTML)\s*(?:\+|\|\||&&|\?\?)?=(?!=)|\.insertAdjacentHTML\s*\(")
#: app-core.js's ooLiveHtml(el, render): it writes render()'s return into el.innerHTML now and again on a language switch
#: (row 361), so its second argument is a sink like an assignment's right-hand side.
_LIVE_HTML = re.compile(r"(?<![\w$.])(?<!function )ooLiveHtml\s*\(")
_ARROW_HEAD = re.compile(r"^\s*(?:async\s+)?(?:\([^()]*\)|[A-Za-z_$][\w$]*)\s*=>")
_ESCAPER = re.compile(r"(?<![\w$.])(?:esc|escHtml)\s*\(")
# One string literal (its text is already blanked in the skeleton, so only the quotes and spaces are left).
_T_LITERAL = re.compile(r"(?<![\w$])(?:OOI18N\.)?t\s*\(\s*([\"'`])\s*\1\s*\)")
_NUMERIC = re.compile(r"\.length\b|\.toFixed\s*\([^()]*\)")
_HOLE = re.compile(r"\$\{")  # the opening of a template hole: its code is read, its "$" is no name
_NAME = re.compile(r"(?<![\w$.])[A-Za-z_$][\w$]*")
_NOT_VALUES = frozenset(("true", "false", "null", "undefined", "typeof", "void", "new", "in", "instanceof"))
_GOES_ON_AFTER = set("+-*/%?:,(=&|[{")
_GOES_ON_BEFORE = set("+-*/%?:.&|)]")


@dataclass(frozen=True)
class Hit:
    file: str
    unit: str
    line: int


def _units(skel: str) -> list[tuple[int, int, str]]:
    """``(start, end, name)`` of each named function body (the row 352 declaration shapes)."""
    out = []
    for m in _DECL.finditer(skel):
        name = m.group(1) or m.group(2) or m.group(3)
        brace = skel.find("{", m.end() - 1)
        if brace == -1:
            continue
        if m.group(3):
            # an arrow unit has a braced body right after "=>"; an expression arrow is not a unit
            arrow = skel.find("=>", m.end() - 1)
            if arrow == -1 or skel[arrow + 2 : brace].strip():
                continue
        else:
            # the parameter list closes before the body opens
            paren = skel.find("(", m.start())
            try:
                brace = skel.find("{", _close(skel, paren, "(", ")"))
            except ValueError:
                continue
        try:
            out.append((brace, _close(skel, brace, "{", "}"), name))
        except ValueError:
            continue
    return out


def _unit_at(units: list[tuple[int, int, str]], at: int) -> str:
    best = None
    for start, end, name in units:
        if start < at < end and (best is None or start > best[0]):
            best = (start, name)
    return best[1] if best else TOP


def _rhs_end(skel: str, start: int) -> int:
    depth, i, n = 0, start, len(skel)
    in_template = False  # a template's text keeps its newlines: none of them ends the statement
    while i < n:
        c = skel[i]
        if c == "`" and depth == 0:
            in_template = not in_template  # a backtick inside a ${ } hole sits at depth 1 or more
        elif in_template and c not in "{}":
            pass
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif depth == 0 and c in ";,":
            return i
        elif depth == 0 and c == "\n":
            before = skel[start:i].rstrip()
            after = skel[i:].lstrip()
            if before and before[-1] not in _GOES_ON_AFTER and not (after and after[0] in _GOES_ON_BEFORE):
                return i
        i += 1
    return n


def _blank(text: str, a: int, b: int) -> str:
    return text[:a] + " " * (b - a) + text[b:]


def _receiver_start(text: str, at: int) -> int:
    """Where the expression ending at ``at`` starts: a dotted name, calls and indexes on it, or a bracketed group."""
    i = at
    while i > 0:
        c = text[i - 1]
        if c in ")]":
            depth, j = 0, i - 1
            while j >= 0:
                if text[j] in ")]":
                    depth += 1
                elif text[j] in "([":
                    depth -= 1
                    if depth == 0:
                        break
                j -= 1
            if j < 0:
                return i
            i = j
        elif c.isalnum() or c in "_$.":
            i -= 1
        else:
            break
    return i


def values_left(rhs: str) -> list[str]:
    """The names left in one right-hand side (skeleton text) once the safe forms are taken out."""
    while True:
        m = _ESCAPER.search(rhs)
        if not m:
            break
        rhs = _blank(rhs, m.start(), _close(rhs, m.end() - 1, "(", ")") + 1)
    for m in reversed(list(_NUMERIC.finditer(rhs))):  # the number and everything it is read from
        rhs = _blank(rhs, _receiver_start(rhs, m.start()), m.end())
    for rx in (_T_LITERAL, _HOLE):
        rhs = rx.sub(lambda m: " " * len(m.group(0)), rhs)
    return [w for w in _NAME.findall(rhs) if w not in _NOT_VALUES]


def scan_source(fname: str, js: str) -> list[Hit]:
    _code, skel = lex(js)
    units = _units(skel)
    hits = []
    for m in _SINK.finditer(skel):
        if m.group(0).endswith("("):
            end = _close(skel, m.end() - 1, "(", ")")
            rhs = skel[m.end() : end]
        else:
            rhs = skel[m.end() : _rhs_end(skel, m.end())]
        if values_left(rhs):
            hits.append(Hit(fname, _unit_at(units, m.start()), skel.count("\n", 0, m.start()) + 1))
    for m in _LIVE_HTML.finditer(skel):
        end = _close(skel, m.end() - 1, "(", ")")
        args = skel[m.end() : end]
        cut = _rhs_end(args, 0)  # the first argument (the element) ends at its own depth-0 comma
        if cut >= len(args) or args[cut] != ",":
            continue  # one argument only: nothing is rendered
        render = args[cut + 1 :]
        head = _ARROW_HEAD.match(render)
        if head:  # an arrow's parameters are no values; its body (an expression or a block) is read whole
            render = " " * head.end() + render[head.end() :]
        if values_left(render):
            hits.append(Hit(fname, _unit_at(units, m.start()), skel.count("\n", 0, m.start()) + 1))
    return hits


def static_sources(static_dir: Path = STATIC) -> dict[str, str]:
    """``relative path -> text`` of every scanned file."""
    out = {}
    for p in sorted(static_dir.rglob("*.js")):
        rel = p.relative_to(static_dir).as_posix()
        if any(rel.startswith(d + "/") for d in VENDOR_DIRS) or rel in SKIPPED_FILES:
            continue
        out[rel] = p.read_text(encoding="utf-8")
    return out


def scan(static_dir: Path = STATIC) -> list[Hit]:
    hits: list[Hit] = []
    for fname, js in static_sources(static_dir).items():
        hits.extend(scan_source(fname, js))
    return hits


def counted(hits: list[Hit]) -> list[str]:
    """One ``file unit count`` line per unit, sorted."""
    per = Counter((h.file, h.unit) for h in hits)
    return sorted(f"{f} {u} {n}" for (f, u), n in per.items())


def main() -> int:
    for line in counted(scan()):
        print(line)
    return 0


__all__ = ["Hit", "bracket_balance", "counted", "scan", "scan_source", "static_sources", "values_left"]

if __name__ == "__main__":
    raise SystemExit(main())
