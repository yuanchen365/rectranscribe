from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session


def get_database_url(app_root: str) -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    # Default to SQLite in project root
    return f"sqlite:///{os.path.join(app_root, 'app.db')}"


class Database:
    def __init__(self, url: str):
        # check_same_thread=False to allow usage in Flask threaded server
        connect_args = {"check_same_thread": False} if url.startswith("sqlite:") else {}
        self.engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
        self._session_factory = scoped_session(sessionmaker(bind=self.engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True))

    @property
    def session(self):
        return self._session_factory()

    def remove(self):
        self._session_factory.remove()

    @contextmanager
    def session_scope(self) -> Generator:
        session = self.session
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

