"""R163: ``stream_backup._corpus_facts`` counts the corpus's tables in a loop that the scale-bench CLI (scripts/run_scale_bench.py -> write_volume_backup ->
write_stream_backup) reaches on the main thread. The loop's body ended in a bare ``if``, which CPython 3.13 leaves outside the exception table of the
``try`` around it, so an interrupt delivered there would skip the ``finally`` that closes the connection (src/utils/interrupts.py;
tests/test_gates_survive_an_interrupt.py, ``_uncovered_loop_heads``). The body is unchanged; the last statement is a guard clause, and the counts are what
they were."""

from __future__ import annotations

import sqlite3

from tests.test_gates_survive_an_interrupt import _uncovered_loop_heads


def test_the_table_count_loop_keeps_its_back_edge_inside_the_try():
    left = _uncovered_loop_heads("src/backup/stream_backup.py", "_corpus_facts") & {"for t in tables:"}
    assert not left, f"stream_backup._corpus_facts: a loop's back-edge is outside the try that covers its head: {sorted(left)}"


def test_the_table_counts_are_what_they_were(tmp_path):
    from src.backup.stream_backup import _corpus_facts

    db = tmp_path / "corpus.db"
    raw = sqlite3.connect(str(db))
    raw.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT)")
    raw.execute("CREATE TABLE sources(id INTEGER PRIMARY KEY)")
    raw.executemany("INSERT INTO articles(hash) VALUES (?)", [("a",), ("b",), ("c",)])
    raw.execute("INSERT INTO sources DEFAULT VALUES")
    raw.commit()
    raw.close()
    facts, _extra = _corpus_facts(db, None)
    assert facts["tables"]["articles"] == 3
    assert facts["tables"]["sources"] == 1
