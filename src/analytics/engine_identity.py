"""WHICH ENGINE produced an article's derived rows -- the per-article stamp R24 needs.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R24 (2026-09-22) rules that a same-engine backup carries its derived rows instead of
paying a re-extraction it does not need. That needs an answer to "same engine as
what?", and the tree had none: no version constant, no fingerprint, nothing in a
backup's manifest finer than ``app_version``. Three facts shaped the answer.

1. **ENGINE IDENTITY IS A PROPERTY OF EACH ARTICLE, NOT OF THE BACKUP.** A backup's
   manifest could only say which engine the exporting instance runs NOW. An instance
   that was upgraded half-way through its life holds rows from several engines under
   one version string, and nothing records which article came from which. So the
   stamp is a row in ``article_index_stamps``, written by ``index_article`` in the same
   pass as the rows it certifies -- never by the exporter, never copied by the merge.

1b. **...AND OF THE INPUTS IT READ.** Identical engines produce identical rows only from
   identical inputs, and an article's inputs can change after it is indexed without it
   being indexed again: a wiki body replaced, a country adopted from a later merge, a
   source renamed so its self-name suppression reads differently. So the stamp also
   records :func:`index_inputs_digest` of what the pass read, and a restore recomputes
   it from the incoming row. A stamp is then a statement that stays true for ever --
   "engine E, on inputs I, produced these rows" -- and nothing has to remember to
   invalidate it when an input moves.

2. **"THE ENGINE" IS MORE THAN THE CODE.** The same commit extracts differently on two
   machines when an optional dictionary is installed on one of them (``simplemma``
   lemmatises, ``jieba``/``janome``/``pythainlp`` segment zh/ja/th, ``py3langid``
   deduces a missing language, ``vaderSentiment`` scores English), when an operator
   flips one of the three switches, when a generated ``configs/cities.yml`` shadows
   the shipped sample gazetteer, or when the interpreter's Unicode tables differ
   (case-folding and ``\\w`` both read them). Every one of those is an input here.

3. **THE CODE IS VERSIONED BY HAND, AND THE HASH POLICES THE VERSION (R412, 2026-11-04,
   amends R24).** Until then the identity hashed the BYTES of the modules and data files a
   pass reads, so any change changed it with no one having to decide that it mattered.
   That was correct and too strict: two builds a day apart were "different engines" and
   every restore paid a full re-extraction. The identity now carries
   :data:`INDEXER_VERSION`, bumped by hand when what an engine file writes changes, and
   :func:`code_digest` -- still the hash of those files -- is kept as the POLICE: the pin
   ``configs/indexer_pin.json`` records the digest at the last bump or at the last
   judgement that a change left the output alone, and ``tests/test_indexer_pin.py`` is red
   whenever the digest has moved without the pin being re-recorded through
   ``scripts/indexer_pin.py``, which refuses to do it without a sentence saying WHAT changed
   (``--bump``) or WHY the output did not (``--same``). That sentence is the PR's statement.
   ``tests/test_index_engine_stamp.py`` runs a real pass in a fresh interpreter and
   fails if it loads a module or opens a data file the list does not name -- so the
   list cannot silently fall behind the code, which is the only way the police can lie.
   WHAT THE POLICE CANNOT DO: a ``--same`` recorded for a change that did change the output
   carries stale rows; the sentence and the review are the only defence there.

THE CARRY COMPARES AGAINST THE BASELINE IDENTITY ONLY. The post-merge re-index always
uses ``get_extractor("baseline")``, so the question a carry must answer is "would the
re-index this corpus is about to run reproduce these rows?" -- an article stamped by
any other extractor (spaCy at ingest) can never be carried, and should not be.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from functools import cache, lru_cache
from pathlib import Path

#: The identity's own format. Bump it only if the COMPONENTS below change shape, so an
#: old stamp can never collide with a new one computed from different inputs.
IDENTITY_SCHEMA = "oo-index-engine-2"

#: The hand-bumped version of what the engine files write (R412). Bump it, through
#: ``python scripts/indexer_pin.py --bump "what changed"``, whenever a change alters the
#: rows ``index_article`` produces for the same input; a change that provably leaves them
#: alone is recorded with ``--same "why"`` and leaves this number where it is, which is
#: the point -- the restore then still carries. The guard is ``tests/test_indexer_pin.py``.
INDEXER_VERSION = 1

#: The hand-bumped version of the PLACES AND ENTITIES stage alone (R415). Same discipline as :data:`INDEXER_VERSION`, policed by
#: ``configs/www_indexer_pin.json`` (``python scripts/indexer_pin.py --engine www --bump|--same "<sentence>"``). A change confined to
#: the www modules below bumps THIS number and leaves the keyword stamp where it is, so a restore still carries the keyword rows and
#: re-extracts only the places and entities.
WWW_INDEXER_VERSION = 1

#: The prefix every stamp carries. A stamp is ``e1-`` + 32 hex digits = 35 characters,
#: inside ``Article.index_engine``'s String(40).
STAMP_PREFIX = "e1-"

_REPO = Path(__file__).resolve().parents[2]

#: Every module whose code shapes what ``index_article`` writes: the keyword pass, the
#: language deduction, sentiment, the When x Where x Who stores and extractors, the
#: markup strip that runs before any of them, the country/city resolution, the source
#: self-name rule and the top-keyword arithmetic (both in ``store.py``). Measured, not
#: read: a fresh interpreter running one full pass per language loads exactly these,
#: plus the package ``__init__`` files and the modules in :data:`NOT_OUTPUT_AFFECTING`.
ENGINE_MODULES: tuple[str, ...] = (
    "src/analytics/__init__.py",
    "src/analytics/equivalence.py",
    "src/analytics/extract.py",
    "src/analytics/langdetect.py",
    "src/analytics/lemma.py",
    "src/analytics/managed.py",
    "src/analytics/reindex_parallel.py",
    "src/analytics/segmentation.py",
    "src/analytics/sentiment.py",
    "src/analytics/store.py",
    "src/analytics/vader_linear.py",
    "src/catalog/__init__.py",
    "src/catalog/aggregates.py",
    "src/catalog/cities.py",
    "src/catalog/countries.py",
    "src/services/__init__.py",
    "src/services/stopwords.py",
    "src/timemap/__init__.py",
    "src/timemap/dateextract.py",
    "src/timemap/datestore.py",
    "src/timemap/entextract.py",
    "src/timemap/locextract.py",
    "src/timemap/whostore.py",
    "src/utils/markup_blocks.py",
    "src/utils/safe_yaml.py",
)

#: The data files those modules read. ``cities.yml`` is GENERATED and preferred when
#: present; the sample is the shipped fallback -- both are hashed, present or absent,
#: so a machine that generated the full gazetteer is a different engine from one that
#: did not, which it is.
ENGINE_DATA_GLOBS: tuple[str, ...] = (
    "configs/stopwords_extra/*.yml",
    "configs/stopwords_iso/*.txt",
    # The shipped translation rings: which ring members a language keeps out of another
    # language's grammar list (R102) is decided from them, so they shape what a pass writes.
    "configs/keyword_equivalents.yml",
    "configs/keyword_rings_generated.yml",
    "configs/cities.yml",
    "configs/cities.sample.yml",
    # Built per install from the operator's own OSM data (scripts/build_place_gazetteer.py) and merged into the gazetteer by
    # ``load_cities`` (0.5 row C S4): an input that differs per install, so it is hashed at runtime, absent or not.
    "configs/places_gazetteer.yml",
)

#: The modules ONLY the places-and-entities stage reads (R415): nothing in the keyword pass or the date stage imports them
#: (measured by importing ``src.timemap.whostore`` and ``src.timemap.datestore`` in fresh interpreters). They leave the keyword
#: engine's code digest and form the www engine's.
WWW_ONLY_MODULES: tuple[str, ...] = (
    "src/catalog/cities.py",
    "src/timemap/entextract.py",
    "src/timemap/locextract.py",
    "src/timemap/whostore.py",
)

#: Modules the www stage reads that the keyword pass reads too: part of BOTH engines' code digests.
#: ``reindex_parallel.py`` is here because its ``_extract_www`` chooses the text and the source country the pooled path hands the
#: place and entity extractors. STATED LIMIT: ``store.py`` is NOT here (it is narrowed into the keyword digest only), so a change to
#: ``_index_article_www`` or the www half of ``index_article`` is a judgement the author makes by hand: bump WWW_INDEXER_VERSION.
WWW_SHARED_MODULES: tuple[str, ...] = (
    "src/catalog/__init__.py",
    "src/analytics/reindex_parallel.py",
    "src/catalog/aggregates.py",
    "src/catalog/countries.py",
    "src/timemap/__init__.py",
    "src/utils/safe_yaml.py",
)

#: The www stage's data: the gazetteers (``cities.yml`` is generated per install and shadows the sample; ``places_gazetteer.yml`` is
#: built per install from the operator's own OSM data).
WWW_DATA_GLOBS: tuple[str, ...] = (
    "configs/cities.yml",
    "configs/cities.sample.yml",
    "configs/places_gazetteer.yml",
)

#: Optional distributions whose presence or version changes extraction. Their data
#: files (simplemma's dictionaries, VADER's lexicon, jieba's dictionary) live inside
#: the distribution, so the version is what identifies them.
ENGINE_DISTRIBUTIONS: tuple[str, ...] = (
    "simplemma",
    "vaderSentiment",
    "py3langid",
    "jieba",
    "janome",
    "pythainlp",
    "spacy",
)

#: Modules a pass loads that do NOT shape its output, each with the reason. A module
#: in neither this map nor :data:`ENGINE_MODULES` fails the closure test -- the same
#: "a new thing must be triaged" rule the merge's completeness registries enforce.
NOT_OUTPUT_AFFECTING: dict[str, str] = {
    "src/analytics/baseline.py": (
        "baseline TAGS for a keyword the pass CREATES; a restore's keywords are created "
        "by the merge in both modes, so a carry and a re-index cannot differ here"
    ),
    "src/analytics/engine_identity.py": "this module; it computes the stamp, not the rows",
    "src/config/kv_store.py": (
        "the settings store; the country column type reads the store's country FORM through it when a pass binds "
        "a code. The form is a fact about the file, and the value a pass hands over is the same lowercase "
        "alpha-2 in either, so extraction writes nothing different"
    ),
    "src/database/connect.py": (
        "opens and snapshots database connections; it carries no extraction logic, so a change here can make "
        "no indexed article stale"
    ),
    "src/database/derived_views.py": (
        "the READ seam over the keyword rows (R96): a view listing the table's own columns, so a "
        "reader sees exactly the rows a pass wrote; it changes how they are read, never what "
        "extraction writes"
    ),
    "src/database/feed_key.py": (
        "derives sources.feed_key from a source's feed URL when a source row is written; an index pass reads "
        "sources and never writes them, so it cannot change what a pass writes"
    ),
    "src/database/outlet.py": (
        "names the OUTLET (a domain) a source belongs to, so a gate that states independence counts a site's "
        "feeds once; it only reads sources, so an index pass that loads it writes exactly what it wrote before"
    ),
    "src/database/open_stats.py": (
        "counts and times the keyed opens of the encrypted database file (a counter connect.py calls around an "
        "open; numbers and two closed vocabularies only); it sees no keyword row and writes nothing a pass reads, "
        "so a change here can make no indexed article stale"
    ),
    "src/database/stand_in.py": (
        "says which row is a salvage copy's PLACE-HOLDER (a lost article's stand-in has no text) so a pass "
        "leaves it out; a real article is written exactly as before, so a change here can make no indexed "
        "article stale"
    ),
    "src/monitoring/__init__.py": "the package engine_text lives in; no extraction code",
    "src/monitoring/engine_text.py": (
        "cleans an engine's error TEXT of the passphrase before it is stored or logged; it runs "
        "only on a failure and never changes the rows a pass writes"
    ),
    "src/monitoring/secret_scrub.py": (
        "takes the passphrase out of the text a log record, a report or a journal line is made of, and is the filter the logging "
        "setup (src/utils/logging_config.py, itself exempt) puts in front of its handlers; it never sees a keyword row and "
        "never changes one a pass writes"
    ),
    "src/services/duckduckgo.py": "imported by the services package; makes no call in a pass",
    "src/utils/logging_config.py": "log formatting only",
}

#: Files a pass opens that do not shape its output, by the same rule.
NOT_OUTPUT_AFFECTING_FILES: dict[str, str] = {
    "configs/keyword_baseline/": "baseline tags on keyword creation (see baseline.py above)",
    "audit/duckduckgo.log": "the services package's audit log, opened on import",
    # An editable install's own packaging records. importlib.metadata walks them when
    # this module asks for the ENGINE_DISTRIBUTIONS' versions; nothing extracts from them.
    "open_omniscience.egg-info/": "package metadata, read by importlib.metadata",
    "__editable__": "the editable install's import path hook",
}


def _read(rel: str) -> bytes | None:
    try:
        return (_REPO / rel).read_bytes()
    except OSError:
        return None


def engine_files() -> list[str]:
    """Every repo-relative file the closure test covers (code modules and data files), sorted -- the list is deterministic across
    machines and filesystems."""
    return sorted(set(ENGINE_MODULES) | set(_data_files()))


#: The one engine module whose bytes are NOT hashed whole: ``store.py`` is 2,700 lines and most of them (the drains, backfills,
#: reports, ``reindex_articles``) never shape what ``index_article`` writes, yet it changed in 24 of the ~40 commits that touched
#: any engine file in the 30 days to 2026-11-02 -- each one a new engine, so a backup rarely carried. Its identity is instead a
#: digest of the code ``index_article`` can REACH (see :func:`narrowed_source_digest`), and falls back to the whole file whenever
#: that cannot be established.
NARROWED_MODULES: dict[str, str] = {"src/analytics/store.py": "index_article"}

#: Names whose use makes a name-based reachability walk unsound (dynamic lookup): any of them in reachable code means the whole file.
_DYNAMIC_NAMES = frozenset({"globals", "locals", "vars", "eval", "exec", "__import__", "importlib", "compile"})
#: ``getattr``/``setattr``/``hasattr``/``delattr`` are fine when the attribute name is a string CONSTANT (the name then joins the
#: reachability walk like any other reference); a computed name could reach anything, so it means the whole file.
_ATTR_BUILTINS = frozenset({"getattr", "setattr", "hasattr", "delattr"})

def _is_repo_module(name: str) -> bool:
    base = name.replace(".", "/")
    return name.startswith("src.") and (_read(base + ".py") is not None or _read(base + "/__init__.py") is not None)


def _absolute(path: str, level: int, module: str) -> str:
    """The dotted name a (possibly relative) ``from <module> import`` in the repo file ``path`` refers to."""
    if not level:
        return module
    parts = path[:-3].split("/")
    pkg = parts if parts[-1] == "__init__" and parts.pop() else parts[:-1]
    base = pkg[: len(pkg) - (level - 1)] if level > 1 else pkg
    return ".".join([*base, module] if module else base)


def _imports_of(tree) -> list[tuple[int, str, list[str]]]:
    import ast

    out: list[tuple[int, str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((0, a.name, []) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.append((node.level, node.module or "", [a.name for a in node.names]))
    return out


def _module_tree(mod: str):
    import ast

    data = _read(mod.replace(".", "/") + ".py")
    if data is None:
        data = _read(mod.replace(".", "/") + "/__init__.py")
    if data is None:
        return None
    try:
        return ast.parse(data)
    except (SyntaxError, ValueError):
        return None


def _repo_module_refers_to(mod: str, own_module: str) -> bool:
    """Whether the repo module ``mod`` (dotted) imports ``own_module``, at any depth in any function: i.e. could call back into the
    narrowed file by name. Unreadable, unparsable or relative means yes (doubt keeps the whole file). The check is DIRECT, not
    transitive, on purpose: the repo's import graph is so connected that a transitive one always answers yes. What makes direct
    enough is ``tests/test_engine_identity_narrowed.py::test_no_module_a_pass_loads_imports_the_narrowed_file``, which loads a real
    pass in a fresh interpreter and requires that no module it executed imports the file."""
    tree = _module_tree(mod)
    if tree is None:
        return True
    path = mod.replace(".", "/") + ".py"
    if _read(path) is None:
        path = mod.replace(".", "/") + "/__init__.py"
    for level, name, from_names in _imports_of(tree):
        name = _absolute(path, level, name)
        targets = [name, *(f"{name}.{n}" for n in from_names if name)]
        for target in targets:
            if target == own_module:
                return True
    return False


def _strip_docstrings(tree) -> None:
    import ast

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = node.body
            first = body[0] if body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body = body[1:] or [ast.Pass()]


#: Method names that change the object they are called on (list, dict, set, deque and the like). A call to one on module-level data,
#: from a def the walk may not reach, changes what a reachable def reads. NAME-based and over-inclusive, like the rest.
_MUTATING_METHODS = frozenset(
    {"append", "extend", "insert", "add", "update", "pop", "popitem", "remove", "discard", "clear", "setdefault", "sort", "reverse",
     "appendleft", "extendleft", "popleft", "rotate", "difference_update", "intersection_update", "symmetric_difference_update"}
)


def narrowed_source_digest(source: bytes, root: str, *, extra_roots: frozenset[str] = frozenset(), own_module: str = "") -> str | None:
    """A digest of the part of ``source`` that ``root`` can reach, or ``None`` when that cannot be established soundly.

    NAME-BASED and deliberately over-inclusive: every top-level function, class or assignment whose name appears anywhere in a
    reachable node (a call, a default, a decorator, an annotation, a local that merely shares the name) is reachable. Over-inclusion
    costs a re-extraction; only UNDER-inclusion could carry a wrong row, so every doubt returns ``None`` and the caller hashes the whole
    file. ``None`` when: the source does not parse; ``root`` is not a top-level def; reachable code uses a dynamic lookup
    (:data:`_DYNAMIC_NAMES`); a reachable function imports a module that is not hashed on its own, or imports from ``own_module``
    itself; a decorator or base class is an attribute chain into the module's own names. Top-level statements that are not a
    def/class/assignment (imports, ``if``/``try`` blocks, expressions) are ALWAYS part of the digest, as are all top-level
    assignments, so a changed constant or import moves the identity whether or not anything reaches it. Docstrings and comments
    are not part of it (neither executes); line numbers are not either."""
    import ast

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    _strip_docstrings(tree)
    defs: dict[str, ast.AST] = {}
    always: list[ast.AST] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in defs:
                return None  # a redefinition: which one wins depends on order, so keep the file whole
            defs[node.name] = node
        else:
            always.append(node)
    if root not in defs:
        return None
    # FAIL-SAFES for state this name walk cannot follow. A ``global`` statement (``nonlocal`` only reaches an enclosing function, which is hashed with its def), or a store into an attribute or
    # subscript of a module-level name, lets a function that nothing reachable names change what a reachable one reads.
    module_names = set(defs)
    for top in always:
        for sub in ast.walk(top):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Store):
                module_names.add(sub.id)
    # Names bound by a top-level import are module-level state too (``os.environ`` is shared, mutable and read through an import).
    imported: set[str] = set()
    for top in always:
        for sub in ast.walk(top):
            if isinstance(sub, ast.Import):
                imported.update((a.asname or a.name.split(".")[0]) for a in sub.names)
            elif isinstance(sub, ast.ImportFrom):
                imported.update((a.asname or a.name) for a in sub.names)
    state_names = module_names | imported
    for dnode in defs.values():
        for dec in getattr(dnode, "decorator_list", []):
            # A decorator that is one of this module's own defs can register what it wraps somewhere the walk cannot see.
            head = dec.func if isinstance(dec, ast.Call) else dec
            while isinstance(head, (ast.Attribute, ast.Subscript, ast.Call)):
                head = head.func if isinstance(head, ast.Call) else head.value
            if isinstance(head, ast.Name) and head.id in module_names:
                return None
        for sub in ast.walk(dnode):
            if isinstance(sub, ast.Global):
                return None
            if isinstance(sub, ast.Call):
                fn = sub.func
                if isinstance(fn, ast.Name) and fn.id in ("setattr", "delattr"):
                    return None  # rebinding an attribute by name, in a def the walk may not reach
                if isinstance(fn, ast.Attribute) and fn.attr in _MUTATING_METHODS:
                    base = fn.value
                    while isinstance(base, (ast.Attribute, ast.Subscript)):
                        base = base.value
                    if isinstance(base, ast.Name) and base.id in state_names:
                        return None  # a mutation of module-level data, e.g. ``_CFG.update(...)``
            if isinstance(sub, (ast.Attribute, ast.Subscript)) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                base = sub.value
                while isinstance(base, (ast.Attribute, ast.Subscript)):
                    base = base.value
                if isinstance(base, ast.Name) and base.id in state_names:
                    return None
    # CALLERS TO A FIXPOINT: whatever calls the root chooses the arguments it is given (scope, country, extractor), and so does
    # whatever calls THAT. A caller is any def that names the root, a caller of it, ... by bare name or as ``module.name``.
    callers = {root}
    grew = True
    while grew:
        grew = False
        for dname, dnode in defs.items():
            if dname in callers:
                continue
            if any(
                (isinstance(sub, ast.Name) and sub.id in callers) or (isinstance(sub, ast.Attribute) and sub.attr in callers)
                for sub in ast.walk(dnode)
            ):
                callers.add(dname)
                grew = True
    # An alias or a table at top level (``f = index_article``) hides callers of the alias from the walk above: hash the file whole.
    for top in always:
        if isinstance(top, (ast.Import, ast.ImportFrom)):
            continue
        if any(
            (isinstance(sub, ast.Name) and sub.id in callers) or (isinstance(sub, ast.Attribute) and sub.attr in callers)
            for sub in ast.walk(top)
        ):
            return None
    reachable: dict[str, ast.AST] = {}
    # ROOTS: the root; every definition that NAMES the root (its callers feed it arguments it writes and certifies: the post-restore
    # re-index, the backfill, ...); every name a top-level statement mentions (a dispatch table, an alias, a decorator target, a
    # definition under a top-level ``if``/``try``); and what other engine modules import from this file.
    todo = [root, *sorted(n for n in extra_roots if n in defs)]
    todo.extend(sorted(callers - {root}))
    for top in always:
        for sub in ast.walk(top):
            if isinstance(sub, ast.Name) and sub.id in defs:
                todo.append(sub.id)
            elif isinstance(sub, ast.Attribute) and sub.attr in defs:
                todo.append(sub.attr)

    def _repo_import_ok(mod: str) -> bool:
        if mod.split(".")[0] in sys.stdlib_module_names or not mod.startswith("src."):
            return True  # the standard library and third-party packages cannot call a name of ours back
        # A repo module, hashed on its own or not: fine unless some chain of repo imports from it reaches this file.
        return not _repo_module_refers_to(mod, own_module)

    while todo:
        name = todo.pop()
        if name in reachable:
            continue
        target = defs[name]
        reachable[name] = target
        for sub in ast.walk(target):
            if isinstance(sub, ast.Name):
                if sub.id in _DYNAMIC_NAMES:
                    return None
                if sub.id in defs and sub.id not in reachable:
                    todo.append(sub.id)
            elif isinstance(sub, ast.Attribute):
                if sub.attr in _DYNAMIC_NAMES:
                    return None
                if sub.attr in defs and sub.attr not in reachable:
                    todo.append(sub.attr)  # `module.fn` style reference to one of our own names
            elif isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in _ATTR_BUILTINS:
                arg = sub.args[1] if len(sub.args) > 1 else None
                if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                    return None  # a computed attribute name could reach any of our names
                if arg.value in defs and arg.value not in reachable:
                    todo.append(arg.value)
            elif isinstance(sub, ast.Import):
                if not all(_repo_import_ok(alias.name) for alias in sub.names):
                    return None
            elif isinstance(sub, ast.ImportFrom):
                mod = ("." * sub.level) + (sub.module or "")
                if sub.level or mod == own_module or not _repo_import_ok(mod):
                    return None
    for top in always:
        for level, name, from_names in _imports_of(top):
            if level or not _repo_import_ok(name) or any(
                not _repo_import_ok(f"{name}.{n}") for n in from_names if _is_repo_module(f"{name}.{n}")
            ):
                return None
    h = hashlib.sha256()
    for top in always:
        h.update(ast.dump(top, include_attributes=False).encode())
        h.update(b"\x02")
    for name in sorted(reachable):
        h.update(name.encode())
        h.update(b"\x00")
        h.update(ast.dump(reachable[name], include_attributes=False).encode())
        h.update(b"\x03")
    return h.hexdigest()


def _names_other_engine_modules_take_from(rel: str) -> frozenset[str] | None:
    """The names of ``rel`` that OTHER engine modules import (they run inside a pass, so what they use is reachable), or ``None``
    when one of them reaches into it in a way a name list cannot capture (a module import, a relative import, an unparsable
    file) -- the caller then hashes the whole file."""
    import ast

    own = rel[:-3].replace("/", ".")
    parent, _, leaf = own.rpartition(".")
    names: set[str] = set()
    for other in ENGINE_MODULES:
        if other == rel or not other.endswith(".py"):
            continue
        data = _read(other)
        if data is None:
            continue
        try:
            tree = ast.parse(data)
        except (SyntaxError, ValueError):
            return None
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = _absolute(other, node.level, node.module or "")
                if module == own:
                    names.update(a.name for a in node.names)
                elif module == parent and any(a.name == leaf for a in node.names):
                    return None
            elif isinstance(node, ast.Import) and any(a.name == own for a in node.names):
                return None
    return frozenset(names)


def _engine_file_bytes(rel: str, data: bytes) -> bytes:
    """What the code digest hashes for ``rel``: its bytes, except a :data:`NARROWED_MODULES` file whose reachable-code digest could
    be established, which contributes that digest under a marker no whole file can start with."""
    root = NARROWED_MODULES.get(rel)
    if root is None:
        return data
    try:
        extra = _names_other_engine_modules_take_from(rel)
        digest = None if extra is None else narrowed_source_digest(
            data, root, extra_roots=extra, own_module=rel[:-3].replace("/", ".")
        )
    except Exception:  # noqa: BLE001 - any doubt hashes the whole file
        digest = None
    return data if digest is None else b"\x00narrowed:" + digest.encode()


def _expand(globs: tuple[str, ...]) -> list[str]:
    out: set[str] = set()
    for pattern in globs:
        if any(ch in pattern for ch in "*?["):
            out.update(str(p.relative_to(_REPO)) for p in _REPO.glob(pattern) if p.is_file())
        else:
            out.add(pattern)
    return sorted(out)


def _data_files() -> list[str]:
    """Every data file either engine reads."""
    return _expand(ENGINE_DATA_GLOBS)


def _kw_data_files() -> list[str]:
    return sorted(set(_data_files()) - set(_expand(WWW_DATA_GLOBS)))


def _kw_modules() -> list[str]:
    return sorted(set(ENGINE_MODULES) - set(WWW_ONLY_MODULES))


def _www_modules() -> list[str]:
    return sorted(set(WWW_ONLY_MODULES) | set(WWW_SHARED_MODULES))


def _digest_of(files: list[str], *, narrow: bool) -> str:
    """sha256 over (path, bytes) of ``files``. A MISSING file contributes its name and an explicit absence marker rather than nothing,
    so "absent" and "empty" are different and a deleted gazetteer cannot hash like an untouched one. Line endings are normalised
    (``\\r\\n`` to ``\\n``): a Windows checkout with autocrlf must not hash differently from the same commit on Linux."""
    h = hashlib.sha256()
    for rel in files:
        data = _read(rel)
        h.update(rel.encode())
        h.update(b"\x00")
        if data is None:
            h.update(b"<absent>")
        else:
            if narrow:
                data = _engine_file_bytes(rel, data)
            data = data.replace(b"\r\n", b"\n")
            h.update(str(len(data)).encode())
            h.update(b"\x00")
            h.update(data)
        h.update(b"\x01")
    return h.hexdigest()


@lru_cache(maxsize=1)
def code_digest() -> str:
    """The hash of the KEYWORD engine's CODE modules (:data:`ENGINE_MODULES` without :data:`WWW_ONLY_MODULES`). Since R412 it is not
    part of the identity: it is what ``configs/indexer_pin.json`` and ``tests/test_indexer_pin.py`` police the hand-bumped
    :data:`INDEXER_VERSION` with.

    Cached for the process: the files a running app extracts with do not change under it, and a pass must not re-read ~200 files
    per article."""
    return _digest_of(_kw_modules(), narrow=True)


@lru_cache(maxsize=1)
def www_code_digest() -> str:
    """The hash of the places-and-entities stage's code (R415), policing :data:`WWW_INDEXER_VERSION` through
    ``configs/www_indexer_pin.json``."""
    return _digest_of(_www_modules(), narrow=False)


@lru_cache(maxsize=1)
def data_digest() -> str:
    """The hash of the KEYWORD engine's DATA files (stoplists, rings), computed at runtime on every install and part of the identity: a
    data file can differ per install, so it cannot be versioned by hand. The gazetteers belong to the www engine (:func:`www_data_digest`)."""
    return _digest_of(_kw_data_files(), narrow=False)


@lru_cache(maxsize=1)
def www_data_digest() -> str:
    """The hash of the www stage's gazetteers: ``configs/cities.yml`` is generated on the operator's machine and shadows the shipped
    sample, and ``configs/places_gazetteer.yml`` is built from their own OSM data, so a machine that has them is a different www engine."""
    return _digest_of(_expand(WWW_DATA_GLOBS), narrow=False)


@cache
def _dist_version(dist: str) -> str | None:
    """The installed version of one distribution, or None when it is absent."""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - stdlib on every supported Python
        return None
    try:
        return version(dist)
    except PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - a broken metadata record is an unknown, not a crash
        return "<unreadable>"


def _switches() -> dict[str, bool]:
    """The three operator switches that change what a pass writes, read LIVE through
    the very predicates extraction itself consults -- never re-derived here, so the
    identity and the extraction cannot disagree about whether a switch is on."""
    from src.analytics.extract import code_token_filter_enabled
    from src.analytics.lemma import extraction_lemma_enabled
    from src.analytics.segmentation import _enabled as segmentation_enabled

    return {
        "lemma": bool(extraction_lemma_enabled()),
        "segmentation": bool(segmentation_enabled()),
        "code_token_filter": bool(code_token_filter_enabled()),
    }


def _gazetteer_digest(extractor) -> str | None:
    gaz = getattr(extractor, "gazetteer", None) or getattr(
        getattr(extractor, "_baseline", None), "gazetteer", None
    )
    if not gaz:
        return None
    blob = json.dumps(sorted(gaz.items()), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def engine_components(extractor=None, *, extractor_name: str | None = None) -> dict:
    """The inputs the stamp is a hash of, readable -- for a diagnostic that has to say
    WHY two stamps differ, not only that they do."""
    name = extractor_name or getattr(extractor, "name", None) or "baseline"
    return {
        "schema": IDENTITY_SCHEMA,
        "extractor": name,
        "gazetteer": _gazetteer_digest(extractor) if extractor is not None else None,
        "indexer": INDEXER_VERSION,
        "data": data_digest(),
        "distributions": {d: _dist_version(d) for d in ENGINE_DISTRIBUTIONS},
        "switches": _switches(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "unicode": unicodedata.unidata_version,
    }


@lru_cache(maxsize=64)
def _stamp_for(blob: str) -> str:
    return STAMP_PREFIX + hashlib.sha256(blob.encode()).hexdigest()[:32]


def engine_id(extractor=None, *, extractor_name: str | None = None) -> str:
    """The stamp for the engine that would run with ``extractor`` right now."""
    blob = json.dumps(
        engine_components(extractor, extractor_name=extractor_name),
        sort_keys=True,
        separators=(",", ":"),
    )
    return _stamp_for(blob)


def baseline_engine_id() -> str:
    """The identity a post-merge re-index would stamp -- what a carry must match."""
    return engine_id(extractor_name="baseline")


#: The www stage's own format and stamp prefix (``w1-`` + 32 hex digits = 35 characters, inside ``article_www_stamps.engine``).
WWW_IDENTITY_SCHEMA = "oo-www-engine-1"
WWW_STAMP_PREFIX = "w1-"
#: The prefix of a www inputs digest (``wi1-`` + 32 hex digits = 36 characters).
WWW_INPUTS_PREFIX = "wi1-"


def www_engine_components() -> dict:
    """What the PLACES-AND-ENTITIES stamp is a hash of, readable. Neither extractor consults an operator switch or an optional
    dictionary; the interpreter's Unicode tables and ``\\w`` do reach them, so those stay in."""
    return {
        "schema": WWW_IDENTITY_SCHEMA,
        "indexer": WWW_INDEXER_VERSION,
        "data": www_data_digest(),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "unicode": unicodedata.unidata_version,
    }


