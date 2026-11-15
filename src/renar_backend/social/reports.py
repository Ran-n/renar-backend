#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/11/15 00:19:53.939838
Revised: 2026/11/15 02:45:12.386957

Reports to the moderators, shared by everything reportable (comments,
reviews, profiles).

A report table has one row per (target, reporter): repeating a report is a
no-op. Reports only reach the admin panel; nothing is hidden automatically.
The log lines carry ids only, never the reason text.
"""

import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

_log = logging.getLogger(__name__)


def add_report(
    db: Session, model: type, target_column: Any, target_id: int, reporter_column: Any, reporter_id: int, reason: str
) -> bool:
    """Record `reporter_id`'s report on `target_id`. Commits.

    `model` is the report table's class, `target_column` its FK column to
    the thing reported and `reporter_column` its FK column to the reporter
    (e.g. `ReviewReport`, `ReviewReport.review_id`, `ReviewReport.reporter_id`).
    Returns whether a new report was stored. The caller checks the target
    exists and isn't the reporter's own first.
    """
    already = db.query(model).filter(target_column == target_id, reporter_column == reporter_id).first()
    if already is not None:
        return False
    db.add(model(**{target_column.key: target_id, reporter_column.key: reporter_id, "reason": reason.strip()}))
    try:
        db.commit()
    except IntegrityError:
        # the same user's concurrent request stored the report first
        db.rollback()
        _log.info("concurrent %s row by user %s on %s: kept the first", model.__tablename__, reporter_id, target_id)
        return False
    _log.info("%s: %s reported by user %s", model.__tablename__, target_id, reporter_id)
    return True


def remove_report(
    db: Session, model: type, target_column: Any, target_id: int, reporter_column: Any, reporter_id: int
) -> bool:
    """Take back `reporter_id`'s report on `target_id`. Commits. Returns
    whether a report was removed."""
    report = db.query(model).filter(target_column == target_id, reporter_column == reporter_id).first()
    if report is None:
        return False
    db.delete(report)
    db.commit()
    _log.info("%s: report on %s retracted by user %s", model.__tablename__, target_id, reporter_id)
    return True
