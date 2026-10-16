"""What a repair refusal's words may be made of (R138): read from the source, with a negative control for every form.

``Declined`` (repair) and ``SalvageRefused`` (salvage) carry a sentence the code wrote, and that sentence reaches a log line, the
repair's ``reason_text`` (the boot-sequence status and the diagnostics bundle) and a job row. Every producer says a fixed sentence
today; nothing but this reading keeps the next one from quoting what a driver said, and a driver's words can hold the statement that
carried the passphrase. ``run()`` scrubs the words where they enter a record or a log (tests/test_repair.py drives that with a
planted passphrase); this is the other half, the words at the place they are made.

The rule, for every argument of a ``Declined(...)`` or ``SalvageRefused(...)`` (the code, the words, ``detail=`` or a fact), read through
the names assigned in the same function:

  * a caught exception may appear only as ``type(x).__name__``, as the argument of ``failure_text`` / ``failure_label`` (the class and
    a fixed label of a driver's error), or, when the ``except`` clause names ONLY the code's own refusals (``LibraryBusy``,
    ``Declined``, ``SalvageRefused``: fixed sentences), as ``str(x)`` / ``exception_text(x)`` / ``_words_of(x)`` / ``x.detail`` / ``x.code``
    (the two calls only as plain names, ``exception_text`` only in a module that binds it once, from ``src.monitoring.secret_scrub``, and
    ``_words_of`` only in ``repair.py``, where it is bound once and its whole definition is pinned);
  * anything else (an f-string, ``str``, ``repr``, ``.args``, ``%``, ``.format``, a field of the exception) is a violation, scrubbed
    or not: engine text into a record is class-only.

What this adds to ``tests/test_sink_sweep_records.py`` (which reads repair.py line by line and counts each use of a caught exception):
that table is keyed by the text of a line, so widening ``except LibraryBusy as busy`` to ``except (LibraryBusy, OSError) as busy`` leaves
``str(busy)`` an allowed line. Here the same line is read against the clause above it.

The names are followed through the OUTERMOST enclosing function (so a nested function sees what the one around it assigned) by ``=``,
``+=``, an annotated assignment, a walrus, a tuple unpacking (position by position when it can be told, the whole right-hand side when it
cannot), a store into an item or an attribute of the name (``d["n"] = x``, ``self.t = x``), a mutating call on it (``parts.append(x)``),
and a ``for`` / ``with`` / comprehension target. A function or method defined in the module and called in the words (``g()`` or
``self.g()``, by name) is followed to what it returns, and text carried from another function is followed: an attribute read is followed
to every store to an attribute of that name in the module (``self.t = x``, ``setattr(o, "t", x)``, ``self.parts.append(x)``), and a name
declared ``global`` / ``nonlocal`` to every assignment to it. The readers that reach the exception being handled without naming it (``format_exc``, ``sys.exc_info``, ``sys.exception``,
``locals()`` ...) are a violation wherever they appear in a refusal's words.

STATED LIMITS (each has a control in :data:`LIMITS` that passes today; extending the reading means moving the entry to
:data:`VIOLATIONS`): a parameter is not followed to the callers that pass it, a call into another module is not read (only
``failure_text`` / ``failure_label``, by name, are allowed to take the exception), and an attribute read through ``getattr`` is not
followed. None occurs in ``repair.py`` or ``salvage.py`` today.
"""

from __future__ import annotations

import ast
import copy
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("src/database/repair.py", "src/database/salvage.py")
RAISED = frozenset({"Declined", "SalvageRefused"})
#: The classes whose text is a sentence the code wrote (nothing a driver said): an ``except`` naming only these may read the words.
OWN = frozenset({"LibraryBusy", "Declined", "SalvageRefused"})
CLASS_ONLY = frozenset({"failure_text", "failure_label"})
#: The calls that hand over an own refusal's words scrubbed, allowed as PLAIN NAMES only and where the module binds them as pinned below:
#: ``exception_text`` (imported once from ``SCRUB_MODULE``) and ``_words_of`` (defined once, in ``HELPER_MODULE``, whole definition pinned).
OWN_TEXT_CALLS = frozenset({"exception_text", "_words_of"})
SCRUB_MODULE = "src.monitoring.secret_scrub"
HELPER_MODULE = "src/database/repair.py"
HELPER_SOURCE = (
    "def _words_of(refusal: Declined | salvage.SalvageRefused) -> str:\n"
    "    text = exception_text(refusal, typed=False)\n"
    "    refusal.detail = text\n"
    "    refusal.args = (text,)\n"
    "    refusal.__context__ = None\n"
    "    refusal.__cause__ = None\n"
    "    return text\n"
)
OWN_FIELDS = frozenset({"detail", "code"})
#: Readers of the exception being handled (or of every name) that need no name to reach it; none may appear in a refusal's words.
UNNAMED_READERS = frozenset(
    {"format_exc", "format_exception", "format_exception_only", "print_exc", "print_exception", "exc_info", "exception", "extract_tb",
     "format_tb", "format_stack", "format_list", "locals", "globals", "vars"}
)
#: Calls that put their arguments INTO the object they are called on.
MUTATORS = frozenset({"append", "extend", "add", "update", "insert", "setdefault", "appendleft", "extendleft", "write"})


