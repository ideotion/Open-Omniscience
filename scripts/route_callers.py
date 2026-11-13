#!/usr/bin/env python3
"""Which API routes does the shipped UI actually call? (Lane M, 2026-11-13.)

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A feature an ordinary person cannot click is a feature they do not have. In
November 2026 six climate fetchers and an Open-Meteo route were found built on
the server with no button anywhere; this script finds the next ones.

It works from SOURCE ONLY, never from the live ``app`` object (a positive read of
``src.api.main.app.routes`` made a route guard flaky in CI, see CLAUDE.md's
session rituals): every ``@router.<verb>("...")`` / ``@app.<verb>("...")`` under
``src/api`` is joined to its module's ``APIRouter(prefix=...)``; every string and
template literal under ``src/static`` (JS, HTML) and ``src/tui`` (the terminal
panel) is then matched against each route path, a ``{param}`` segment matching
anything and a ``${...}`` interpolation matching any one segment.

It is a HEURISTIC with a known bias: a URL assembled from pieces in separate
literals (``base + "/render"``) is not seen, so a route reported as UNCALLED must
be hand-checked before anyone acts on it. The opposite error is rarer: a literal
that names a path in a comment or a help string counts as a caller.

Usage:
    python scripts/route_callers.py            # table of uncalled routes
    python scripts/route_callers.py --all      # every route with its callers
    python scripts/route_callers.py --json     # machine-readable
"""

from __future__ import annotations

import argparse
import ast
import functools
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_DIR = ROOT / "src" / "api"
VERBS = {"get", "post", "put", "delete", "patch"}


@dataclass
class Route:
    method: str
    path: str
    file: str
    line: int
    callers: list[str] = field(default_factory=list)
    other: dict[str, list[str]] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _router_prefixes(tree: ast.Module) -> dict[str, str]:
    """``name -> prefix`` for every ``name = APIRouter(prefix=...)`` in a module."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        fn = node.value.func
        if not (isinstance(fn, ast.Name) and fn.id == "APIRouter"):
            continue
        prefix = ""
        for kw in node.value.keywords:
            if kw.arg == "prefix":
                prefix = _const_str(kw.value) or ""
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                out[tgt.id] = prefix
    return out


def collect_routes(api_dir: Path = API_DIR) -> list[Route]:
    """Every decorated route under ``api_dir``, read from source."""
    trees: dict[Path, ast.Module] = {}
    for py in sorted(api_dir.rglob("*.py")):
        trees[py] = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
    # A package may define its router once and share it (src/api/diagnostics/_base.py).
    pkg_prefix: dict[Path, dict[str, str]] = {}
    for py, tree in trees.items():
        pkg_prefix.setdefault(py.parent, {}).update(_router_prefixes(tree))
    routes: list[Route] = []
    for py, tree in trees.items():
        local = {**pkg_prefix.get(py.parent, {}), **_router_prefixes(tree)}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                verb = dec.func.attr
                owner = dec.func.value
                if verb not in VERBS or not isinstance(owner, ast.Name):
                    continue
                path = _const_str(dec.args[0]) if dec.args else None
                if path is None:
                    for kw in dec.keywords:
                        if kw.arg == "path":
                            path = _const_str(kw.value)
                if path is None:
                    continue
                if owner.id == "app":
                    prefix = ""
                elif owner.id in local:
                    prefix = local[owner.id]
                else:
                    continue  # not a FastAPI router (e.g. an unrelated .get decorator)
                routes.append(
                    Route(verb.upper(), prefix + path, str(py.relative_to(ROOT)), dec.lineno)
                )
    return routes


_HOLE = "\x01"  # one ${...} interpolation, after normalisation

# Where a caller lives decides what it proves. Only UI callers make a route reachable
# by an ordinary person; the others are recorded so a reader can see WHO uses it.
CALLER_KINDS: dict[str, tuple[str, ...]] = {
    "ui": ("src/static", "src/tui"),
    # the server hands these URLs to the UI inside a response (card links, deep links)
    "server-link": ("src",),
    "scripts": ("scripts", "install.sh", "install.ps1", "install-offline.sh", "Makefile"),
    "tests": ("tests",),
}
_SUFFIXES = {".js", ".html", ".py", ".sh", ".ps1", ""}


def _files(kind: str):
    for rel in CALLER_KINDS[kind]:
        base = ROOT / rel
        cands = [base] if base.is_file() else (sorted(base.rglob("*")) if base.is_dir() else [])
        for f in cands:
            if not f.is_file() or f.suffix not in _SUFFIXES or "vendor" in f.parts:
                continue
            r = str(f.relative_to(ROOT))
            if kind == "server-link" and r.startswith(("src/static/", "src/tui/")):
                continue  # static/tui are "ui"; src/api counts (diagnostics plans, bundle probes)
            if f.suffix == "" and f.name != "Makefile":
                continue
            yield r, f


@dataclass
class _FileLits:
    path: str
    lits: list[str]  # every literal, interpolations replaced by _HOLE
    tokens: set[str]  # every literal's raw text, for the composition rule


def _js_literals(text: str) -> list[str]:
    """String and template literals of a JS source, comments skipped.

    A naive quote regex desynchronises on the first apostrophe inside a comment
    ("don't") and silently loses every literal after it; this small scanner does
    not. A template's ``${...}`` becomes ``_HOLE`` (nested templates inside a hole
    are skipped with it). A ``/`` where an expression may start opens a regex
    literal, which is skipped (one with a quote in it would desynchronise too).
    """
    out: list[str] = []
    i, n = 0, len(text)
    prev = ""  # last significant character, to tell a regex from a division
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if (
            c == "/"
            and i + 1 < n
            and text[i + 1] not in "/*"
            and (
                prev == ""
                or prev in "(,=:[!&|?{};+-*%<>~^"
                or text[max(0, i - 7) : i].rstrip().endswith(("return", "typeof"))
            )
        ):
            j, in_class = i + 1, False
            while j < n and text[j] != "\n":
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "[":
                    in_class = True
                elif text[j] == "]":
                    in_class = False
                elif text[j] == "/" and not in_class:
                    break
                j += 1
            i, prev = j + 1, "x"
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c in "'\"":
            j, buf = i + 1, []
            while j < n and text[j] != c and text[j] != "\n":
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j : j + 2])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            out.append("".join(buf))
            i, prev = j + 1, "x"
            continue
        elif c == "`":
            j, buf = i + 1, []
            while j < n and text[j] != "`":
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j : j + 2])
                    j += 2
                elif text.startswith("${", j):
                    depth, j = 1, j + 2
                    while j < n and depth:
                        depth += {"{": 1, "}": -1}.get(text[j], 0)
                        j += 1
                    buf.append(_HOLE)
                else:
                    buf.append(text[j])
                    j += 1
            out.append("".join(buf))
            i, prev = j + 1, "x"
            continue
        else:
            prev = c
            i += 1
    return out


_SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)
_ATTR = re.compile(r"""\b[\w:-]+\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def _html_literals(text: str) -> list[str]:
    out: list[str] = []
    for m in _SCRIPT.finditer(text):
        out.extend(_js_literals(m.group(1)))
    for m in _ATTR.finditer(_SCRIPT.sub("", text)):
        out.append(m.group(1) if m.group(1) is not None else m.group(2))
    return out


