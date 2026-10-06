"""No fast hash is ever fed the passphrase: the walk that holds the next key derivation to what the cache's now is.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE FAILURE IT HOLDS OFF. The columnar cache's key was ``sha256("oo-columnar-v1:" + passphrase)``: one fast hash of the
ONE passphrase that opens everything, the shape CodeQL's ``py/weak-sensitive-data-hashing`` names, and a cheaper offline
attack on that passphrase than the corpus itself (SQLCipher 4 stretches with PBKDF2-HMAC-SHA512 at 256,000 rounds). It is
now stretched the same way (``columnar._derive_key``, pinned in ``tests/test_columnar_key_derivation.py``); this walk is
the net beneath that: the next module that hashes a passphrase with ``hashlib.sha256`` fails here, with the line, before
CodeQL or a person has to find it.

WHAT IT READS. The syntax of every ``.py`` file under ``src/`` and ``scripts/``. A call is a FAST hash when it is a
``hashlib`` constructor other than the two stretching functions (``pbkdf2_hmac``, ``scrypt``), ``hmac.new``,
``hmac.digest`` or ``hmac.HMAC``, or the ``update`` of a hash object the same scope made (``h = hashlib.sha256()`` ...
``h.update(x)``; ``hashlib.sha256().update(x)``). It is FLAGGED when anything in its arguments is, or was made from, a
name the code uses for the passphrase: an identifier (a name, an attribute, a keyword, a string key of a subscript or of
``.get``/``getenv``) one of whose words (split on ``_`` and on a lower-to-upper change) is ``passphrase``, ``password``,
``passwd``, ``passcode``, ``pwd``, ``pw`` or ``secret``. "Made from" is followed inside one function (or the module's own
statements): ``raw = ("x:" + passphrase).encode()`` taints ``raw``, so ``hashlib.sha256(raw)`` is flagged, and so is
what is read through a ``with open(passphrase_file) as fh``. The stretching functions are NOT flagged (they are what the
rule asks for), but are counted, so that the tests can see the walk reads the real derivation.

WHAT STAYS OUTSIDE, stated so that nobody reads a green run as more than it is:

* It reads names, not values. A passphrase that reaches a hash under a name that does not say what it is (``key``,
  ``s``, ``self._x``), through a helper's return value that is hashed in ANOTHER function, through a closure, through
  ``getattr``, ``**kwargs`` or a container built elsewhere, or as a hash object passed in as a parameter (``def f(h,
  pw): h.update(pw)``), is not seen. The plural ``secrets`` is not a word (it is the standard module); ``phrase`` is not
  (the text analysis uses it for word groups); ``token`` is not.
* It reads Python under ``src/`` and ``scripts/``. The pages (``src/static``) were searched by hand when this was
  written for a digest call (``crypto.subtle.digest`` or a hash routine) and hold none; nothing walks them. Tests are not
  read: they hash passphrases to build expected answers.
* Only ``hashlib`` and ``hmac`` are sinks. Another fast-hash library (``cryptography``'s ``hashes.Hash``, ``zlib.crc32``,
  the built-in ``hash``) is not, and none is fed a passphrase today.
* It separates FAST hashes from the two stretching functions of ``hashlib``; it does not say a stretching call is strong
  enough. The round count of the cache's key is read off SQLCipher itself in ``tests/test_columnar_key_derivation.py``.

THE LIST OF ALLOWED CALLS IS EMPTY AND STAYS THAT WAY unless a ruling says otherwise: a fast hash of a passphrase has no
use the stretching functions do not serve, and a "fingerprint of the passphrase to tell whether it changed" is the same
offline attack with a friendlier name.
"""

from __future__ import annotations

import ast
import functools
import re
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SCANNED = ("src", "scripts")

#: The words that say a name is the passphrase (see the module docstring for what is and is not one).
_SECRET_WORDS = frozenset({"passphrase", "password", "passwd", "passcode", "pwd", "pw", "secret"})
_CASE_CHANGE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

