from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float, text
from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column
from werkzeug.security import generate_password_hash, check_password_hash


Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)
    email_verified = Column(Boolean, default=False, nullable=False)
    role = Column(String(50), default="user", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    google_sub = Column(String(255), unique=True, nullable=True, index=True)
    display_name = Column(String(255), nullable=True)
    avatar_url = Column(String(512), nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    plan = Column(String(50), default="free", nullable=False)

    jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan")
    usages = relationship("Usage", back_populates="user", cascade="all, delete-orphan")

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_active(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String(32), default="queued", nullable=False)
    src_filename = Column(String(512), nullable=True)
    model = Column(String(128), nullable=True)
    language = Column(String(32), nullable=True)
    segments = Column(Integer, nullable=True)
    cost_tokens = Column(Integer, nullable=True)
    cost_usd = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    output_dir_rel = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="jobs")


class Usage(Base):
    __tablename__ = "usages"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    action = Column(String(64), nullable=False)
    quantity = Column(Float, nullable=False, default=0)
    meta = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="usages")


def create_all(engine):
    Base.metadata.create_all(engine)


def ensure_user_columns(engine):
    """Simple helper to add new columns when running on an existing SQLite DB."""
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
        alters = []
        if "google_sub" not in existing:
            alters.append("ALTER TABLE users ADD COLUMN google_sub VARCHAR(255)")
        if "display_name" not in existing:
            alters.append("ALTER TABLE users ADD COLUMN display_name VARCHAR(255)")
        if "avatar_url" not in existing:
            alters.append("ALTER TABLE users ADD COLUMN avatar_url VARCHAR(512)")
        if "last_login_at" not in existing:
            alters.append("ALTER TABLE users ADD COLUMN last_login_at DATETIME")
        if "plan" not in existing:
            alters.append("ALTER TABLE users ADD COLUMN plan VARCHAR(50) NOT NULL DEFAULT 'free'")
        if "password_hash" in existing:
            # ensure column allows NULL (SQLite ignores constraint changes, but safe for rebuild)
            pass
        for stmt in alters:
            conn.execute(text(stmt))

