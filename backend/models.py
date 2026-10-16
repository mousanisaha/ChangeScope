"""SQLAlchemy ORM models for ChangeScope.

Defines schemas for monitored websites, snapshots, and detected changes.
"""

from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def utc_now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


class User(Base):
    """User account model for authentication, authorization, and multi-tenant isolation."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_checks_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    sites: Mapped[List["MonitoredSite"]] = relationship(
        "MonitoredSite", back_populates="user", cascade="all, delete-orphan", order_by="desc(MonitoredSite.created_at)"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan", order_by="desc(Notification.created_at)"
    )
    notification_preferences: Mapped[Optional["NotificationPreference"]] = relationship(
        "NotificationPreference", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class MonitoredSite(Base):
    """Represents a website registered by the user for automated monitoring."""

    __tablename__ = "monitored_sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), default=1, nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    check_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    capture_screenshots: Mapped[bool] = mapped_column(Boolean, default=False)
    visual_threshold: Mapped[float] = mapped_column(Float, default=1.0)

    # Telemetry and state from latest check
    last_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_response_time_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="sites")
    snapshots: Mapped[List["SiteSnapshot"]] = relationship(
        "SiteSnapshot", back_populates="site", cascade="all, delete-orphan", order_by="desc(SiteSnapshot.created_at)"
    )
    changes: Mapped[List["DetectedChange"]] = relationship(
        "DetectedChange", back_populates="site", cascade="all, delete-orphan", order_by="desc(DetectedChange.created_at)"
    )
    check_logs: Mapped[List["SiteCheckLog"]] = relationship(
        "SiteCheckLog", back_populates="site", cascade="all, delete-orphan", order_by="desc(SiteCheckLog.created_at)"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification", back_populates="site", cascade="all, delete-orphan", order_by="desc(Notification.created_at)"
    )


class SiteSnapshot(Base):
    """Historical snapshot capturing a point-in-time state of a monitored website."""

    __tablename__ = "site_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    site_id: Mapped[int] = mapped_column(Integer, ForeignKey("monitored_sites.id", ondelete="CASCADE"), index=True)

    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_time_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    text_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    screenshot_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    screenshot_width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    screenshot_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    screenshot_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    visual_diff_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    visual_change_detected: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    screenshot_error: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    # Relationships
    site: Mapped["MonitoredSite"] = relationship("MonitoredSite", back_populates="snapshots")


class DetectedChange(Base):
    """Records a detected change between consecutive snapshots of a site."""

    __tablename__ = "detected_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    site_id: Mapped[int] = mapped_column(Integer, ForeignKey("monitored_sites.id", ondelete="CASCADE"), index=True)

    change_type: Mapped[str] = mapped_column(String(32), default="text")  # "text", "visual", "availability"
    summary: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    previous_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    # Relationships
    site: Mapped["MonitoredSite"] = relationship("MonitoredSite", back_populates="changes")


class SiteCheckLog(Base):
    """Historical telemetry log for each check cycle (successful and failed)."""

    __tablename__ = "site_check_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    site_id: Mapped[int] = mapped_column(Integer, ForeignKey("monitored_sites.id", ondelete="CASCADE"), index=True)

    status: Mapped[str] = mapped_column(String(32), default="success")  # "baseline_created", "unchanged", "change_detected", "check_failed"
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    # Relationships
    site: Mapped["MonitoredSite"] = relationship("MonitoredSite", back_populates="check_logs")


class Notification(Base):
    """Persistent alert record for detected changes and monitoring failures."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), default=1, nullable=True, index=True
    )
    site_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("monitored_sites.id", ondelete="CASCADE"), nullable=True, index=True
    )

    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # "text_change", "visual_change", "check_failed"
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    link_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # "change", "visual", "monitor"
    link_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    dedup_key: Mapped[Optional[str]] = mapped_column(String(128), unique=True, index=True, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="notifications")
    site: Mapped[Optional["MonitoredSite"]] = relationship("MonitoredSite", back_populates="notifications")


class NotificationPreference(Base):
    """User preferences for enabling or disabling specific alert event types."""

    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), default=1, nullable=True, index=True
    )
    notify_text_change: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_visual_change: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_check_failed: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="notification_preferences")


class SchedulerSetting(Base):
    """Global scheduler and automation preferences."""

    __tablename__ = "scheduler_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    auto_checks_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer, default=5)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

