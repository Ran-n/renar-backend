#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/13 15:35:10.062622
Revised: 2026/11/13 15:35:10.062622

Staging for "another worker inserted it first" branches. They can't be hit
by timing in a single-threaded test, so the competing row is committed from
a second session and this session is made to miss it: `hide_selects` blanks
this session's next SELECTs on one entity. The INSERT, the real
unique-index IntegrityError, the savepoint rollback and the re-query all
still run against real Postgres.
"""

from sqlalchemy import event, false
from sqlalchemy.exc import IntegrityError

from renar_backend.database import SessionLocal


def commit_elsewhere(*rows) -> list[int | None]:
    """Commit rows from a second session, the way a parallel worker would;
    returns their ids (None for a table keyed by something else)."""
    other = SessionLocal()
    try:
        other.add_all(rows)
        other.commit()
        return [getattr(row, "id", None) for row in rows]
    finally:
        other.close()


def hide_selects(session, entity, *, times: int | None):
    """Make this session's next `times` SELECTs on `entity` (every one if
    None) come back empty, as if the competing insert hadn't committed yet.

    `session` may also be a sessionmaker, to reach the session a request
    handler opens itself; the returned callable removes the hook."""
    remaining = [times]

    def _blank(state):
        if not state.is_select or entity not in [d.get("entity") for d in state.statement.column_descriptions]:
            return
        if remaining[0] is not None:
            if remaining[0] <= 0:
                return
            remaining[0] -= 1
        state.statement = state.statement.where(false())

    event.listen(session, "do_orm_execute", _blank)
    return lambda: event.remove(session, "do_orm_execute", _blank)


def integrity_error() -> IntegrityError:
    return IntegrityError("INSERT ...", {}, Exception("duplicate key value violates unique constraint"))
