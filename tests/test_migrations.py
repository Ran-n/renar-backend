#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/15 11:00:47.855143
Revised: 2026/11/15 11:01:41.278520

Alembic history guard: the migrations must build, on an empty database,
the same schema the models describe.

The rest of the suite builds its schema with ``Base.metadata.create_all()``
and never runs a migration, which is how replaying the history on an empty
database stayed broken unnoticed: revision ``a7c2e9f4b816`` imported the
trigger SQL from ``renar_backend.db_triggers`` (today's SQL), which by then
named ``users.email_confirmed``, a column a later revision adds.

What this file pins down:

- ``alembic upgrade head`` on an empty schema reaches the head revision.
- The schema it builds has no difference from the models (the check
  ``alembic check`` makes), so a fresh install equals a migrated one.
- Its trigger functions and triggers are the ones ``create_all()`` installs
  from ``db_triggers.py``: changing that module without a migration fails.
- No migration imports application code, the root cause of the above.

Downgrading to base is deliberately not covered: ``a3f8c1e97b52`` (remove
book and youtube media types) deleted rows and enum values and is declared
irreversible, so the history only replays forwards.
"""

import ast
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from conftest import _PG_BASE_URL, _SCHEMA
from sqlalchemy import Engine, create_engine, text

from renar_backend.database import Base

pytestmark = pytest.mark.regression

_ROOT = Path(__file__).resolve().parent.parent
_VERSIONS = _ROOT / "alembic" / "versions"
_APP_PACKAGE = "renar_backend"

_FUNCTIONS_SQL = text(
    """
    SELECT p.proname, pg_get_function_arguments(p.oid), p.prosrc
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = :schema
    ORDER BY 1, 2
    """
)
_TRIGGERS_SQL = text(
    """
    SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid)
    FROM pg_trigger t
    JOIN pg_class c ON c.oid = t.tgrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = :schema AND NOT t.tgisinternal
    ORDER BY 1, 2
    """
)


def _schema_url(schema: str) -> str:
    return f"{_PG_BASE_URL}?options=-csearch_path%3D{schema}"


@pytest.fixture(scope="module")
def migrated_schema() -> Iterator[str]:
    """A throwaway schema built only by ``alembic upgrade head``, in a child
    process (alembic/env.py reads DATABASE_URL at import time)."""
    schema = f"renar_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(_PG_BASE_URL)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        result = subprocess.run(  # noqa: S603 (fixed argv, no shell)
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "DATABASE_URL": _schema_url(schema)},
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        assert result.returncode == 0, f"alembic upgrade head failed on an empty schema:\n{result.stderr[-4000:]}"
        yield schema
    finally:
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def migrated_engine(migrated_schema: str) -> Iterator[Engine]:
    engine = create_engine(_schema_url(migrated_schema))
    yield engine
    engine.dispose()


def _routines(engine: Engine, schema: str, query) -> list[tuple]:
    """Rows of ``query`` for ``schema``, with the schema name itself removed
    so two schemas' definitions compare equal when they are the same."""
    with engine.connect() as conn:
        rows = conn.execute(query, {"schema": schema}).all()
    return [tuple(str(value).replace(f"{schema}.", "") for value in row) for row in rows]


def test_upgrade_from_empty_reaches_head(migrated_engine: Engine):
    head = ScriptDirectory.from_config(Config(str(_ROOT / "alembic.ini"))).get_current_head()
    with migrated_engine.connect() as conn:
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert current == [head]


def test_migrated_schema_matches_the_models(migrated_engine: Engine):
    with migrated_engine.connect() as conn:
        differences = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert differences == [], (
        "the schema the migrations build differs from the models: add a migration, "
        f"or fix the model to describe what the migrations built: {differences}"
    )


@pytest.mark.parametrize("query", [_FUNCTIONS_SQL, _TRIGGERS_SQL], ids=["functions", "triggers"])
def test_migrated_triggers_match_create_all(migrated_engine: Engine, migrated_schema: str, query):
    """``_fresh_db`` has just built the suite's own schema with create_all(),
    which installs today's db_triggers.py SQL; the migrations must end in the
    same functions and triggers."""
    from renar_backend.database import engine as create_all_engine

    expected = _routines(create_all_engine, _SCHEMA, query)
    assert expected, "create_all() installed no functions/triggers: the comparison would prove nothing"
    assert _routines(migrated_engine, migrated_schema, query) == expected, (
        "db_triggers.py changed without a migration that applies the new SQL "
        "(or a migration's frozen copy differs from it)"
    )


def _app_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return [name for name in names if name.split(".")[0] == _APP_PACKAGE]


def test_no_migration_imports_application_code():
    """A migration is a frozen fact about one moment; importing the app makes
    it change meaning whenever the app does, and breaks replaying history."""
    offenders = {path.name: found for path in sorted(_VERSIONS.glob("*.py")) if (found := _app_imports(path))}
    assert offenders == {}, f"migrations import application code; inline a frozen copy instead: {offenders}"


def test_app_import_scan_sees_both_import_forms(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import os\nimport renar_backend.db_triggers\nfrom renar_backend.models import User\nfrom alembic import op\n",
        encoding="utf-8",
    )
    assert _app_imports(sample) == ["renar_backend.db_triggers", "renar_backend.models"]
