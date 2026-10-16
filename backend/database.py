"""Database configuration and session management for ChangeScope.

Uses SQLite for persistent storage with SQLAlchemy 2.0 ORM.
"""

import os
from collections.abc import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

# Default to a local SQLite database file in the project root
DEFAULT_DB_FILE = "changescope.db"
DATABASE_URL = os.getenv("CHANGESCOPE_DATABASE_URL", f"sqlite:///./{DEFAULT_DB_FILE}")

# check_same_thread=False is required for SQLite when accessed across multiple threads in FastAPI
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and ensures it is closed after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialize database tables defined in models.py and migrate missing columns."""
    # Import models here so they are registered with Base.metadata before creation
    from backend import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # Lightweight migration helper for SQLite when new columns are added to existing DB
    if engine.url.drivername.startswith("sqlite"):
        with engine.begin() as conn:
            # Check monitored_sites columns
            try:
                existing_site_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(monitored_sites)").fetchall()}
                if "capture_screenshots" not in existing_site_cols:
                    conn.exec_driver_sql("ALTER TABLE monitored_sites ADD COLUMN capture_screenshots BOOLEAN DEFAULT 0")
                if "visual_threshold" not in existing_site_cols:
                    conn.exec_driver_sql("ALTER TABLE monitored_sites ADD COLUMN visual_threshold FLOAT DEFAULT 1.0")
                if "user_id" not in existing_site_cols:
                    conn.exec_driver_sql("ALTER TABLE monitored_sites ADD COLUMN user_id INTEGER REFERENCES users(id)")

                # Check site_snapshots columns
                existing_snap_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(site_snapshots)").fetchall()}
                if "screenshot_width" not in existing_snap_cols:
                    conn.exec_driver_sql("ALTER TABLE site_snapshots ADD COLUMN screenshot_width INTEGER")
                if "screenshot_height" not in existing_snap_cols:
                    conn.exec_driver_sql("ALTER TABLE site_snapshots ADD COLUMN screenshot_height INTEGER")
                if "screenshot_size_bytes" not in existing_snap_cols:
                    conn.exec_driver_sql("ALTER TABLE site_snapshots ADD COLUMN screenshot_size_bytes INTEGER")
                if "visual_diff_percent" not in existing_snap_cols:
                    conn.exec_driver_sql("ALTER TABLE site_snapshots ADD COLUMN visual_diff_percent FLOAT")
                if "visual_change_detected" not in existing_snap_cols:
                    conn.exec_driver_sql("ALTER TABLE site_snapshots ADD COLUMN visual_change_detected BOOLEAN")
                if "screenshot_error" not in existing_snap_cols:
                    conn.exec_driver_sql("ALTER TABLE site_snapshots ADD COLUMN screenshot_error VARCHAR(512)")

                # Check notifications columns
                existing_notif_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(notifications)").fetchall()}
                if "user_id" not in existing_notif_cols:
                    conn.exec_driver_sql("ALTER TABLE notifications ADD COLUMN user_id INTEGER REFERENCES users(id)")

                # Check notification_preferences columns
                existing_pref_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(notification_preferences)").fetchall()}
                if "user_id" not in existing_pref_cols:
                    conn.exec_driver_sql("ALTER TABLE notification_preferences ADD COLUMN user_id INTEGER REFERENCES users(id)")

                # Backward compatibility: associate any legacy unowned records with an initial user
                orphaned_sites = conn.exec_driver_sql("SELECT COUNT(*) FROM monitored_sites WHERE user_id IS NULL").fetchone()[0]
                if orphaned_sites > 0:
                    user_row = conn.exec_driver_sql("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()
                    if not user_row:
                        from backend.auth import hash_password
                        hashed_pw = hash_password("ChangeScope@123")
                        conn.exec_driver_sql(
                            "INSERT INTO users (email, hashed_password, full_name, is_active, is_admin, auto_checks_enabled) "
                            "VALUES (?, ?, ?, 1, 1, 1)",
                            ("admin@changescope.local", hashed_pw, "Administrator"),
                        )
                        user_row = conn.exec_driver_sql("SELECT id FROM users ORDER BY id ASC LIMIT 1").fetchone()

                    if user_row:
                        default_user_id = user_row[0]
                        conn.exec_driver_sql("UPDATE monitored_sites SET user_id = ? WHERE user_id IS NULL", (default_user_id,))
                        conn.exec_driver_sql("UPDATE notifications SET user_id = ? WHERE user_id IS NULL", (default_user_id,))
                        conn.exec_driver_sql("UPDATE notification_preferences SET user_id = ? WHERE user_id IS NULL", (default_user_id,))
            except Exception:
                # If table doesn't exist yet, create_all already set it up
                pass
