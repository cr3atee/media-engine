from __future__ import annotations

import importlib
import pkgutil
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app.config.settings import settings
from app.database.base import Base


config = context.config
config.set_main_option("sqlalchemy.url", settings.database.url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def import_model_modules() -> None:
    import app.models as models_package

    for module in pkgutil.walk_packages(
        models_package.__path__,
        prefix=f"{models_package.__name__}.",
    ):
        importlib.import_module(module.name)


import_model_modules()

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database.url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    from asyncio import run

    run(run_migrations_online())
