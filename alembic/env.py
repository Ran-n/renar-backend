#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 10:19:09.196421
Revised: 2026/11/15 11:01:41.837600
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from renar_backend import models  # noqa: F401  (registers all tables on Base.metadata)
from renar_backend.config import settings
from renar_backend.database import Base

config = context.config
# "%" is configparser's interpolation character: a URL-encoded option
# (e.g. options=-csearch_path%3Dschema) must have it doubled to survive.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