def _name_of(func: ast.expr) -> str | None:
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None


def _types_of(node: ast.expr | None) -> list[str] | None:
    """The class names an ``except`` clause lists (``None`` for a bare ``except``)."""
    if node is None:
        return None
    members = node.elts if isinstance(node, ast.Tuple) else [node]
    return [name for name in (_name_of(m) for m in members) if name]


def _bindings(tree: ast.AST, name: str) -> list[ast.AST]:
    """Every place that binds ``name``: an import (a star import binds every name), a definition, a store, a parameter, an ``except``
    target, a ``global`` / ``nonlocal`` declaration. A module whose only binding of a name is the one expected cannot have it rebound."""
    found: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            found += [node for a in node.names if a.name == "*" or (a.asname or a.name.split(".")[0]) == name]
        elif (
            (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name)
            or (isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del)))
            or (isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names)
            or (isinstance(node, ast.ExceptHandler) and node.name == name)
            or (isinstance(node, ast.arg) and node.arg == name)
        ):
            found.append(node)
    return found


def _trusted_calls(tree: ast.Module, module: str | None) -> frozenset[str]:
    """Which of :data:`OWN_TEXT_CALLS` this module may use by name, because of what binds the name in it."""
    trusted: set[str] = set()
    scrub = _bindings(tree, "exception_text")
    if (
        len(scrub) == 1
        and isinstance(scrub[0], ast.ImportFrom)
        and scrub[0].module == SCRUB_MODULE
        and scrub[0].level == 0
        and [(a.name, a.asname) for a in scrub[0].names] == [("exception_text", None)]
    ):
        trusted.add("exception_text")
    helper = _bindings(tree, "_words_of")
    if module == HELPER_MODULE and len(helper) == 1 and isinstance(helper[0], ast.FunctionDef) and helper[0] in tree.body:
        trusted.add("_words_of")
    return frozenset(trusted)


def helper_problems(source: str) -> list[str]:
    """What is wrong with ``_words_of`` and the name it scrubs with in ``source`` (empty when nothing is): the allowance is by name, so
    the definition is compared WHOLE (the signature with its defaults, keyword-only parameters and annotations, the decorators, the
    return annotation and the body, with only a first-statement docstring set aside) and both names must be bound exactly once."""
    tree = ast.parse(source)
    problems: list[str] = []
    trusted = _trusted_calls(tree, HELPER_MODULE)
    if "exception_text" not in trusted:
        problems.append("exception_text is not bound exactly once, by `from src.monitoring.secret_scrub import exception_text`")
    if "_words_of" not in trusted:
        problems.append("_words_of is not bound exactly once, by a module-level def")
    helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_words_of"]
    if len(helpers) == 1:
        helper = copy.deepcopy(helpers[0])
        if helper.body and isinstance(helper.body[0], ast.Expr) and isinstance(helper.body[0].value, ast.Constant):
            helper.body = helper.body[1:]
        if ast.dump(helper) != ast.dump(ast.parse(HELPER_SOURCE).body[0]):
            problems.append(f"the definition is not the pinned one:\n{ast.unparse(helper)}")
    return problems


