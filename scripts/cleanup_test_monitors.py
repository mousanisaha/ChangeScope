"""Safe development-only cleanup script for ChangeScope.

Identifies and removes ONLY confirmed test fixture monitors created during
automated testing (from tests/test_notifications.py) without touching
user-created monitors or resetting the database.

Usage:
    # Dry-run inspection (shows what would be cleaned without modifying DB):
    python scripts/cleanup_test_monitors.py

    # Apply cleanup (deletes only confirmed test fixture records):
    python scripts/cleanup_test_monitors.py --apply
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

# Ensure project root is in python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import SessionLocal
from backend.models import (
    MonitoredSite,
    SiteSnapshot,
    SiteCheckLog,
    DetectedChange,
    Notification,
)

# Exact test fixture monitors created in tests/test_notifications.py
CONFIRMED_TEST_FIXTURES = {
    "Text Alert Target": "https://example.com/alerts-text",
    "Fail Test Target": "https://example.com/fail-test",
    "Visual Alert Target": "https://example.com/visual-alert",
    "Dedup Target": "https://example.com/dedup",
    "Fail Spam Target": "https://example.com/fail-spam",
    "Lifecycle Target": "https://example.com/lifecycle",
    "Mark All Target": "https://example.com/mark-all",
    "Delete Target": "https://example.com/delete-test",
    "Suppressed Target": "https://example.com/suppressed",
}


def find_test_monitors(db):
    """Find monitors matching confirmed test fixture names and URLs."""
    all_sites = db.query(MonitoredSite).all()
    test_monitors = []
    user_monitors = []

    for site in all_sites:
        if site.name in CONFIRMED_TEST_FIXTURES and site.url == CONFIRMED_TEST_FIXTURES[site.name]:
            test_monitors.append(site)
        else:
            user_monitors.append(site)

    return test_monitors, user_monitors


def main():
    parser = argparse.ArgumentParser(
        description="Safely identify and remove development test fixture monitors from ChangeScope database."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the cleanup and remove confirmed test records. Without this flag, runs in dry-run mode.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        test_monitors, user_monitors = find_test_monitors(db)

        print("\n=== ChangeScope Test Monitor Scanner ===")
        print(f"Total monitors in database: {len(test_monitors) + len(user_monitors)}")
        print(f"Confirmed test fixture monitors: {len(test_monitors)}")
        print(f"Preserved user monitors: {len(user_monitors)}")

        if user_monitors:
            print("\nPreserved User Monitors (will NOT be touched):")
            for u in user_monitors:
                print(f"  [ID {u.id}] '{u.name}' ({u.url}) - User ID: {u.user_id}")

        if not test_monitors:
            print("\nNo test fixture monitors found in the database. Nothing to clean.")
            return

        print("\nIdentified Test Fixture Monitors:")
        for t in test_monitors:
            snap_count = db.query(SiteSnapshot).filter(SiteSnapshot.site_id == t.id).count()
            log_count = db.query(SiteCheckLog).filter(SiteCheckLog.site_id == t.id).count()
            chg_count = db.query(DetectedChange).filter(DetectedChange.site_id == t.id).count()
            notif_count = db.query(Notification).filter(Notification.site_id == t.id).count()
            print(
                f"  - [ID {t.id}] '{t.name}' ({t.url})\n"
                f"      Snapshots: {snap_count}, Logs: {log_count}, Changes: {chg_count}, Notifications: {notif_count}"
            )

        if not args.apply:
            print("\n[DRY RUN COMPLETE] No records were modified.")
            print("To safely remove only these confirmed test monitors, run:")
            print("    python scripts/cleanup_test_monitors.py --apply\n")
            return

        # Perform targeted deletion
        print("\nApplying cleanup of confirmed test fixture monitors...")
        screenshot_base = PROJECT_ROOT / "data" / "screenshots"

        deleted_ids = []
        for t in test_monitors:
            deleted_ids.append(t.id)
            # Remove associated screenshots folder if present
            site_screenshot_dir = screenshot_base / f"site_{t.id}"
            if site_screenshot_dir.exists():
                try:
                    shutil.rmtree(site_screenshot_dir)
                    print(f"  Removed screenshot assets: {site_screenshot_dir}")
                except Exception as e:
                    print(f"  Warning: Could not remove {site_screenshot_dir}: {e}")

            # SQLAlchemy cascades automatically delete snapshots, logs, changes, notifications
            db.delete(t)

        db.commit()
        print(f"\nSuccessfully cleaned up {len(deleted_ids)} test monitors (IDs: {deleted_ids}).")
        print("All associated snapshots, logs, changes, and notifications were removed.")
        print("All user data and user-created monitors were preserved intact.\n")

    finally:
        db.close()


if __name__ == "__main__":
    main()