#: ``hashlib``'s two stretching functions: what a passphrase SHOULD go through, so never flagged.
_STRETCHING = frozenset({"pbkdf2_hmac", "scrypt"})
#: ``hmac``'s callables that compute a keyed hash (``compare_digest`` compares two values and hashes nothing).
_HMAC_SINKS = frozenset({"new", "digest", "HMAC"})
#: The calls on a mapping-looking receiver that read a value by its string key, which can name the passphrase.
_KEYED_READS = frozenset({"get", "getenv", "pop", "setdefault"})


class Hit(NamedTuple):
    """One call that hashes: what it is, where, the passphrase-like name its arguments reach (None when none), and
    whether it is one of the stretching functions."""

    label: str
    line: int
    mention: str | None
    stretching: bool


def _is_secret_name(name: str) -> bool:
    return any(word in _SECRET_WORDS for word in _CASE_CHANGE.sub("_", name).lower().split("_"))


def _first_mention(node: ast.AST, tainted: set[str]) -> str | None:
    """The first name in ``node`` that is the passphrase or was made from it (``tainted``), or None."""
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            if n.id in tainted or _is_secret_name(n.id):
                return n.id
        elif isinstance(n, ast.Attribute):
            if f".{n.attr}" in tainted or _is_secret_name(n.attr):
                return n.attr
        elif isinstance(n, ast.keyword):
            if n.arg and _is_secret_name(n.arg):
                return n.arg
        elif isinstance(n, ast.Subscript):
            key = n.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str) and _is_secret_name(key.value):
                return repr(key.value)
        elif isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant):
            key = n.args[0].value
            f = n.func
            reader = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            if reader in _KEYED_READS and isinstance(key, str) and _is_secret_name(key):
                return repr(key)
    return None


def _targets(target: ast.AST) -> list[str]:
    """The names an assignment target binds: ``x``, an attribute as ``.x``, each element of a tuple or list."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [f".{target.attr}"]
    if isinstance(target, (ast.Tuple, ast.List)):
        return [name for element in target.elts for name in _targets(element)]
    if isinstance(target, ast.Starred):
        return _targets(target.value)
    return []


def _own_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """Every node of ``scope`` that is not inside a scope nested in it (a nested function, lambda or class is its own)."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(node))


def _tainted(nodes: list[ast.AST]) -> set[str]:
    """The names a scope makes from the passphrase, to a fixed point (a copy of a copy is a copy)."""
    tainted: set[str] = set()
    changed = True
    while changed:
        changed = False
        for n in nodes:
            pairs: list[tuple[ast.AST, ast.AST]] = []
            if isinstance(n, ast.Assign):
                pairs = [(t, n.value) for t in n.targets]
            elif isinstance(n, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)) and n.value is not None:
                pairs = [(n.target, n.value)]
            elif isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension)):
                pairs = [(n.target, n.iter)]
            elif isinstance(n, ast.withitem) and n.optional_vars is not None:
                pairs = [(n.optional_vars, n.context_expr)]
            for target, value in pairs:
                if _first_mention(value, tainted) is None:
                    continue
                for name in _targets(target):
                    if name not in tainted:
                        tainted.add(name)
                        changed = True
    return tainted


def _imports(tree: ast.AST) -> tuple[dict[str, str], dict[str, str]]:
    """``(modules, names)``: the local name each ``hashlib``/``hmac`` import goes by (``import hashlib as hl`` ->
    ``{"hl": "hashlib"}``) and the ``hashlib``/``hmac`` function each ``from`` import brings in (``from hashlib import
    sha1 as s`` -> ``{"s": "hashlib.sha1"}``), wherever in the file the import is."""
    modules: dict[str, str] = {}
    names: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for alias in n.names:
                if alias.name in ("hashlib", "hmac"):
                    modules[alias.asname or alias.name] = alias.name
        elif isinstance(n, ast.ImportFrom) and n.module in ("hashlib", "hmac"):
            for alias in n.names:
                names[alias.asname or alias.name] = f"{n.module}.{alias.name}"
    return modules, names


