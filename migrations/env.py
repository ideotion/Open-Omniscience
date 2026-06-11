"""
Alembic environment for Open Omniscience.

Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pulls the target metadata from the live models and the database URL from the same
settings the app uses (src.database.session), so `alembic upgrade head` migrates
exactly the database the app runs against. SQLite ALTERs run in batch mode.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context

# Live models -> autogenerate target. Importing models populates Base.metadata.
from src.database import models  # noqa: F401  (needed so all tables register)
from src.database.models import Base
from src.database.session import DATABASE_URL, engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _include_object(obj, name, type_, reflected, compare_to):
    """Ignore the SQLite FTS5 virtual table and its shadow tables, which are created
    at runtime by src/database/fts.py and are not part of the ORM metadata -- so
    `alembic check` (the CI drift gate) does not flag them as 'removed'."""
    if type_ == "table" and (name == "article_fts" or name.startswith("article_fts_")):
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL without a DB connection (`alembic upgrade --sql`)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite-safe ALTERs
        include_object=_include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the live engine, or against a connection injected via
    ``config.attributes["connection"]`` -- the staged-copy upgrade path used by the
    backup/restore pipeline, which must never touch the live database."""
    injected = config.attributes.get("connection", None)
    if injected is not None:
        context.configure(
            connection=injected,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite-safe ALTERs
            include_object=_include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite-safe ALTERs
            include_object=_include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