class Reading:
    """One module read: the producer calls it found, what was wrong with their words, and which allowed forms were met."""

    def __init__(self, source: str, *, module: str | None = None, trusted: frozenset[str] | None = None) -> None:
        self.tree = ast.parse(source)
        self.trusted = _trusted_calls(self.tree, module) if trusted is None else trusted
        self.parent = {child: node for node in ast.walk(self.tree) for child in ast.iter_child_nodes(node)}
        self.sites = 0
        self.forms: Counter[str] = Counter()
        self.violations: list[str] = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and _name_of(node.func) in RAISED:
                self.sites += 1
                for argument in [*node.args, *(k.value for k in node.keywords)]:
                    self._read(argument, argument, set())

    def _bound(self, node: ast.AST) -> dict[str, bool]:
        """The exceptions the ``except`` clauses around ``node`` have bound, each with whether its clause names only our own refusals."""
        bound: dict[str, bool] = {}
        child = node
        while child in self.parent:
            up = self.parent[child]
            if isinstance(up, ast.ExceptHandler) and up.name and child is not up.type:
                types = _types_of(up.type)
                bound.setdefault(up.name, types is not None and bool(types) and all(t in OWN for t in types))
            child = up
        return bound

    def _function_of(self, node: ast.AST) -> ast.AST:
        """The OUTERMOST function around ``node``: a nested function reads the names the one around it assigned."""
        outer: ast.AST = self.tree
        while node in self.parent:
            node = self.parent[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                outer = node
        return outer

    def _assigned(self, name: str, scope: ast.AST) -> list[ast.expr]:
        """Every expression the function puts into ``name`` (see the module docstring for the ways)."""
        found: list[ast.expr] = []
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    found += self._from_target(name, target, node.value)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                found += self._from_target(name, node.target, node.value)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                found += self._from_target(name, node.target, node.iter)
            elif isinstance(node, ast.withitem) and node.optional_vars is not None:
                found += self._from_target(name, node.optional_vars, node.context_expr)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in MUTATORS
                and self._base_name(node.func.value) == name
            ):
                found += [*node.args, *(k.value for k in node.keywords)]
        return found

    def _returned(self, name: str) -> list[ast.expr]:
        """What every function called ``name`` in the module returns (a helper or a closure called in a refusal's words)."""
        return [
            r.value
            for fn in ast.walk(self.tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == name
            for r in ast.walk(fn)
            if isinstance(r, ast.Return) and r.value is not None
        ]

    def _stored(self, attr: str) -> list[ast.expr]:
        """Every expression stored into an attribute called ``attr`` anywhere in the module (``self.t = x``, ``self.d[k] = x``,
        ``setattr(o, "t", x)``, ``self.parts.append(x)``): text carried from one function to another."""
        found: list[ast.expr] = []
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and node.value is not None:
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(self._hits_attribute(t, attr) for t in targets):
                    found.append(node.value)
            elif isinstance(node, ast.Call) and _name_of(node.func) == "setattr" and len(node.args) == 3:
                named = node.args[1]
                if not (isinstance(named, ast.Constant) and isinstance(named.value, str)) or named.value == attr:
                    found.append(node.args[2])
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in MUTATORS
                and self._hits_attribute(node.func.value, attr)
            ):
                found += [*node.args, *(k.value for k in node.keywords)]
        return found

    def _hits_attribute(self, target: ast.expr, attr: str) -> bool:
        if isinstance(target, (ast.Tuple, ast.List)):
            return any(self._hits_attribute(t, attr) for t in target.elts)
        node = target.value if isinstance(target, ast.Starred) else target
        while isinstance(node, (ast.Subscript, ast.Attribute)):
            if isinstance(node, ast.Attribute) and node.attr == attr:
                return True
            node = node.value
        return False

    def _declared_outside(self, name: str) -> bool:
        """Whether some function declares ``name`` ``global`` / ``nonlocal``: then an assignment anywhere in the module may be the one read."""
        return any(isinstance(n, (ast.Global, ast.Nonlocal)) and name in n.names for n in ast.walk(self.tree))

    def _follow(self, value: ast.expr, seen: set[int], form: str) -> None:
        if id(value) not in seen:
            seen.add(id(value))
            self.forms[form] += 1
            self._read(value, value, seen)

    @staticmethod
    def _base_name(node: ast.expr) -> str | None:
        while isinstance(node, (ast.Subscript, ast.Attribute)):
            node = node.value
        return node.id if isinstance(node, ast.Name) else None

    def _from_target(self, name: str, target: ast.expr, value: ast.expr) -> list[ast.expr]:
        if isinstance(target, ast.Name):
            return [value] if target.id == name else []
        if isinstance(target, (ast.Subscript, ast.Attribute)):
            return [value] if self._base_name(target) == name else []
        if isinstance(target, (ast.Tuple, ast.List)):
            if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts) and not any(
                isinstance(e, ast.Starred) for e in [*target.elts, *value.elts]
            ):
                return [v for t, v in zip(target.elts, value.elts, strict=True) for v in self._from_target(name, t, v)]
            return [value] if any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(target)) else []
        return []

    def _read(self, expression: ast.expr, at: ast.AST, seen: set[int]) -> None:
        bound = self._bound(at)
        for use in ast.walk(expression):
            if isinstance(use, ast.Call) and _name_of(use.func) in UNNAMED_READERS:
                self.violations.append(f"{use.lineno}: {ast.unparse(use)} reads the exception being handled and is part of a refusal's words")
            if isinstance(use, ast.Attribute) and isinstance(use.ctx, ast.Load):
                for value in self._stored(use.attr):
                    self._follow(value, seen, "carried-attribute")
                for value in self._returned(use.attr):
                    self._follow(value, seen, "assigned-name")
                continue
            if not (isinstance(use, ast.Name) and isinstance(use.ctx, ast.Load)):
                continue
            if use.id in bound:
                form = self._form(use, own=bound[use.id])
                if form is None:
                    shown = ast.unparse(self.parent.get(use, use))
                    self.violations.append(f"{use.lineno}: the caught exception {use.id!r} is part of a refusal's words ({shown})")
                else:
                    self.forms[form] += 1
                continue
            scope = self.tree if self._declared_outside(use.id) else self._function_of(at)
            for value in [*self._assigned(use.id, scope), *self._returned(use.id)]:
                self._follow(value, seen, "assigned-name")

    def _form(self, use: ast.Name, *, own: bool) -> str | None:
        up = self.parent.get(use)
        if isinstance(up, ast.Call) and use in up.args:
            name = _name_of(up.func)
            above = self.parent.get(up)
            if name == "type" and len(up.args) == 1 and isinstance(above, ast.Attribute) and above.attr == "__name__":
                return "type-name"
            if name in CLASS_ONLY:
                return "class-only-call"
            if own and name == "str" and len(up.args) == 1 and not up.keywords:
                return "own-str"
            if own and isinstance(up.func, ast.Name) and name in self.trusted and up.args[0] is use:
                return "own-text"
        if own and isinstance(up, ast.Attribute) and up.value is use and up.attr in OWN_FIELDS:
            return "own-field"
        return None


