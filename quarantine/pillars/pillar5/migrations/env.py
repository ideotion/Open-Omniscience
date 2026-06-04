"""
Pillar 5: Financial Intelligence - Alembic Environment Configuration

This module configures Alembic for Pillar 5's database migrations.
"""

import sys
from pathlib import Path
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# Add pillar5 to Python path
# When running from pillar5 directory, __file__ is pillar5/migrations/env.py
# So parent.parent is the workspace root
pillar5_path = Path(__file__).parent.parent.resolve()
# Also add the parent (pillar5) to the path
sys.path.insert(0, str(pillar5_path.parent))
sys.path.insert(0, str(pillar5_path))

# Import Pillar 5's Base metadata
from pillar5.src.models import Base

# This is the Alembic Config object, which provides access to the .ini file values.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Add Pillar 5's model metadata for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
