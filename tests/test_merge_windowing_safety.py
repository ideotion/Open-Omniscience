"""Windowing a merge step is only safe where it cannot change what lands.

WHY THIS FILE EXISTS, and why it is separate from ``test_merge_bounded.py``:
that file proves the windows are BOUNDED and that no article is lost. This one
proves something different and easier to get wrong -- that windowing a step does
not quietly change the CONTENTS of the user's corpus.

THE MEASUREMENT BEHIND IT (run before any of this was written): a ``NOT EXISTS``
against the target does NOT see rows the SAME statement is inserting. So given
two incoming rows sharing a step's dedup key:

    whole-corpus statement  -> inserts BOTH
    windowed statement      -> inserts ONE   (window 2 sees window 1's commit)

Both answers are defensible; they are not the same answer. Silently swapping one
for the other under a performance change is exactly the class of thing this
project's discipline forbids, and no test whose fixture happens to contain no
internal duplicates can see it.

So a step may be windowed only where a second candidate for one identity cannot
survive -- ``_WINDOWED_STEPS`` records which of the three justifications applies
to each, and the tests below check those claims against the SCHEMA and the SQL
rather than against the registry's own comments.
"""

from __future__ import annotations

import ast
import re
import sqlite3
from pathlib import Path

import pytest

from src.backup import merge as merge_mod
from src.database.models import Article, ArticleKeyword

_SRC = Path(merge_mod.__file__).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
#  the premise: windowing really can change the answer
# --------------------------------------------------------------------------- #
def test_a_not_exists_does_not_see_the_same_statements_own_inserts() -> None:
    """The measured premise the whole registry rests on.

    If this ever stops being true (a SQLite change, a different driver), the
    justification requirement below becomes unnecessary rather than wrong -- but
    we would want to KNOW, because the reasoning in _WINDOWED_STEPS is written on
    top of it.
    """
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE tgt (id INTEGER PRIMARY KEY, k TEXT)")
    con.execute("CREATE TABLE inc (id INTEGER PRIMARY KEY, k TEXT)")
    con.executemany("INSERT INTO inc VALUES (?,?)", [(1, "same"), (2, "same")])
    con.execute(
        "INSERT INTO tgt (k) SELECT i.k FROM inc i"
        " WHERE NOT EXISTS (SELECT 1 FROM tgt m WHERE m.k = i.k)"
    )
    assert con.execute("SELECT count(*) FROM tgt").fetchone()[0] == 2, (
        "the whole-corpus statement no longer keeps both duplicates -- if SQLite now "
        "sees its own inserts, re-read _WINDOWED_STEPS: its justification requirement "
        "may have become unnecessary"
    )


