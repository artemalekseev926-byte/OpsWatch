from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from opswatch.db import Base, utcnow


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id", ondelete="SET NULL"), nullable=True)
    role: Mapped[Role | None] = relationship(lazy="joined")
    telegram_username: Mapped[str] = mapped_column(String(100), default="")
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    telegram_link_code: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    telegram_link_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    personal_bot_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    personal_bot_username: Mapped[str] = mapped_column(String(100), default="")
    personal_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notify_telegram: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_desktop: Mapped[bool] = mapped_column(Boolean, default=False)
    quiet_start: Mapped[str] = mapped_column(String(5), default="")
    quiet_end: Mapped[str] = mapped_column(String(5), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(8), default="ru", server_default="ru")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    client: Mapped[str] = mapped_column(String(300), default="")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    secrets: Mapped[str] = mapped_column(Text, default="")
    poll_interval: Mapped[int] = mapped_column(Integer, default=60)
    visible_roles: Mapped[list] = mapped_column(JSON, default=list)
    ingest_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(16), default="unknown")
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_name: Mapped[str] = mapped_column(String(200), default="")
    category: Mapped[str] = mapped_column(String(32), index=True)
    type: Mapped[str] = mapped_column(String(100), default="event")
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(500))
    message: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)
    reporter_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acked_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution: Mapped[str] = mapped_column(Text, default="")
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escalation: Mapped[list] = mapped_column(JSON, default=list)
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)

    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="event", cascade="all, delete-orphan", lazy="selectin"
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    stored_name: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    event: Mapped[Event] = relationship(back_populates="attachments")


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    event_types: Mapped[list] = mapped_column(JSON, default=list)
    min_severity: Mapped[str] = mapped_column(String(16), default="warning")
    target_roles: Mapped[list] = mapped_column(JSON, default=list)
    target_users: Mapped[list] = mapped_column(JSON, default=list)
    escalate_after_min: Mapped[int] = mapped_column(Integer, default=0)
    escalate_roles: Mapped[list] = mapped_column(JSON, default=list)
    escalate_users: Mapped[list] = mapped_column(JSON, default=list)
    stop: Mapped[bool] = mapped_column(Boolean, default=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    min_severity: Mapped[str] = mapped_column(String(16), default="info")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(16), default="event")
    title: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16), default="info")
    category: Mapped[str] = mapped_column(String(32), default="system")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    telegram_status: Mapped[str] = mapped_column(String(16), default="pending")
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_via_personal: Mapped[bool] = mapped_column(Boolean, default=False)


class BackupJob(Base):
    __tablename__ = "backup_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"), nullable=True)
    schedule: Mapped[str] = mapped_column(String(100), default="0 2 * * *")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    keep_last: Mapped[int] = mapped_column(Integer, default=7)
    encrypt: Mapped[bool] = mapped_column(Boolean, default=True)
    password: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    destinations: Mapped[dict] = mapped_column(JSON, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="never")
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BackupRecord(Base):
    __tablename__ = "backup_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("backup_jobs.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    manual: Mapped[bool] = mapped_column(Boolean, default=False)
    file_path: Mapped[str] = mapped_column(Text, default="")
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class MetricPoint(Base):
    __tablename__ = "metric_points"
    __table_args__ = (Index("ix_metric_points_series", "source_id", "name", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64))
    value: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