def read(source: str, *, module: str | None = None, trusted: frozenset[str] | None = OWN_TEXT_CALLS) -> Reading:
    """Read ``source``. The controls trust both text calls by default (they are snippets); ``trusted=None`` works it out from what the
    module binds, as the real modules are read."""
    return Reading(source, module=module, trusted=trusted)


# --------------------------------------------------------------------------- #
#  the real modules
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rel", SOURCES)
def test_no_refusal_is_made_of_a_caught_exceptions_words(rel):
    reading = read((ROOT / rel).read_text(encoding="utf-8"), module=rel, trusted=None)
    assert reading.violations == [], f"{rel}: {reading.violations}"
    assert reading.sites >= {"src/database/repair.py": 14, "src/database/salvage.py": 4}[rel], "the reading found no producer: it would pass over nothing"


def test_the_reading_met_every_form_it_allows_in_the_real_code():
    """A form that no producer uses is a branch of the reading nothing exercises: the controls below prove each one, and this proves
    the real modules reach them, so a reading that stopped walking assignments or attributes would show here as well."""
    forms: Counter[str] = Counter()
    for rel in SOURCES:
        forms += read((ROOT / rel).read_text(encoding="utf-8"), module=rel, trusted=None).forms
    for form in ("type-name", "class-only-call", "own-str", "assigned-name"):
        assert forms[form] >= 1, (form, dict(forms))


def test_the_helper_that_hands_over_a_refusals_words_is_pinned_to_its_one_shape():
    """``_words_of(x)`` and ``exception_text(x)`` are allowed by NAME, so a name is only as good as what is bound to it: this pins the
    whole definition of the helper (signature, defaults, decorators, annotations, body) and that both names are bound exactly once in
    repair.py, so the allowance cannot outlive either. The controls below mutate the real source one way at a time."""
    assert helper_problems((ROOT / HELPER_MODULE).read_text(encoding="utf-8")) == []


# --------------------------------------------------------------------------- #
#  controls: a violation per form, and the forms that stay allowed
# --------------------------------------------------------------------------- #
_HANDLER = "def f():\n    try:\n        pass\n    except {clause} as exc:\n{body}\n"


def _snippet(body: str, clause: str = "OSError") -> str:
    return _HANDLER.format(clause=clause, body="\n".join("        " + line for line in body.splitlines()))


VIOLATIONS = {
    "an f-string": 'raise Declined("c", f"could not open ({exc})")',
    "an f-string with !r": 'raise Declined("c", f"could not open ({exc!r})")',
    "str()": 'raise Declined("c", str(exc))',
    "repr()": 'raise Declined("c", repr(exc))',
    "a cut str()": 'raise Declined("c", str(exc)[:200])',
    "args": 'raise Declined("c", exc.args[0])',
    "a field of the exception": 'raise Declined("c", exc.strerror)',
    "percent": 'raise Declined("c", "could not open (%s)" % exc)',
    "format": 'raise Declined("c", "could not open ({})".format(exc))',
    "concatenation": 'raise Declined("c", "could not open (" + str(exc) + ")")',
    "the keyword detail": 'raise Declined("c", detail=f"{exc}")',
    "a fact": 'raise Declined("c", "fixed", note=str(exc))',
    "a fact in a mapping": 'raise Declined("c", "fixed", **{"note": str(exc)})',
    "the code": "raise Declined(str(exc), 'fixed')",
    "the salvage refusal": 'raise salvage.SalvageRefused("c", f"{exc}")',
    "a name assigned in the handler": 'text = f"could not open ({exc})"\nraise Declined("c", text)',
    "a name assigned in two steps": 'first = str(exc)\ntext = "a " + first\nraise Declined("c", text)',
    "a name appended to": 'text = "fixed"\ntext += str(exc)\nraise Declined("c", text)',
    "a name unpacked from a tuple": 'code, text = "c", str(exc)\nraise Declined(code, text)',
    "a name unpacked from one value": 'code, text = divmod(1, exc)\nraise Declined(code, text)',
    "a name from a walrus": 'if (text := str(exc)):\n    raise Declined("c", text)',
    "a scrubbed str() is not a class": 'raise Declined("c", scrubbed(str(exc)))',
    "exception_text": 'raise Declined("c", exception_text(exc))',
    "type() with more than the name": 'raise Declined("c", type(exc).__doc__)',
    "a bare str of a driver class": 'raise Declined("c", str(type(exc)))',
    "a name from an annotated assignment": 'text: str = str(exc)\nraise Declined("c", text)',
    "a name from a starred unpacking": 'code, *rest = "c", str(exc)\nraise Declined(code, *rest)',
    "a name from a store into an item": 'held = {}\nheld["note"] = str(exc)\nraise Declined("c", **held)',
    "an item read back": 'held = {}\nheld["note"] = str(exc)\nraise Declined("c", held["note"])',
    "a name from a store into an attribute": 'self.note = str(exc)\nraise Declined("c", self.note)',
    "a name filled by append and joined": 'parts = []\nparts.append(str(exc))\nraise Declined("c", ", ".join(parts))',
    "a name from a for target": 'for text in [str(exc)]:\n    raise Declined("c", text)',
    "a name from a with target": 'with opened(str(exc)) as text:\n    raise Declined("c", text)',
    "a name from a comprehension": 'raise Declined("c", ", ".join(text for text in [str(exc)]))',
    "a lambda that reads it": 'raise Declined("c", (lambda: str(exc))())',
    "a closure that reads it": 'def words():\n    return str(exc)\nraise Declined("c", words())',
    "a closure that reads it, through a name": 'def words():\n    text = str(exc)\n    return text\nraise Declined("c", words())',
    "a helper handed the exception": 'raise Declined("c", describe(exc))',
    "format_exc": 'raise Declined("c", traceback.format_exc())',
    "sys.exc_info": 'raise Declined("c", str(sys.exc_info()[1]))',
    "sys.exception": 'raise Declined("c", str(sys.exception()))',
    "locals": 'raise Declined("c", str(locals()))',
    "the exception as the second argument of exception_text": 'raise Declined("c", exception_text("fixed", exc))',
}


