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
    # disable_existing_loggers defaults to True, which silently DISABLES every
    # pre-existing logger not listed in alembic.ini's [loggers] (root, sqlalchemy,
    # alembic only) for the rest of the process -- caught 2026-07-26 when the app's
    # own boot-time Alembic self-heal (init_db()) disabled the already-imported
    # `trafilatura`/`trafilatura.metadata`/`htmldate` loggers, silently swallowing
    # their diagnostics (including the noise-filtered ERROR the W4 fix targets)
    # forever after. uvicorn's own default logging config makes the same call with
    # this same override for the identical reason.
    #
    # TWO DISTINCT FAILURE MODES, both real, kept together deliberately: the
    # first is the production one (an app logger muted for the rest of the
    # process), the second is the test one (a caplog assertion that silently
    # loses every record). They were written by separate passes against the
    # same setting; neither supersedes the other.
    # disable_existing_loggers=False (fileConfig's own default is True): the bare
    # default silently sets `.disabled = True` on EVERY pre-existing logger not
    # explicitly named in alembic.ini's [loggers] (only root/sqlalchemy/alembic are
    # listed there) -- permanently, process-wide, for the rest of the run. Any test
    # elsewhere in the suite that triggers an `alembic upgrade`/`alembic check` (which
    # imports this module) BEFORE it, and that later asserts on a caplog-captured
    # WARNING from an app-module logger (e.g. src.briefing.registry, src.analytics.
    # columnar), silently loses every record -- `caplog.at_level()` only sets a
    # logger's `.level`, never its `.disabled` flag, so it cannot undo this.
    # Empirically confirmed (a standalone repro: getLogger() before fileConfig(),
    # then fileConfig() with the bare default -> .disabled flips True and every
    # later .warning() call is silently dropped). Same class of production risk too:
    # a real boot-time migration self-heal would silently mute ordinary app logging
    # for the rest of the process. Never intentional here -- keep it off.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

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
