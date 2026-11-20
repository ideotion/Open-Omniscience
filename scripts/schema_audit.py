#!/usr/bin/env python3
"""Write the schema-freeze inventory: every table and column, the migration chain, and the format identifiers (0.8 row B).

Open Omniscience - Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``RELEASE_0.8_GATE.md`` row B asks for «a written schema-freeze audit [that] lists the tables and the migrations after
which only additive ones follow» (Q102 = a; brief S08-02 S5). The judgement in that audit (which migration the freeze
starts after, which pending column is declared additive) is the 0.8 session's; the FACTS it judges are generated here,
from the code itself, so they cannot drift from it unseen:

* the main database: every ORM table and column (``src.database.models.Base``) and the Alembic chain, base to head;
* the lane stores (wiki, law, OSM, medical and the shared versioned tables): every table and column of ``LaneBase``,
  under the module that declares it;
* the tables made by raw DDL at run time (``CREATE TABLE`` / ``CREATE VIRTUAL TABLE`` in ``src/``), outside Alembic;
* the backup, export and custody format identifiers (the public ``"oo-..."`` constants of ``src/backup``,
  ``src/utils/export_envelope.py`` and ``src/custody/log.py``).

    python scripts/schema_audit.py            # writes docs/product/SCHEMA_FREEZE_INVENTORY.md
    python scripts/schema_audit.py --check    # exit 1 if the committed file differs from the code (names the lines)
    python scripts/schema_audit.py --stdout   # prints it

The output holds no date and no machine fact, so the same tree always gives the same file. Nothing is opened, migrated
or read from a database: the models, the migration scripts and the source text are the whole input.
"""

from __future__ import annotations

import argparse
import difflib
import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "docs" / "product" / "SCHEMA_FREEZE_INVENTORY.md"
#: The modules whose models make up the lane stores (each registers its tables on ``LaneBase`` when imported).
LANE_MODULES = ("src.versioned.models", "src.wiki.lane_models", "src.law.lane_models", "src.osm.lane_models",
                "src.medical.lane_models")
#: Where a format identifier is declared: the backup package, the export envelope, the custody log.
IDENTIFIER_SOURCES = ("src/backup", "src/utils/export_envelope.py", "src/custody/log.py")

_DDL = re.compile(r"CREATE\s+(VIRTUAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?"
                  r"(?:\{([A-Z][A-Z0-9_]*)\}|(?!(?:IF|AS|SELECT)\b)([A-Za-z_][A-Za-z0-9_]*)\b)", re.I)
_IDENT = re.compile(r'^([A-Z][A-Z0-9_]*)\s*(?::[^=]+)?=\s*"(oo-[^"]*)"', re.M)


def _type(col) -> str:
    from sqlalchemy.dialects import sqlite

    try:
        return str(col.type.compile(dialect=sqlite.dialect()))
    except Exception:  # noqa: BLE001 - a type sqlite cannot compile is named by its class
        return type(col.type).__name__


def _tables(metadata, owner: dict[str, str] | None = None) -> list[str]:
    lines: list[str] = []
    for name in sorted(metadata.tables):
        table = metadata.tables[name]
        where = f" (`{owner[name]}`)" if owner and name in owner else ""
        lines.append(f"### `{name}`{where}")
        lines.append("")
        lines.append("| column | type | null | key |")
        lines.append("|---|---|---|---|")
        for col in table.columns:  # declaration order, which is the table's own
            key = "primary" if col.primary_key else ("foreign" if col.foreign_keys else "")
            lines.append(f"| `{col.name}` | {_type(col)} | {'yes' if col.nullable else 'no'} | {key} |")
        lines.append("")
    return lines


def _owners(base) -> dict[str, str]:
    out: dict[str, str] = {}
    for mapper in base.registry.mappers:
        table = getattr(mapper.class_, "__table__", None)
        if table is not None:
            out[table.name] = mapper.class_.__module__
    return out


def _migrations() -> tuple[list[str], list[str]]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    script = ScriptDirectory.from_config(cfg)
    heads = sorted(script.get_heads())
    chain = list(reversed(list(script.walk_revisions())))  # base first
    lines = []
    for i, rev in enumerate(chain, 1):
        down = rev.down_revision
        downs = ", ".join(f"`{d}`" for d in (down if isinstance(down, tuple) else (down,)) if d) or "base"
        lines.append(f"| {i} | `{rev.revision}` | {downs} | `{Path(rev.path).name}` |")
    return heads, lines


