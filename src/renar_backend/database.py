#!/usr/bin/env python3
"""
Authors: Ran# <ran.hash@proton.me>
Created: 2026/07/17 10:19:00.957877
Revised: 2026/07/21 13:55:50.540909
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

# connect_timeout (seconds, libpq-native) caps how long a *new* connection
# attempt can hang when the DB host is unreachable, so a request fails fast
# with a clear error instead of hanging on the OS TCP timeout.
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5})

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