def _callee(func: ast.expr, modules: dict[str, str], names: dict[str, str]) -> tuple[str, bool] | None:
    """``(label, is_a_stretching_function)`` for a call of ``hashlib`` or ``hmac``, or None for any other callee."""
    qualified = None
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in modules:
        qualified = f"{modules[func.value.id]}.{func.attr}"
    elif isinstance(func, ast.Name) and func.id in names:
        qualified = names[func.id]
    if qualified is None:
        return None
    module, _, attr = qualified.partition(".")
    if module == "hashlib":
        return qualified, attr in _STRETCHING
    return (qualified, False) if attr in _HMAC_SINKS else None


def hash_calls(source: str) -> list[Hit]:
    """Every call in ``source`` that hashes (a fast hash, an ``update`` of a hash object, a stretching function) with the
    passphrase-like name its arguments reach. Raises ``SyntaxError`` for a file that does not parse."""
    tree = ast.parse(source)
    modules, names = _imports(tree)
    scopes = [tree, *(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)))]

    def hash_objects(nodes: list[ast.AST]) -> set[str]:
        made: set[str] = set()
        for n in nodes:
            value = getattr(n, "value", None)
            if isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(value, ast.Call):
                callee = _callee(value.func, modules, names)
                if callee and not callee[1]:
                    for target in n.targets if isinstance(n, ast.Assign) else [n.target]:
                        made.update(_targets(target))
        return made

    # An attribute (``self._h``) is made in one method and updated in another, so those are read across the whole file.
    attribute_hashes = {name for scope in scopes for name in hash_objects(list(_own_nodes(scope))) if name.startswith(".")}
    hits: list[Hit] = []
    for scope in scopes:
        nodes = list(_own_nodes(scope))
        tainted = _tainted(nodes)
        objects = hash_objects(nodes) | attribute_hashes
        for n in nodes:
            if not isinstance(n, ast.Call):
                continue
            callee = _callee(n.func, modules, names)
            if callee is None and isinstance(n.func, ast.Attribute) and n.func.attr == "update":
                receiver = n.func.value
                made = isinstance(receiver, ast.Call) and (_callee(receiver.func, modules, names) or ("", True))[1] is False
                tracked = (isinstance(receiver, ast.Name) and receiver.id in objects) or (
                    isinstance(receiver, ast.Attribute) and f".{receiver.attr}" in objects
                )
                if made or tracked:
                    callee = ("hash.update", False)
            if callee is None:
                continue
            mention = next(
                (m for arg in (*n.args, *(k.value for k in n.keywords)) if (m := _first_mention(arg, tainted)) is not None),
                None,
            )
            if mention is None:
                mention = next((k.arg for k in n.keywords if k.arg and _is_secret_name(k.arg)), None)
            hits.append(Hit(callee[0], n.lineno, mention, callee[1]))
    return hits


def fast_hashes_of_the_passphrase(source: str) -> list[Hit]:
    """The calls the guard flags: a fast hash whose arguments reach the passphrase."""
    return [hit for hit in hash_calls(source) if hit.mention is not None and not hit.stretching]


