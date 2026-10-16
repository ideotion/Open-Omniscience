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
    ``Declined``, ``SalvageRefused``: fixed sentences), as ``str(x)`` / ``exception_text(x)`` / ``x.detail`` / ``x.code``;
  * anything else (an f-string, ``str``, ``repr``, ``.args``, ``%``, ``.format``, a field of the exception) is a violation, scrubbed
    or not: engine text into a record is class-only.

What this adds to ``tests/test_sink_sweep_records.py`` (which reads repair.py line by line and counts each use of a caught exception):
that table is keyed by the text of a line, so widening ``except LibraryBusy as busy`` to ``except (LibraryBusy, OSError) as busy`` leaves
``str(busy)`` an allowed line. Here the same line is read against the clause above it.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("src/database/repair.py", "src/database/salvage.py")
RAISED = frozenset({"Declined", "SalvageRefused"})
#: The classes whose text is a sentence the code wrote (nothing a driver said): an ``except`` naming only these may read the words.
OWN = frozenset({"LibraryBusy", "Declined", "SalvageRefused"})
CLASS_ONLY = frozenset({"failure_text", "failure_label"})
OWN_FIELDS = frozenset({"detail", "code"})


def _name_of(func: ast.expr) -> str | None:
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None


def _types_of(node: ast.expr | None) -> list[str] | None:
    """The class names an ``except`` clause lists (``None`` for a bare ``except``)."""
    if node is None:
        return None
    members = node.elts if isinstance(node, ast.Tuple) else [node]
    return [name for name in (_name_of(m) for m in members) if name]


class Reading:
    """One module read: the producer calls it found, what was wrong with their words, and which allowed forms were met."""

    def __init__(self, source: str) -> None:
        self.tree = ast.parse(source)
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
        while node in self.parent:
            node = self.parent[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return self.tree

    def _assigned(self, name: str, scope: ast.AST) -> list[ast.expr]:
        """Every expression the function assigns to ``name``: ``=``, ``+=``, a tuple unpacking (position by position when it can be
        told, the whole right-hand side when it cannot), an annotated assignment and a walrus."""
        found: list[ast.expr] = []
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    found += self._from_target(name, target, node.value)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                found += self._from_target(name, node.target, node.value)
        return found

    def _from_target(self, name: str, target: ast.expr, value: ast.expr) -> list[ast.expr]:
        if isinstance(target, ast.Name):
            return [value] if target.id == name else []
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
            for value in self._assigned(use.id, self._function_of(at)):
                if id(value) not in seen:
                    seen.add(id(value))
                    self.forms["assigned-name"] += 1
                    self._read(value, value, seen)

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
            if own and name == "exception_text" and up.args[0] is use:
                return "own-text"
        if own and isinstance(up, ast.Attribute) and up.value is use and up.attr in OWN_FIELDS:
            return "own-field"
        return None


def read(source: str) -> Reading:
    return Reading(source)


# --------------------------------------------------------------------------- #
#  the real modules
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("rel", SOURCES)
def test_no_refusal_is_made_of_a_caught_exceptions_words(rel):
    reading = read((ROOT / rel).read_text(encoding="utf-8"))
    assert reading.violations == [], f"{rel}: {reading.violations}"
    assert reading.sites >= {"src/database/repair.py": 14, "src/database/salvage.py": 4}[rel], "the reading found no producer: it would pass over nothing"


def test_the_reading_met_every_form_it_allows_in_the_real_code():
    """A form that no producer uses is a branch of the reading nothing exercises: the controls below prove each one, and this proves
    the real modules reach them, so a reading that stopped walking assignments or attributes would show here as well."""
    forms: Counter[str] = Counter()
    for rel in SOURCES:
        forms += read((ROOT / rel).read_text(encoding="utf-8")).forms
    for form in ("type-name", "class-only-call", "own-str", "assigned-name"):
        assert forms[form] >= 1, (form, dict(forms))


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
        ('raise Declined("c", f"{type(exc).__name__}")', "type-name"),
        ('raise Declined("c", damage.failure_text(exc))', "class-only-call"),
        ('text = "fixed"\nraise Declined("c", text)', "assigned-name"),
    ],
)
def test_control_each_allowed_form_is_counted_so_the_real_run_can_be_checked_for_it(body, form):
    clause = "(LibraryBusy, Declined)" if form.startswith("own") else "OSError"
    reading = read(_snippet(body, clause))
    assert reading.violations == [] and reading.forms[form] >= 1, (form, dict(reading.forms))


def test_control_a_producer_called_through_a_module_is_found_and_a_class_definition_is_not_one():
    source = 'class Declined(RuntimeError):\n    def __init__(self, code, detail):\n        super().__init__(detail)\n'
    assert read(source).sites == 0
    assert read(_snippet('raise repair.Declined("c", f"{exc}")')).violations
    assert read(_snippet('raise salvage.SalvageRefused("c", f"{exc}")')).violations