def test_windowing_that_step_would_keep_only_one() -> None:
    """The other half: the same statement, bounded and committed, keeps one."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE tgt (id INTEGER PRIMARY KEY, k TEXT)")
    con.execute("CREATE TABLE inc (id INTEGER PRIMARY KEY, k TEXT)")
    con.executemany("INSERT INTO inc VALUES (?,?)", [(1, "same"), (2, "same")])
    for lo, hi in ((0, 1), (1, 2)):
        con.execute(
            "INSERT INTO tgt (k) SELECT i.k FROM inc i"
            " WHERE NOT EXISTS (SELECT 1 FROM tgt m WHERE m.k = i.k)"
            " AND i.id > ? AND i.id <= ?",
            (lo, hi),
        )
        con.commit()
    assert con.execute("SELECT count(*) FROM tgt").fetchone()[0] == 1


# --------------------------------------------------------------------------- #
#  the registry is enforced, on the real path
# --------------------------------------------------------------------------- #
def test_every_windowed_call_site_is_registered() -> None:
    """No step may opt into windowing without declaring why that is safe.

    Reads the SOURCE for ``src=`` arguments rather than the registry, so adding a
    windowed call site and forgetting the registry entry reddens here. The
    literal-vs-variable split matters: ``src=table`` inside the link-table loop
    is a variable, so its two real values are named explicitly.
    """
    literal = set(re.findall(r'src="([a-z_]+)"', _SRC))
    # the one non-literal call site: the loop over the two link tables
    loop_tables = set(re.findall(r'\(\s*"(article_keywords?[a-z_]*)",\s*"', _SRC))
    assert "article_keyword_association" in loop_tables and "article_keywords" in loop_tables, (
        "the link-table loop's table names moved -- this guard can no longer see them"
    )
    used = literal | loop_tables
    assert used, "found no windowed call sites at all -- this guard is not reading the source"
    unregistered = used - set(merge_mod._WINDOWED_STEPS)
    assert not unregistered, f"windowed but unregistered: {sorted(unregistered)}"


def test_an_unregistered_step_is_refused_at_runtime() -> None:
    """Enforced on the real path, not only by the source guard above.

    A source-level check can be defeated by a call site it cannot parse; this
    cannot.
    """
    con = sqlite3.connect(":memory:")
    with pytest.raises(ValueError, match="not a registered windowed step"):
        merge_mod._insert_tracked(
            con, 1, "whatever",
            "INSERT INTO whatever SELECT * FROM inc.whatever i WHERE 1=1" + merge_mod._WINDOW_MARK,
            src="not_a_real_step",
        )


def test_every_justification_is_one_of_the_three_admissible_kinds() -> None:
    bad = {t: j for t, j in merge_mod._WINDOWED_STEPS.items()
           if j not in merge_mod._WINDOW_JUSTIFICATIONS}
    assert not bad, f"unrecognised justification(s): {bad}"


def test_the_two_registries_are_disjoint_and_the_reasons_are_real() -> None:
    """A step cannot be both windowed and deliberately-not, and "not windowed"
    must carry a REASON -- an empty string would read as considered when it was
    not."""
    both = set(merge_mod._WINDOWED_STEPS) & set(merge_mod._NOT_WINDOWED)
    assert not both, f"listed in both registries: {sorted(both)}"
    for t, reason in merge_mod._NOT_WINDOWED.items():
        assert len(reason) > 40, f"{t}'s reason is too thin to be a reason: {reason!r}"


# --------------------------------------------------------------------------- #
#  the justifications are checked against reality, not against themselves
# --------------------------------------------------------------------------- #
def test_a_rep_justification_really_has_a_materialise_rep_call() -> None:
    """"rep" is only true if the step actually builds one and joins it.

    Checked against the SQL, because the registry saying "rep" and the statement
    still carrying an inline ``GROUP BY`` is precisely the drift this catches.
    """
    for table, just in merge_mod._WINDOWED_STEPS.items():
        if just != "rep":
            continue
        assert f'src="{table}"' in _SRC, f"{table} claims rep but is not a windowed call site"
    # every materialised rep is joined on the id, not re-grouped inline
    names = re.findall(r'_materialise_rep\(\s*con,\s*"(\w+)"', _SRC)
    assert len(names) == sum(1 for j in merge_mod._WINDOWED_STEPS.values() if j == "rep"), (
        f"materialised reps {names} do not match the steps claiming 'rep'"
    )
    for n in names:
        assert f"temp.{n} rep ON rep.rep_id = i.id" in _SRC, (
            f"{n} is materialised but not joined on rep_id = i.id"
        )


def _sql_literals() -> str:
    """Every string literal in merge.py that is NOT a docstring.

    A bare ``"X" not in source`` guard over a removal is satisfied by nothing and
    broken by everything: the comment or docstring that RECORDS the removal
    necessarily quotes the removed text, so the guard fails against correct code
    (it did, on the first run of the test below). Rewording the explanation is
    the wrong repair -- that explanation is what a future session reads before
    deciding the removal was a mistake.

    So parse instead of grep, and keep only the literals that can actually BE
    SQL. ``ast`` gives an exact docstring test (first statement of a module,
    class or function body), which no regex over triple quotes does.
    """
    tree = ast.parse(_SRC)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            docstrings.add(id(body[0].value))
    return "\n".join(
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    )


def _windowed_call_sql() -> dict[str, str]:
    """The SQL of every ``_insert_tracked(..., src=...)`` call, by source table.

    Scoped with ``ast`` rather than by searching the file, because an inline rep
    sub-query is only a BUG INSIDE A WINDOWED STATEMENT -- an unwindowed step's
    runs once and is fine. The first draft of the test below asserted the pattern
    was absent from the whole module and duly failed on ``commodity_prices``,
    which is not windowed and never will be (it scales with symbols x days, not
    with the corpus). A guard that fires on correct code gets relaxed, and a
    relaxed guard catches nothing.
    """
    out: dict[str, str] = {}
    for node in ast.walk(ast.parse(_SRC)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_insert_tracked"):
            continue
        src = next((k.value for k in node.keywords if k.arg == "src"), None)
        if src is None:
            continue
        name = src.value if isinstance(src, ast.Constant) else "<variable:table>"
        out[name] = "\n".join(
            n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        )
    return out


def test_no_windowed_statement_still_carries_an_inline_group_by() -> None:
    """The quadratic shape the materialisation exists to remove must be GONE
    from the statements that are actually windowed."""
    calls = _windowed_call_sql()
    assert calls, "found no windowed calls -- this guard is not reading the source"
    offenders = {t: s for t, s in calls.items() if "MIN(id) AS rep_id" in s}
    assert not offenders, (
        f"inline rep sub-query inside a WINDOWED statement: {sorted(offenders)} -- it "
        "re-runs its GROUP BY once per window"
    )
    # anti-vacuity: the extractor must really be reaching the SQL, or the
    # assertion above is satisfied by a dict of empty strings.
    assert any("INSERT INTO keywords" in s for s in calls.values()), (
        "_windowed_call_sql is not capturing the statements' SQL"
    )


def test_the_unwindowed_inline_reps_are_still_present_and_deliberate() -> None:
    """The negative-space twin: the guard above must not be passing because
    someone removed every rep sub-query in the module.

    ``commodity_prices`` legitimately keeps its inline form. If that ever
    disappears, the guard above loses the only thing that distinguishes "scoped
    correctly" from "matches nothing anywhere".
    """
    assert "MIN(id) AS rep_id" in _sql_literals(), (
        "no inline rep sub-query survives anywhere -- the scoped guard above can no "
        "longer be distinguished from a vacuous one"
    )


def test_a_constraint_justification_is_backed_by_or_ignore() -> None:
    """"constraint" means the TARGET collapses the second candidate. That only
    works with OR IGNORE -- a plain INSERT would abort the whole merge instead."""
    for table, just in merge_mod._WINDOWED_STEPS.items():
        if just != "constraint":
            continue
        pat = rf"INSERT OR IGNORE INTO {{table}}|INSERT OR IGNORE INTO {re.escape(table)}"
        assert re.search(pat, _SRC), f"{table} claims 'constraint' but its insert is not OR IGNORE"


def test_a_unique_justification_is_backed_by_the_schema() -> None:
    """"unique" is a claim about the MODEL, so read the model.

    ``articles.hash`` being unique=True is what made the already-shipped articles
    windowing safe. That was true by luck rather than by check when it shipped;
    this is the check.
    """
    assert Article.__table__.columns["hash"].unique is True, (
        "articles.hash is no longer unique, so the articles step's 'unique' justification "
        "is false and windowing it can now collapse incoming duplicates"
    )


# --------------------------------------------------------------------------- #
#  _materialise_rep itself
# --------------------------------------------------------------------------- #
def _rep_fixture() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.execute("ATTACH ':memory:' AS inc")
    con.execute("CREATE TABLE inc.keywords (id INTEGER PRIMARY KEY, normalized_term TEXT, language TEXT)")
    con.executemany(
        "INSERT INTO inc.keywords VALUES (?,?,?)",
        [(1, "wheat", "en"), (2, "wheat", "en"), (3, "wheat", "fr"),
         (4, "blé", None), (5, "blé", "en"), (6, "wheat", None)],
    )
    return con


def test_materialise_rep_picks_the_same_rows_as_the_inline_group_by() -> None:
    """Set equality, not a count -- a count agrees for the wrong reasons."""
    con = _rep_fixture()
    inline = {
        r[0] for r in con.execute(
            "SELECT i.id FROM inc.keywords i JOIN"
            " (SELECT normalized_term, COALESCE(language,'en') AS lang, MIN(id) AS rep_id"
            "  FROM inc.keywords GROUP BY normalized_term, COALESCE(language,'en')) rep"
            " ON rep.normalized_term = i.normalized_term"
            " AND rep.lang = COALESCE(i.language,'en') AND rep.rep_id = i.id"
        )
    }
    merge_mod._materialise_rep(
        con, "rep_keywords",
        "SELECT MIN(id) FROM inc.keywords GROUP BY normalized_term, COALESCE(language,'en')",
    )
    materialised = {
        r[0] for r in con.execute(
            "SELECT i.id FROM inc.keywords i JOIN temp.rep_keywords rep ON rep.rep_id = i.id"
        )
    }
    assert materialised == inline
    # and it really did collapse something, or the comparison proves nothing
    assert len(inline) < 6, "the fixture has no duplicates to collapse -- this test is vacuous"


def test_a_materialised_rep_survives_the_commit_between_windows() -> None:
    """Load-bearing: the windowed loop COMMITs, and the rep join must still work.

    A temp table's lifetime is the connection, not the transaction -- the same
    property temp.map_* has always relied on. Pinned because if it were false,
    every rep-justified step would fail on its SECOND window, which is a state no
    small fixture reaches.
    """
    con = _rep_fixture()
    merge_mod._materialise_rep(
        con, "rep_keywords",
        "SELECT MIN(id) FROM inc.keywords GROUP BY normalized_term, COALESCE(language,'en')",
    )
    before = con.execute("SELECT count(*) FROM temp.rep_keywords").fetchone()[0]
    con.execute("BEGIN IMMEDIATE")
    con.execute("COMMIT")
    con.execute("BEGIN IMMEDIATE")
    con.execute("COMMIT")
    assert con.execute("SELECT count(*) FROM temp.rep_keywords").fetchone()[0] == before


def test_materialise_rep_is_idempotent_across_reruns() -> None:
    """A restore that re-runs a step must not accumulate a doubled rep set."""
    con = _rep_fixture()
    sql = "SELECT MIN(id) FROM inc.keywords GROUP BY normalized_term, COALESCE(language,'en')"
    first = merge_mod._materialise_rep(con, "rep_keywords", sql)
    second = merge_mod._materialise_rep(con, "rep_keywords", sql)
    assert first == second
    assert con.execute("SELECT count(*) FROM temp.rep_keywords").fetchone()[0] == first


def test_materialise_rep_refuses_an_unsafe_table_name() -> None:
    con = sqlite3.connect(":memory:")
    with pytest.raises(ValueError, match="unsafe temp table name"):
        merge_mod._materialise_rep(con, "rep; DROP TABLE x", "SELECT 1")


# --------------------------------------------------------------------------- #
#  windowing on a non-id key
# --------------------------------------------------------------------------- #
def test_a_window_key_must_be_a_plain_identifier() -> None:
    con = sqlite3.connect(":memory:")
    with pytest.raises(ValueError, match="unsafe window key"):
        merge_mod._insert_tracked(
            con, 1, "articles",
            "INSERT INTO articles SELECT * FROM inc.articles i WHERE 1=1" + merge_mod._WINDOW_MARK,
            src="articles", src_key="id) OR 1=1 --",
        )


def test_the_link_tables_window_on_article_id_not_id() -> None:
    """They have a COMPOSITE primary key and no surrogate, so ``id`` would fail
    outright -- but silently doing the wrong thing is the risk worth pinning, not
    the crash."""
    assert 'src_key="article_id"' in _SRC
    assert "id" not in ArticleKeyword.__table__.columns, (
        "article_keywords gained an `id` -- windowing it on article_id still works, but the "
        "reason recorded at the call site is now stale"
    )