def _ddl_tables(orm: set[str]) -> list[str]:
    found: dict[str, set[str]] = {}
    for path in sorted((ROOT / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for m in _DDL.finditer(text):
            name = m.group(3)
            if m.group(2):  # an f-string naming a module constant: read the constant's literal value
                const = re.search(rf'^{m.group(2)}\s*(?::[^=\n]+)?=\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']', text, re.M)
                if const is None:
                    continue  # a name built at run time is not listed
                name = const.group(1)
            kind = "virtual" if m.group(1) else "table"
            found.setdefault(f"{name}\t{kind}", set()).add(path.relative_to(ROOT).as_posix())
    lines = []
    for key in sorted(found):
        name, kind = key.split("\t")
        also = "yes" if name in orm else ""
        lines.append(f"| `{name}` | {kind} | {also} | {', '.join(f'`{p}`' for p in sorted(found[key]))} |")
    return lines


def _identifiers() -> list[str]:
    paths: list[Path] = []
    for src in IDENTIFIER_SOURCES:
        p = ROOT / src
        paths.extend(sorted(p.rglob("*.py")) if p.is_dir() else [p])
    lines = []
    for path in paths:
        for m in _IDENT.finditer(path.read_text(encoding="utf-8")):
            lines.append(f"| `{m.group(1)}` | `{m.group(2)}` | `{path.relative_to(ROOT).as_posix()}` |")
    return lines


def render() -> str:
    from src.database.models import Base

    for mod in LANE_MODULES:
        importlib.import_module(mod)
    from src.versioned.models import LaneBase

    heads, chain = _migrations()
    lane_owner = _owners(LaneBase)
    orm = set(Base.metadata.tables) | set(LaneBase.metadata.tables)
    out = [
        "<!-- GENERATED by scripts/schema_audit.py; do not edit by hand. Regenerate with `python scripts/schema_audit.py`;",
        "     tests/test_schema_audit.py fails while this file and the code disagree. -->",
        "",
        "# Schema-freeze inventory",
        "",
        "The facts the 0.8 schema-freeze audit judges (`RELEASE_0.8_GATE.md` row B, Q102 = a, brief S08-02 S5), read from the",
        "code: the models, the migration scripts and the source text. Which migration the freeze starts after, and which",
        "pending column is declared additive, is the audit's judgement and is not written here.",
        "",
        "## 1. Main database: the migration chain",
        "",
        f"Head{'s' if len(heads) != 1 else ''}: {', '.join(f'`{h}`' for h in heads)} ({len(chain)} migrations, base first).",
        "",
        "| # | revision | after | file |",
        "|---|---|---|---|",
        *chain,
        "",
        f"## 2. Main database: tables ({len(Base.metadata.tables)}, from `src/database/models.py`)",
        "",
        *_tables(Base.metadata),
        f"## 3. Lane stores: tables ({len(LaneBase.metadata.tables)}, each under the module that declares it)",
        "",
        "One file per lane kind; each lane file holds the shared versioned tables and its own.",
        "",
        *_tables(LaneBase.metadata, lane_owner),
        "## 4. Tables made by raw DDL at run time",
        "",
        "`CREATE TABLE` and `CREATE VIRTUAL TABLE` statements in `src/` with a literal name (a name built at run time is",
        "not listed). \"ORM\" marks a name that is also a model table above.",
        "",
        "| table | kind | ORM | declared in |",
        "|---|---|---|---|",
        *_ddl_tables(orm),
        "",
        "## 5. Format identifiers",
        "",
        "The public `\"oo-...\"` constants of the backup package, the export envelope and the custody log.",
        "",
        "| constant | value | declared in |",
        "|---|---|---|",
        *_identifiers(),
        "",
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="exit 1 if the committed inventory differs from the code")
    g.add_argument("--stdout", action="store_true", help="print the inventory instead of writing it")
    a = ap.parse_args(argv)
    text = render()
    if a.stdout:
        sys.stdout.write(text)
        return 0
    if a.check:
        have = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if have == text:
            print(f"{OUT.relative_to(ROOT).as_posix()} matches the code")
            return 0
        diff = difflib.unified_diff(have.splitlines(), text.splitlines(), "committed", "from the code", lineterm="", n=0)
        print("\n".join(list(diff)[:80]))
        print(f"{OUT.relative_to(ROOT).as_posix()} is out of date: run python scripts/schema_audit.py")
        return 1
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
