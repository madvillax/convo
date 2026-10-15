"""Create the PostgreSQL engine and SQLAlchemy session factory.

Each database operation gets its own short-lived session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from convo.core.config import Settings

if TYPE_CHECKING:
    SessionFactory = sessionmaker[Session]


def make_session_factory(settings: Settings) -> tuple[Engine, SessionFactory]:
    engine = create_engine(
        settings.database_url,
        pool_pre_ping=True,
        echo=False,
        connect_args={"connect_timeout": 10},
    )
    return engine, sessionmaker(engine, expire_on_commit=False)
