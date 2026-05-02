"""Alembic environment — async-friendly.

Imports every model so ``Base.metadata`` is fully populated before
``--autogenerate`` runs. Phase 4+ will append real domain-model imports
below the placeholder import.

Reference: BACKEND_BLUEPRINT.md §9.1.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.core.config import get_settings
from app.core.db_base import Base

# IMPORTANT: import every domain.<context>.models so they register on
# Base.metadata BEFORE autogenerate runs.
import app.domain.catalog.models
import app.domain.identity.models
import app.domain.inventory.models
import app.domain.ops.models  # noqa: F401

# Phase 6+ will add:
#   import app.domain.orders.models
#   import app.domain.payments.models
#   import app.domain.deliveries.models

settings = get_settings()
config = context.config
config.set_main_option("sqlalchemy.url", str(settings.mysql_dsn))

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL for offline migration (no live connection)."""
    context.configure(
        url=str(settings.mysql_dsn),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