def www_engine_id() -> str:
    """The stamp for the places-and-entities engine that would run right now (R415)."""
    blob = json.dumps(www_engine_components(), sort_keys=True, separators=(",", ":"))
    return WWW_STAMP_PREFIX + hashlib.sha256(blob.encode()).hexdigest()[:32]


def www_inputs_digest(*, raw_content: str | None, country: str | None) -> str:
    """A hash of EVERYTHING the places and entities stores read from one article (R415): the ``content`` COLUMN (not the decompressed
    text -- the stores read the column directly, so a compressed article shows them an empty body) and the article's own ``country``
    (the place extractor's ``source_country``). ONE function for both sides of the comparison, as :func:`date_part` is: the merge
    imports this to recompute it from an incoming row."""
    payload = {
        "raw": hashlib.sha256((raw_content or "").encode("utf-8", "surrogatepass")).hexdigest(),
        "country": country or "",
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return WWW_INPUTS_PREFIX + hashlib.sha256(blob.encode("utf-8", "surrogatepass")).hexdigest()[:32]


#: The prefix every inputs digest carries (``i1-`` + 32 hex digits = 35 characters).
INPUTS_PREFIX = "i1-"


def date_part(value) -> str | None:
    """The calendar date of a stored timestamp, as ``YYYY-MM-DD``, or None.

    One function for both sides of the comparison, because the two sides hold the value
    differently: ``index_article`` has the ORM's ``datetime``, the restore reads the raw
    column through sqlite3 and gets the stored text. Only the DATE matters -- it is what
    ``observed_on`` and the date extractor's anchor are made of -- so a time-of-day edit
    is not an input change."""
    if value is None:
        return None
    if hasattr(value, "date") and callable(value.date):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    if len(text) < 10:
        return None
    try:
        from datetime import date

        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def index_inputs_digest(
    *,
    text: str,
    raw_content: str | None,
    title: str | None,
    language: str | None,
    detected_language: str | None,
    observed: str | None,
    country: str | None,
    self_forms,
) -> str:
    """A hash of EVERYTHING one article contributes to what ``index_article`` writes.

    Each field is here because a reader of it was found, not because it seemed wise:

      * ``text`` -- the article text the keyword pass, sentiment and the language
        deduction read (``get_content()``: decompressed when stored compressed);
      * ``raw_content`` -- the ``content`` COLUMN, which the date, place and entity
        stores read directly instead of ``get_content()``. The two differ exactly when
        an article is stored compressed, and then those stores see an empty body;
      * ``title`` -- passed to the extractor beside the text;
      * ``language`` and ``detected_language`` -- both, raw: the keyword pass reads the
        first non-empty one, the date extractor reads ``language`` alone;
      * ``observed`` -- the date of ``published_at or created_at``: every mention's
        ``observed_on``, and the anchor that resolves "yesterday";
      * ``country`` -- the article's own, raw: the place extractor's ``source_country``,
        and what a re-index denormalises onto each mention;
      * ``self_forms`` -- the source's self-name forms, the words the keyword pass
        suppresses as the source naming itself. They come from the SOURCE row, so an
        article merged onto a differently-named local source has different inputs.
    """
    payload = {
        "text": hashlib.sha256((text or "").encode("utf-8", "surrogatepass")).hexdigest(),
        "raw": hashlib.sha256((raw_content or "").encode("utf-8", "surrogatepass")).hexdigest(),
        "title": title or "",
        "language": language or "",
        "detected_language": detected_language or "",
        "observed": observed,
        "country": country or "",
        "self_forms": sorted(self_forms or ()),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return INPUTS_PREFIX + hashlib.sha256(blob.encode("utf-8", "surrogatepass")).hexdigest()[:32]