def _py_literals(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            out.append(
                "".join(str(v.value) if isinstance(v, ast.Constant) else _HOLE for v in node.values)
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
    return out


def _shell_literals(text: str) -> list[str]:
    return [m.group(0) for m in re.finditer(r"/[\w./{}$-]+", text)]


_NESTED_WORD = re.compile(r"""['"]([\w-]+)['"]""")


def collect_literals(kind: str = "ui") -> list[_FileLits]:
    out: list[_FileLits] = []
    for rel, f in _files(kind):
        text = f.read_text(encoding="utf-8", errors="replace")
        if f.suffix == ".js":
            raw = _js_literals(text)
        elif f.suffix == ".html":
            raw = _html_literals(text)
        elif f.suffix == ".py":
            raw = _py_literals(text)
        else:
            raw = _shell_literals(text)
        lits = [x for x in raw if "/" in x]
        # quoted words nested inside markup strings count too: data-on-click="altAct(1,'keep')"
        nested = {w for x in raw for w in _NESTED_WORD.findall(x)}
        if lits:
            out.append(_FileLits(rel, lits, set(raw) | nested))
    return out


def _seg_rx(seg: str, tokens: set[str]) -> str:
    if seg.startswith("{") and seg.endswith("}"):
        return ".+" if ":path" in seg else "[^/?#]+"
    # a ${...} hole stands for a literal segment only when that segment is spelled
    # as a whole string elsewhere in the same file (a job-name table, a ternary)
    if seg in tokens:
        return "(?:" + re.escape(seg) + "|" + _HOLE + ")"
    return re.escape(seg)


@functools.cache
def _route_rx_cached(path: str, tokens: frozenset[str]) -> re.Pattern[str]:
    segs = [_seg_rx(s, set(tokens)) for s in path.strip("/").split("/")]
    return re.compile(
        r"(?:^|[^A-Za-z0-9_/.-])/" + "/".join(segs) + r"(?:$|[?#'\"\s]|/?$|" + _HOLE + ")"
    )


def _route_rx(path: str, tokens: set[str]) -> re.Pattern[str]:
    return _route_rx_cached(path, frozenset(s for s in path.strip("/").split("/") if s in tokens))


def _calls(path: str, fl: _FileLits) -> bool:
    if not path.strip("/"):
        return False
    rx = _route_rx(path, fl.tokens)
    for lit in fl.lits:
        if rx.search(" " + lit):
            return True
    # composition: "/api/integrity/collapse/" + (apply ? "apply" : "revert")
    segs = path.strip("/").split("/")
    for cut in range(1, len(segs)):
        head = "/" + "/".join(segs[:cut]) + "/"
        if "{" in head:
            break
        tail = "/".join(segs[cut:])
        if "{" in tail:
            continue
        if any(lit.endswith(head) for lit in fl.lits) and (
            tail in fl.tokens or "/" + tail in fl.tokens
        ):
            return True
    # a trailing parameter appended by concatenation: "/api/events/feeds/user/" + key
    if segs[-1].startswith("{") and len(segs) > 1:
        head_rx = re.compile(
            r"(?:^|[^A-Za-z0-9_/.-])/" + "/".join(_seg_rx(x, fl.tokens) for x in segs[:-1]) + "/$"
        )
        if any(head_rx.search(" " + lit) for lit in fl.lits):
            return True
    # a parameter spliced mid-path: "/api/custody/" + encodeURIComponent(id) + "/verify"
    for k, seg in enumerate(segs):
        rest = segs[k + 1 :]
        if not (seg.startswith("{") and rest) or any("{" in x for x in segs[:k] + rest):
            continue
        head = "/" + "/".join(segs[:k]) + "/"
        tail_rx = re.compile("^/" + re.escape("/".join(rest)) + r"(?:$|[?#]|" + _HOLE + ")")
        if any(lit.endswith(head) for lit in fl.lits) and (
            any(tail_rx.match(lit) for lit in fl.lits)
            # ... + "/" + verb, with the verb spelled as its own string in the file
            or (len(rest) == 1 and rest[0] in fl.tokens and "/" in fl.tokens)
        ):
            return True
    return False


def _seg_plain(seg: str) -> str:
    if seg.startswith("{") and seg.endswith("}"):
        return _HOLE  # a base handed across files carries its parameter as ${...}
    return "(?:" + re.escape(seg) + ")"


def _composed(path: str, files: list[_FileLits]) -> list[str]:
    """Callers that build the URL from a BASE handed across files.

    ``ooVersionReader(host, `/api/law/documents/${id}`)`` in one file, then
    ``${base}/versions`` (or ``URL + "/close-now"``) in another: the base literal must be EXACTLY a route
    prefix (the whole literal, so a stray mention does not count) and the tail
    must open a literal of its own. Weaker evidence than a whole URL; the report
    marks it so.
    """
    segs = path.strip("/").split("/")
    hits: set[str] = set()
    for cut in range(2, len(segs)):
        if all(x.startswith("{") for x in segs[cut:]):
            continue  # a bare-parameter tail would match any "${x}/${y}" literal
        head = re.compile("^/" + "/".join(_seg_plain(x) for x in segs[:cut]) + "$")
        tail = re.compile(
            "^"
            + _HOLE
            + "?/"
            + "/".join(_seg_plain(x) for x in segs[cut:])
            + r"(?:$|[?#]|"
            + _HOLE
            + ")"
        )
        base = [
            fl for fl in files if any(head.match(lit) for lit in fl.lits if lit.startswith("/"))
        ]
        if not base:
            continue
        # a ${base}/tail template may sit in another file (the base is handed over);
        # a plain "/tail" literal only counts beside its base, or "/cancel" anywhere
        # would vouch for every route that ends in /cancel
        held = [
            fl.path for fl in files if any(tail.match(lit) for lit in fl.lits if lit[:1] == _HOLE)
        ]
        same = [fl.path for fl in base if any(tail.match(lit) for lit in fl.lits if lit[:1] == "/")]
        if held or same:
            hits.update([fl.path for fl in base] + held + same)
    return sorted(hits)


def match_callers(routes: list[Route], files: list[_FileLits], kind: str = "ui") -> None:
    for r in routes:
        # PUT/PATCH/DELETE share paths with a GET; the file must at least spell the verb
        need = r.method if r.method in ("PUT", "PATCH", "DELETE") else None
        hits = sorted(
            {fl.path for fl in files if (need is None or need in fl.tokens) and _calls(r.path, fl)}
        )
        if not hits and kind == "ui":
            hits = [f + " (composed)" for f in _composed(r.path, files)]
        if kind == "ui":
            r.callers = hits
        else:
            r.other[kind] = hits


def build(kinds: tuple[str, ...] = ("ui",)) -> list[Route]:
    routes = collect_routes()
    for k in kinds:
        match_callers(routes, collect_literals(k), k)
    return routes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--all", action="store_true", help="list every route, called or not")
    ap.add_argument("--who", action="store_true", help="also name non-UI callers")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)
    routes = build(
        ("ui", "server-link", "scripts", "tests") if (a.all or a.json or a.who) else ("ui",)
    )
    shown = routes if a.all else [r for r in routes if not r.callers]
    if a.json:
        json.dump([r.__dict__ for r in shown], sys.stdout, indent=1)
        print()
        return 0
    for r in sorted(shown, key=lambda r: (r.path, r.method)):
        who = ", ".join(r.callers) if r.callers else "-"
        if a.who:
            who += "  | " + "; ".join(f"{k}: {','.join(v)}" for k, v in r.other.items() if v)
        print(f"{r.method:6} {r.path:70} {r.file}:{r.line}  {who}")
    print(
        f"\n{len(routes)} routes, {sum(1 for r in routes if not r.callers)} with no caller in src/static or src/tui"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