@pytest.mark.parametrize("form", sorted(VIOLATIONS))
def test_control_each_form_of_an_exceptions_words_in_a_refusal_is_a_violation(form):
    reading = read(_snippet(VIOLATIONS[form]))
    assert reading.sites == 1 and reading.violations, form


def test_control_a_violation_is_found_through_a_clause_that_names_other_classes():
    """``str(busy)`` is allowed for our own classes: a clause that adds one other class, or catches everything, loses that."""
    line = 'raise Declined("writer-busy", str(exc))'
    assert read(_snippet(line, "LibraryBusy")).violations == []
    for clause in ("(LibraryBusy, OSError)", "Exception", "(Declined, sqlite3.OperationalError)", "(library_generation.LibraryBusy, OSError)"):
        assert read(_snippet(line, clause)).violations, clause
    assert read(_snippet(line, "(LibraryBusy, Declined)")).violations == []
    assert read(_snippet(line, "library_generation.LibraryBusy")).violations == []
    for helper_line in ('raise Declined("c", exception_text(exc))', 'raise Declined("c", _words_of(exc))'):
        assert read(_snippet(helper_line, "LibraryBusy")).violations == [], helper_line
        for clause in ("OSError", "Exception", "(LibraryBusy, OSError)"):
            assert read(_snippet(helper_line, clause)).violations, (helper_line, clause)


_OWN_ONLY = {
    "str() with an encoding": 'raise Declined("c", str(exc, "utf-8"))',
    "str() of the keyword": 'raise Declined("c", str(object=exc))',
    "exception_text with the exception second": 'raise Declined("c", exception_text("fixed", exc))',
    "the words helper with the exception second": 'raise Declined("c", _words_of("fixed", exc))',
    "the words helper with the exception as a keyword": 'raise Declined("c", _words_of(refusal=exc))',
    "exception_text with the exception as a keyword": 'raise Declined("c", exception_text(exc=exc))',
    "args": 'raise Declined("c", exc.args[0])',
    "the cause": 'raise Declined("c", exc.__cause__)',
    "a fact of the refusal": 'raise Declined("c", exc.facts)',
    "the context": 'raise Declined("c", exc.__context__)',
    "an unknown field": 'raise Declined("c", exc.strerror)',
}


@pytest.mark.parametrize("form", sorted(_OWN_ONLY))
def test_control_an_own_refusal_is_read_only_in_the_exact_shapes_the_reading_allows(form):
    """A clause naming only our own refusals widens ``str(x)`` / ``exception_text(x)`` / ``x.detail`` / ``x.code``, nothing else."""
    assert read(_snippet(_OWN_ONLY[form], "(LibraryBusy, Declined)")).violations, form


@pytest.mark.parametrize("field", sorted(OWN_FIELDS))
def test_control_an_own_field_needs_a_clause_that_names_only_our_own_refusals(field):
    line = f'raise Declined("c", exc.{field})'
    for clause in ("OSError", "Exception", "(LibraryBusy, OSError)", "(Declined, sqlite3.OperationalError)", "(library_generation.LibraryBusy, OSError)"):
        assert read(_snippet(line, clause)).violations, (field, clause)
    for clause in ("LibraryBusy", "Declined", "salvage.SalvageRefused", "(LibraryBusy, Declined)", "library_generation.LibraryBusy"):
        assert read(_snippet(line, clause)).violations == [], (field, clause)


def test_control_a_bare_except_is_not_a_clause_that_names_our_own_refusals():
    source = "def f():\n    try:\n        pass\n    except:\n        raise Declined('c', 'fixed')\n"
    assert read(source).violations == []
    for line in ('str(exc)', 'exc.detail'):
        bare = f"def f():\n    try:\n        pass\n    except Exception as exc:\n        raise Declined('c', {line})\n"
        assert read(bare).violations, line