# --------------------------------------------------------------------------------------------------------------------
# The tree
# --------------------------------------------------------------------------------------------------------------------
def walk_files(paths: list[Path], root: Path) -> tuple[dict[str, list[Hit]], dict[str, str]]:
    """``(hits, unreadable)`` for ``paths``, by path relative to ``root``: what each file's walk found, and for a file that
    does not parse why. A file that does not parse is REPORTED, never skipped: a file the walk cannot read is a file it
    does not guard."""
    hits: dict[str, list[Hit]] = {}
    unreadable: dict[str, str] = {}
    for path in paths:
        rel = path.relative_to(root).as_posix()
        try:
            hits[rel] = hash_calls(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            unreadable[rel] = exc.msg
    return hits, unreadable


@functools.lru_cache(maxsize=1)
def _tree() -> tuple[dict[str, list[Hit]], dict[str, str]]:
    """``walk_files`` over every ``.py`` file under ``src/`` and ``scripts/``, read once for the tests below."""
    return walk_files(sorted(path for base in _SCANNED for path in (ROOT / base).rglob("*.py")), ROOT)


#: The fewest ``.py`` files the walk must find under ``src/`` and ``scripts/`` (there are about 750): a glob or a path that
#: finds almost nothing would pass for the wrong reason.
_LEAST_FILES = 300


def check_tree(hits: dict[str, list[Hit]], unreadable: dict[str, str], *, least_files: int = _LEAST_FILES) -> list[str]:
    """What is wrong with a walk of the tree, one line each: it saw too few files to be looking at the tree, a file does
    not parse, or a fast hash reaches the passphrase."""
    problems: list[str] = []
    seen = len(hits) + len(unreadable)
    if seen <= least_files:
        problems.append(f"the walk found {seen} files; a restructure must not leave it looking at nothing")
    problems += [f"{rel}: does not parse ({why})" for rel, why in unreadable.items()]
    problems += [
        f"{rel}:{h.line}: {h.label} reads {h.mention}"
        for rel, found in hits.items()
        for h in found
        if h.mention is not None and not h.stretching
    ]
    return problems


def test_no_fast_hash_under_src_or_scripts_is_fed_the_passphrase():
    """Every ``.py`` file under ``src/`` and ``scripts/``: not one fast hash reaches a name the code uses for the passphrase.
    A file that does not parse counts against the walk (a file it cannot read is a file it does not guard)."""
    problems = check_tree(*_tree())
    assert not problems, (
        "a fast hash of the passphrase (or of something made from it), or a walk that cannot be trusted. The passphrase "
        "goes through a stretching function (the cache's key: columnar._derive_key, PBKDF2-HMAC-SHA512 at SQLCipher's own "
        "round count; the wrapped keys: scrypt) or nowhere; the list of allowed calls is empty on purpose, see this "
        "module's docstring: " + "; ".join(problems)
    )


def test_the_check_of_the_tree_reports_a_walk_that_saw_nothing_a_file_it_could_not_read_and_each_flagged_call():
    enough = {f"m{i}.py": [] for i in range(_LEAST_FILES + 1)}
    assert check_tree(enough, {}) == []
    assert any("looking at nothing" in line for line in check_tree({}, {}))
    assert any("looking at nothing" in line for line in check_tree({f"m{i}.py": [] for i in range(_LEAST_FILES)}, {}))
    assert check_tree(enough, {"bad.py": "invalid syntax"}) == ["bad.py: does not parse (invalid syntax)"]
    flagged = {**enough, "a.py": [Hit("hashlib.sha256", 3, "passphrase", False)]}
    assert check_tree(flagged, {}) == ["a.py:3: hashlib.sha256 reads passphrase"]
    harmless = {**enough, "b.py": [Hit("hashlib.pbkdf2_hmac", 4, "passphrase", True), Hit("hashlib.sha256", 5, None, False)]}
    assert check_tree(harmless, {}) == []


def test_the_walk_reads_the_real_key_derivation_and_the_real_modules_that_hash_files():
    """A walk that finds nothing passes for the wrong reason, so it must SEE what is there: the cache's PBKDF2 call, which
    takes the passphrase, as a stretching call that reaches a secret name -- and the many fast hashes of files and of
    other values the tree holds, none of which does."""
    derive = hash_calls((ROOT / "src/analytics/columnar.py").read_text(encoding="utf-8"))
    stretching = [h for h in derive if h.stretching and h.mention is not None]
    assert [h.label for h in stretching] == ["hashlib.pbkdf2_hmac"], derive
    assert stretching[0].mention == "passphrase"
    fast = [h for found in _tree()[0].values() for h in found if not h.stretching]
    assert len(fast) > 40, f"the walk saw {len(fast)} fast hashes in the tree; there are dozens"
    assert not [h for h in fast if h.mention is not None]


def test_the_walk_flags_the_shape_the_finding_named_in_the_real_module():
    """The cache's own key as it was, written back into the real source of the module: the walk must flag it. (If
    ``_derive_key`` is restructured so that the text below is not found, this fails loudly and is rewritten with it.)"""
    path = ROOT / "src/analytics/columnar.py"
    source = path.read_text(encoding="utf-8")
    stretched = 'hashlib.pbkdf2_hmac(\n        "sha512", passphrase.encode("utf-8"), salt, _KDF_ITERATIONS, dklen=_KDF_KEY_BYTES\n    ).hex()'
    assert stretched in source, "_derive_key moved: update the replacement below to its new text"
    assert fast_hashes_of_the_passphrase(source) == []
    before = source.replace(stretched, 'hashlib.sha256(("oo-columnar-v1:" + passphrase).encode("utf-8")).hexdigest()')
    assert [(h.label, h.mention) for h in fast_hashes_of_the_passphrase(before)] == [("hashlib.sha256", "passphrase")]


# --------------------------------------------------------------------------------------------------------------------
# What the walk sees (each case is a small module)
# --------------------------------------------------------------------------------------------------------------------
_HEAD = "import hashlib\nimport hmac\nimport os\n"

#: Each way a fast hash can reach the passphrase that the walk follows, as the module the guard must flag.
_FLAGGED = {
    "the pre-fix key: sha256 of a prefixed passphrase": (
        _HEAD + 'def key(passphrase):\n    return hashlib.sha256(("oo-columnar-v1:" + passphrase).encode("utf-8")).hexdigest()\n'
    ),
    "md5 of a password": _HEAD + "def f(password):\n    return hashlib.md5(password.encode()).hexdigest()\n",
    "sha1 of pw": _HEAD + "def f(pw):\n    return hashlib.sha1(pw).digest()\n",
    "an f-string": _HEAD + 'def f(passphrase):\n    return hashlib.sha256(f"v1:{passphrase}".encode()).hexdigest()\n',
    "hashlib.new": _HEAD + 'def f(passphrase):\n    return hashlib.new("sha256", passphrase.encode()).hexdigest()\n',
    "blake2b with a keyword": _HEAD + "def f(secret):\n    return hashlib.blake2b(secret, digest_size=32).hexdigest()\n",
    "an attribute that holds it": _HEAD + "class Q:\n    def f(self):\n        return hashlib.sha256(self._passphrase.encode()).digest()\n",
    "a function that returns it": _HEAD + "def f():\n    return hashlib.sha256(get_passphrase().encode()).digest()\n",
    "a module under another name": "import hashlib as hl\ndef f(passphrase):\n    return hl.sha3_256(passphrase.encode()).digest()\n",
    "a name imported from hashlib": "from hashlib import sha1 as s\ndef f(pw):\n    return s(pw).hexdigest()\n",
    "update of a hash object": _HEAD + "def f(secret):\n    h = hashlib.sha256()\n    h.update(secret.encode())\n    return h.digest()\n",
    "update of a call's result": _HEAD + "def f(passphrase):\n    hashlib.sha256().update(passphrase.encode())\n",
    "update of an attribute made in another method": (
        _HEAD + "class H:\n    def __init__(self):\n        self._h = hashlib.sha256()\n"
        "    def add(self, pw):\n        self._h.update(pw)\n"
    ),
    "a local made from it": _HEAD + 'def f(passphrase):\n    raw = ("x:" + passphrase).encode()\n    return hashlib.sha256(raw).digest()\n',
    "a copy of a copy": _HEAD + "def f(passphrase):\n    a = passphrase\n    b = a\n    return hashlib.sha256(b.encode()).digest()\n",
    "a tuple unpack": _HEAD + "def f(passphrase, salt):\n    a, b = passphrase, salt\n    return hashlib.sha256(a.encode()).digest()\n",
    "a walrus": _HEAD + "def f(passphrase):\n    return hashlib.sha256((x := passphrase).encode()).digest()\n",
    "a comprehension": _HEAD + 'def f(passphrase):\n    data = b"".join(p.encode() for p in (passphrase, "x"))\n    return hashlib.sha256(data).digest()\n',
    "a file it was read from": _HEAD + "def f(passphrase_file):\n    with open(passphrase_file, 'rb') as fh:\n        data = fh.read()\n    return hashlib.sha256(data).digest()\n",
    "a list that is spread": _HEAD + "def f(passphrase):\n    args = [passphrase.encode()]\n    return hashlib.sha256(*args).digest()\n",
    "hmac with it as the key": _HEAD + 'def f(passphrase):\n    return hmac.new(passphrase.encode(), b"m", "sha256").digest()\n',
    "hmac with keyword arguments": _HEAD + 'def f(passphrase):\n    return hmac.new(key=passphrase.encode(), msg=b"m", digestmod="sha256").digest()\n',
    "hashlib.new with a keyword": _HEAD + 'def f(pw):\n    return hashlib.new("sha256", data=pw).hexdigest()\n',
    "a comprehension variable": _HEAD + "def f(passphrase):\n    return [hashlib.sha256(c.encode()).digest() for c in passphrase]\n",
    "a walrus bound earlier": _HEAD + "def f(passphrase):\n    if (data := passphrase.encode()):\n        return hashlib.sha256(data).digest()\n",
    "hmac with it as the message": _HEAD + "def f(passphrase):\n    return hmac.digest(b'k', passphrase.encode(), 'sha256')\n",
    "the environment, by item": _HEAD + 'def f():\n    return hashlib.sha256(os.environ["OO_DB_PASSPHRASE"].encode()).digest()\n',
    "the environment, by get": _HEAD + 'def f():\n    return hashlib.sha256(os.environ.get("OO_DB_PASSPHRASE", "").encode()).digest()\n',
    "the environment, by getenv": _HEAD + 'def f():\n    return hashlib.sha256(os.getenv("OO_DB_PASSPHRASE").encode()).digest()\n',
    "the module's own statements": _HEAD + "passphrase = 'x'\nDIGEST = hashlib.sha256(passphrase.encode()).hexdigest()\n",
    "an async function": _HEAD + "async def f(password):\n    return hashlib.sha256(password.encode()).digest()\n",
    "a lambda": _HEAD + "KEY = lambda passphrase: hashlib.sha256(passphrase.encode()).digest()\n",
}


@pytest.mark.parametrize("way", sorted(_FLAGGED))
def test_the_walk_flags_each_way_a_fast_hash_can_reach_the_passphrase(way):
    assert fast_hashes_of_the_passphrase(_FLAGGED[way]), f"not flagged: {way}"


#: Code that sits beside the passphrase without hashing it, or hashes it the way the rule asks, as the module the guard
#: must leave alone.
_LEFT_ALONE = {
    "pbkdf2_hmac, the stretching function the cache uses": (
        _HEAD + 'def f(passphrase, salt):\n    return hashlib.pbkdf2_hmac("sha512", passphrase.encode(), salt, 256_000, dklen=32)\n'
    ),
    "scrypt": _HEAD + "def f(passphrase, salt):\n    return hashlib.scrypt(passphrase.encode(), salt=salt, n=2**14, r=8, p=1)\n",
    "pbkdf2_hmac under another name": "from hashlib import pbkdf2_hmac as kdf\ndef f(pw, salt):\n    return kdf('sha512', pw, salt, 256000)\n",
    "a hash of a file": _HEAD + "def f(path):\n    return hashlib.sha256(path.read_bytes()).hexdigest()\n",
    "a hash of a host": _HEAD + "def f(host):\n    return hashlib.sha256(host.encode()).digest()\n",
    "a hash of a token": _HEAD + "def f(token):\n    return hashlib.sha256(token.encode()).hexdigest()\n",
    "the standard module named secrets": _HEAD + "import secrets\ndef f():\n    return hashlib.sha256(secrets.token_bytes(16)).hexdigest()\n",
    "phrases of text": _HEAD + 'def f(phrases):\n    return hashlib.sha256(" ".join(phrases).encode()).hexdigest()\n',
    "a dict update that carries the passphrase": _HEAD + 'def f(env, passphrase):\n    env.update({"OO_DB_PASSPHRASE": passphrase})\n',
    "a hash and a passphrase in one function that never meet": (
        _HEAD + "def f(passphrase, data):\n    use(passphrase)\n    return hashlib.sha256(data).hexdigest()\n"
    ),
    "a hash object updated with a chunk": _HEAD + "def f(fh, passphrase):\n    h = hashlib.sha256()\n    h.update(fh.read())\n    return h.digest()\n",
    "a taint that stays in its own function": (
        _HEAD + "def a(passphrase):\n    raw = passphrase\n    return use(raw)\n"
        "def b(path):\n    raw = path.read_bytes()\n    return hashlib.sha256(raw).digest()\n"
    ),
    "a comparison, which hashes nothing": _HEAD + "def f(passphrase, other):\n    return hmac.compare_digest(passphrase.encode(), other)\n",
    "a dict that is keyed by the word, not read by it": _HEAD + 'def f(path):\n    return hashlib.sha256(str({"passphrase": 1}).encode() + path.read_bytes()).digest()\n',
}


@pytest.mark.parametrize("way", sorted(_LEFT_ALONE))
def test_the_walk_leaves_alone_what_does_not_hash_the_passphrase(way):
    assert fast_hashes_of_the_passphrase(_LEFT_ALONE[way]) == [], f"flagged: {way}"


def test_the_walk_counts_a_stretching_call_that_takes_the_passphrase_without_flagging_it():
    hits = hash_calls(_LEFT_ALONE["pbkdf2_hmac, the stretching function the cache uses"])
    assert [(h.label, h.mention, h.stretching) for h in hits] == [("hashlib.pbkdf2_hmac", "passphrase", True)]


def test_a_file_that_does_not_parse_is_reported_not_skipped(tmp_path):
    (tmp_path / "good.py").write_text("import hashlib\nDIGEST = hashlib.sha256(b'x').hexdigest()\n", encoding="utf-8")
    (tmp_path / "bad.py").write_text("def f(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        fast_hashes_of_the_passphrase("def f(:\n")
    hits, unreadable = walk_files(sorted(tmp_path.rglob("*.py")), tmp_path)
    assert list(unreadable) == ["bad.py"] and list(hits) == ["good.py"]


@pytest.mark.parametrize(
    ("name", "is_it"),
    [
        ("passphrase", True), ("_passphrase", True), ("corpus_passphrase", True), ("get_passphrase", True),
        ("OO_DB_PASSPHRASE", True), ("PassphraseBody", True), ("passphraseFile", True), ("password", True),
        ("pw", True), ("secret", True), ("secret_scrub", True), ("PASSWD", True),
        ("phrase", False), ("phrases", False), ("secrets", False), ("token", False), ("key", False), ("pwned", False),
        ("passenger", False), ("passed", False), ("bypass", False), ("keypass", False),
    ],
)
def test_which_names_say_that_a_value_is_the_passphrase(name, is_it):
    assert _is_secret_name(name) is is_it