def test_control_the_innermost_clause_that_binds_a_name_decides_what_it_is():
    own_inside = (
        "def f():\n    try:\n        pass\n    except OSError as exc:\n"
        "        try:\n            pass\n        except LibraryBusy as exc:\n"
        "            raise Declined('c', str(exc))\n"
    )
    other_inside = (
        "def f():\n    try:\n        pass\n    except LibraryBusy as exc:\n"
        "        try:\n            pass\n        except OSError as exc:\n"
        "            raise Declined('c', str(exc))\n"
    )
    assert read(own_inside).violations == []
    assert read(other_inside).violations


def test_control_a_name_assigned_in_the_enclosing_function_is_read_in_the_nested_one():
    """``_swap`` raises ``Declined`` from a nested function; what the function around it assigned is part of the words."""
    source = (
        "def swap():\n    try:\n        pass\n    except OSError as exc:\n"
        "        text = str(exc)\n"
        "        def inner():\n            raise Declined('c', text)\n"
    )
    assert len(read(source).violations) == 1
    clean = (
        "def swap():\n    text = 'fixed'\n"
        "    def inner():\n        raise Declined('c', text)\n"
    )
    assert read(clean).violations == []


def test_control_an_outer_handlers_exception_is_not_made_clean_by_an_inner_own_clause():
    source = (
        "def f():\n"
        "    try:\n        pass\n"
        "    except OSError as outer:\n"
        "        try:\n            pass\n"
        "        except LibraryBusy as busy:\n"
        '            raise Declined("c", str(busy) + str(outer)) from busy\n'
    )
    assert len(read(source).violations) == 1


def test_control_an_exception_name_from_another_function_or_scope_is_not_confused():
    """A name that is not bound by an enclosing clause is no exception; a name assigned in ANOTHER function is not resolved here."""
    source = (
        "def other():\n    try:\n        pass\n    except OSError as text:\n        return str(text)\n"
        "def f(text):\n    raise Declined('c', text)\n"
    )
    assert read(source).violations == []
    after = "def f():\n    try:\n        pass\n    except OSError as exc:\n        pass\n    raise Declined('c', f'{exc}')\n"
    assert read(after).violations == [], "outside the clause the name is not bound by it (it would be a NameError, not a leak)"


ALLOWED = {
    "the class name": 'raise Declined("c", f"could not open ({type(exc).__name__})")',
    "the class name alone": 'raise Declined("c", type(exc).__name__)',
    "failure_text": 'raise Declined("c", f"could not open ({damage.failure_text(exc)})")',
    "failure_label": 'raise Declined("c", failure_label(exc))',
    "a fixed sentence": 'raise Declined("c", "the drive cannot give the damaged file a second name")',
    "a number": 'raise Declined("c", "the drive has too little room", free_mb=1, needed_mb=2)',
    "a name from a fixed assignment": 'held = ["a", "b"]\ntext = "waiting for " + ", ".join(held)\nraise Declined("c", text)',
    "a name from a class name": 'text = f"({type(exc).__name__})"\nraise Declined("c", text)',
    "nothing of the exception": 'raise Declined("c", "fixed") from None',
}


@pytest.mark.parametrize("form", sorted(ALLOWED))
def test_control_the_forms_that_say_nothing_an_engine_said_stay_allowed(form):
    reading = read(_snippet(ALLOWED[form]))
    assert reading.sites == 1 and reading.violations == [], (form, reading.violations)


@pytest.mark.parametrize(
    ("body", "form"),
    [
        ('raise Declined("c", str(exc))', "own-str"),
        ('raise Declined(exc.code, exc.detail)', "own-field"),
        ('raise Declined("c", exception_text(exc, typed=False))', "own-text"),
        ('text = _words_of(exc)\nraise Declined("c", text)', "own-text"),
        ('raise Declined("c", f"{type(exc).__name__}")', "type-name"),
        ('raise Declined("c", damage.failure_text(exc))', "class-only-call"),
        ('text = "fixed"\nraise Declined("c", text)', "assigned-name"),
    ],
)
def test_control_each_allowed_form_is_counted_so_the_real_run_can_be_checked_for_it(body, form):
    clause = "(LibraryBusy, Declined)" if form.startswith("own") else "OSError"
    reading = read(_snippet(body, clause))
    assert reading.violations == [] and reading.forms[form] >= 1, (form, dict(reading.forms))


#: What the reading does NOT see. Each passes today and says why; a reading that learns one moves the entry to VIOLATIONS.
LIMITS = {
    "a parameter is not followed to the callers that pass it": "def f(text):\n    raise Declined('c', text)\n",
    "a call into another module is not read, whatever it does with the exception on its own": _snippet('raise Declined("c", other.describe())'),
    "an attribute read through getattr is not followed": (
        "class S:\n"
        "    def a(self):\n        try:\n            pass\n        except OSError as e:\n            self.t = str(e)\n"
        "    def b(self):\n        raise Declined('c', getattr(self, 'text'))\n"
    ),
}


@pytest.mark.parametrize("limit", sorted(LIMITS))
def test_control_the_stated_limits_of_the_reading_are_the_limits(limit):
    reading = read(LIMITS[limit])
    assert reading.sites == 1 and reading.violations == [], (limit, reading.violations)


def test_the_module_docstring_states_every_limit_the_controls_pin():
    doc = __doc__ or ""
    assert "STATED LIMITS" in doc and "LIMITS" in doc
    assert len(LIMITS) == 3, "a new limit is stated in the docstring above (it names each) and given its entry in LIMITS"
    for words in ("parameter", "another module", "getattr"):
        assert words in doc, words


_CARRIED = {
    "a method that returns it": (
        "class S:\n"
        "    def d(self):\n        try:\n            pass\n        except OSError as e:\n            return str(e)\n"
        "    def f(self):\n        raise Declined('c', self.d())\n"
    ),
    "text kept in an attribute by another method": (
        "class S:\n"
        "    def a(self):\n        try:\n            pass\n        except OSError as e:\n            self.t = str(e)\n"
        "    def b(self):\n        raise Declined('c', self.t)\n"
    ),
    "the exception kept in an attribute by another method": (
        "class S:\n"
        "    def a(self):\n        try:\n            pass\n        except OSError as e:\n            self.err = e\n"
        "    def b(self):\n        raise Declined('c', str(self.err))\n"
    ),
    "text kept in an item of an attribute": (
        "class S:\n"
        "    def a(self):\n        try:\n            pass\n        except OSError as e:\n            self.held['n'] = str(e)\n"
        "    def b(self):\n        raise Declined('c', self.held['n'])\n"
    ),
    "text appended to an attribute by another method": (
        "class S:\n"
        "    def a(self):\n        try:\n            pass\n        except OSError as e:\n            self.parts.append(str(e))\n"
        "    def b(self):\n        raise Declined('c', ', '.join(self.parts))\n"
    ),
    "text unpacked into attributes": (
        "class S:\n"
        "    def a(self):\n        try:\n            pass\n        except OSError as e:\n            self.t, self.u = 'fixed', str(e)\n"
        "    def b(self):\n        raise Declined('c', self.u)\n"
    ),
    "text kept with setattr": (
        "class S:\n"
        "    def a(self):\n        try:\n            pass\n        except OSError as e:\n            setattr(self, 't', str(e))\n"
        "    def b(self):\n        raise Declined('c', self.t)\n"
    ),
    "text kept with setattr under a computed name": (
        "class S:\n"
        "    def a(self, key):\n        try:\n            pass\n        except OSError as e:\n            setattr(self, key, str(e))\n"
        "    def b(self):\n        raise Declined('c', self.t)\n"
    ),
    "text kept in a global by another function": (
        "def a():\n    global T\n    try:\n        pass\n    except OSError as e:\n        T = str(e)\n"
        "def b():\n    raise Declined('c', T)\n"
    ),
}


@pytest.mark.parametrize("form", sorted(_CARRIED))
def test_control_text_carried_from_one_function_to_another_is_followed_to_the_refusal(form):
    reading = read(_CARRIED[form])
    assert reading.sites == 1 and reading.violations, form


def test_control_text_carried_that_says_nothing_an_engine_said_stays_allowed():
    source = (
        "class S:\n"
        "    def a(self):\n        try:\n            pass\n        except OSError as e:\n"
        "            self.t = type(e).__name__\n            self.parts.append('fixed')\n"
        "    def b(self):\n        raise Declined('c', self.t, note=', '.join(self.parts))\n"
        "    def d(self):\n        return 'fixed'\n"
        "    def f(self):\n        raise Declined('c', self.d())\n"
    )
    reading = read(source)
    assert reading.sites == 2 and reading.violations == [] and reading.forms["carried-attribute"] >= 1


def test_control_the_text_calls_are_allowed_as_plain_names_only():
    for call in ("other._words_of(exc)", "other.exception_text(exc)", "self.exception_text(exc)"):
        assert read(_snippet(f'raise Declined("c", {call})', "LibraryBusy")).violations, call
    for call in ("_words_of(exc)", "exception_text(exc)"):
        assert read(_snippet(f'raise Declined("c", {call})', "LibraryBusy")).violations == [], call


_SCRUB = f"from {SCRUB_MODULE} import exception_text\n"
_USE = _snippet('raise Declined("c", _words_of(exc), note=exception_text(exc))', "LibraryBusy")
_WORDS_OF_MODULES = {
    "the module that defines both": (_SCRUB + HELPER_SOURCE + _USE, HELPER_MODULE, 0),
    "another module that defines _words_of": (_SCRUB + HELPER_SOURCE + _USE, "src/database/salvage.py", 1),
    "a second definition of _words_of": (_SCRUB + HELPER_SOURCE + "\ndef _words_of(refusal):\n    return str(refusal)\n" + _USE, HELPER_MODULE, 1),
    "_words_of defined in a class": (_SCRUB + "class C:\n" + "".join("    " + ln + "\n" for ln in HELPER_SOURCE.splitlines()) + _USE, HELPER_MODULE, 1),
    "_words_of assigned elsewhere": (_SCRUB + HELPER_SOURCE + "_words_of = str\n" + _USE, HELPER_MODULE, 1),
    "exception_text rebound": (_SCRUB + HELPER_SOURCE + "exception_text = str\n" + _USE, HELPER_MODULE, 1),
    "exception_text from another module": ("from src.monitoring.other import exception_text\n" + HELPER_SOURCE + _USE, HELPER_MODULE, 1),
    "exception_text under another name": (f"from {SCRUB_MODULE} import exception_text as scrub\n" + HELPER_SOURCE + _USE, HELPER_MODULE, 1),
    "exception_text imported by a star import": (_SCRUB + "from os import *\n" + HELPER_SOURCE + _USE, HELPER_MODULE, 2),
    "exception_text declared global": (_SCRUB + HELPER_SOURCE + "def g():\n    global exception_text\n" + _USE, HELPER_MODULE, 1),
    "exception_text as a parameter name": (_SCRUB + HELPER_SOURCE + "def g(exception_text):\n    pass\n" + _USE, HELPER_MODULE, 1),
}


@pytest.mark.parametrize("form", sorted(_WORDS_OF_MODULES))
def test_control_the_text_calls_are_trusted_only_where_the_module_binds_them_as_pinned(form):
    source, module, flagged = _WORDS_OF_MODULES[form]
    reading = read(source, module=module, trusted=None)
    assert reading.sites == 1 and len(reading.violations) >= flagged, (form, reading.violations)
    if flagged == 0:
        assert reading.violations == []


def _real_helper_source() -> str:
    return (ROOT / HELPER_MODULE).read_text(encoding="utf-8")


_SIGNATURE = "def _words_of(refusal: Declined | salvage.SalvageRefused) -> str:"
_IMPORT = f"from {SCRUB_MODULE} import exception_text\n"
_HELPER_MUTATIONS = {
    "a keyword-only parameter that shadows the scrub": (_SIGNATURE, "def _words_of(refusal: Declined | salvage.SalvageRefused, *, exception_text=lambda e, typed=False: str(e)) -> str:"),
    "a decorator": (_SIGNATURE, "@functools.cache\n" + _SIGNATURE),
    "another return annotation": (_SIGNATURE, _SIGNATURE.replace("-> str", "-> int")),
    "another parameter annotation": (_SIGNATURE, _SIGNATURE.replace("Declined | salvage.SalvageRefused", "Declined")),
    "a default for the parameter": (_SIGNATURE, _SIGNATURE.replace("SalvageRefused)", "SalvageRefused = None)")),
    "a variadic parameter": (_SIGNATURE, _SIGNATURE.replace("SalvageRefused)", "SalvageRefused, *rest)")),
    "a rebinding of the scrub at module level": (_IMPORT, _IMPORT + "exception_text = lambda e, typed=False: str(e)\n"),
    "the scrub imported from another module": (_IMPORT, "from src.monitoring.other import exception_text\n"),
    "the scrub imported under its own name again": (_IMPORT, f"from {SCRUB_MODULE} import exception_text as exception_text\n"),
    "a star import": (_IMPORT, _IMPORT + "from os import *\n"),
    "a second definition": (_SIGNATURE, "def _words_of(refusal):\n    return str(refusal)\n\n\n" + _SIGNATURE),
    "a global declaration of the scrub": ("def run(work", "def _rebind():\n    global exception_text\n\n\ndef run(work"),
    "no put-back into detail": ("    refusal.detail = text\n", ""),
    "no put-back into args": ("    refusal.args = (text,)\n", ""),
    "a cut after the scrub": ("    refusal.args = (text,)\n", "    refusal.args = (text,)\n    text = text[:300]\n"),
    "the context kept": ("    refusal.__context__ = None\n", ""),
    "the cause kept": ("    refusal.__cause__ = None\n", ""),
    "another call than the scrub": ("    text = exception_text(refusal, typed=False)\n", "    text = str(refusal)\n"),
    "the scrub without typed=False": ("    text = exception_text(refusal, typed=False)\n", "    text = exception_text(refusal)\n"),
    "a statement before the scrub": ("    text = exception_text(refusal, typed=False)\n", "    _LOG.info('%s', refusal.detail)\n    text = exception_text(refusal, typed=False)\n"),
}


@pytest.mark.parametrize("form", sorted(_HELPER_MUTATIONS))
def test_control_each_way_of_changing_the_helper_or_what_it_scrubs_with_is_found(form):
    old, new = _HELPER_MUTATIONS[form]
    source = _real_helper_source()
    assert source.count(old) == 1, f"{form}: the text this control changes is no longer in {HELPER_MODULE} exactly once"
    assert helper_problems(source.replace(old, new)), form


def test_control_a_docstring_is_the_one_thing_set_aside_from_the_pinned_definition():
    plain = HELPER_SOURCE
    documented = plain.replace("-> str:\n", '-> str:\n    """words."""\n', 1)
    assert helper_problems(_SCRUB + plain) == [] and helper_problems(_SCRUB + documented) == []
    assert helper_problems(_SCRUB + plain.replace("-> str:\n", '-> str:\n    "one"\n    "two"\n', 1))


def test_control_a_producer_called_through_a_module_is_found_and_a_class_definition_is_not_one():
    source = 'class Declined(RuntimeError):\n    def __init__(self, code, detail):\n        super().__init__(detail)\n'
    assert read(source).sites == 0
    assert read(_snippet('raise repair.Declined("c", f"{exc}")')).violations
    assert read(_snippet('raise salvage.SalvageRefused("c", f"{exc}")')).violations
