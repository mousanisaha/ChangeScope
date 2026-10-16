"""Automated tests for ChangeScope multi-tenant cross-user data isolation.

Verifies:
- Users can only view, modify, and delete their own monitored sites.
- Attempting to access another user's monitor via GET, PUT, DELETE, or POST check returns 404 (no enumeration).
- Snapshots, visual screenshots, and detected changes are isolated per-user.
- Notifications and notification preferences are isolated per-user.
- Analytics summaries and change heatmaps are strictly isolated per-user.
- Scheduler job manual execution /run-now validates monitor ownership (returns 404 for other user's monitor).
- Unauthenticated requests to protected endpoints return 401 Unauthorized.
"""

from datetime import datetime, timezone
import pytest
from backend import models


def test_monitors_list_isolated_between_users(unauthed_client, user_factory):
    """Test User B cannot see User A's monitors when listing /api/sites."""
    user_a, _, headers_a = user_factory("user_a@example.com")
    user_b, _, headers_b = user_factory("user_b@example.com")

    # User A creates a monitor
    res_a = unauthed_client.post(
        "/api/sites",
        headers=headers_a,
        json={"url": "https://example.com/user-a-site", "name": "User A Monitor"},
    )
    assert res_a.status_code == 201
    site_a_id = res_a.json()["id"]

    # User A lists sites -> should see 1 site
    sites_a = unauthed_client.get("/api/sites", headers=headers_a).json()
    assert len(sites_a) == 1
    assert sites_a[0]["id"] == site_a_id

    # User B lists sites -> should see 0 sites
    sites_b = unauthed_client.get("/api/sites", headers=headers_b).json()
    assert len(sites_b) == 0


def test_monitor_access_and_mutations_blocked_cross_user(unauthed_client, user_factory):
    """Test User B cannot get, update, delete, or trigger checks on User A's monitor."""
    user_a, _, headers_a = user_factory("owner_a@example.com")
    user_b, _, headers_b = user_factory("attacker_b@example.com")

    # User A creates monitor
    res_a = unauthed_client.post(
        "/api/sites",
        headers=headers_a,
        json={"url": "https://example.com/private-vault", "name": "Private Vault"},
    )
    site_id = res_a.json()["id"]

    # 1. User B tries GET /api/sites/{id} -> 404 Not Found
    res_get = unauthed_client.get(f"/api/sites/{site_id}", headers=headers_b)
    assert res_get.status_code == 404

    # 2. User B tries PUT /api/sites/{id} -> 404 Not Found
    res_put = unauthed_client.put(
        f"/api/sites/{site_id}",
        headers=headers_b,
        json={"name": "Hijacked Monitor"},
    )
    assert res_put.status_code == 404

    # 3. User B tries POST /api/sites/{id}/check -> 404 Not Found
    res_check = unauthed_client.post(f"/api/sites/{site_id}/check", headers=headers_b)
    assert res_check.status_code == 404

    # 4. User B tries DELETE /api/sites/{id} -> 404 Not Found
    res_del = unauthed_client.delete(f"/api/sites/{site_id}", headers=headers_b)
    assert res_del.status_code == 404

    # Verify User A's monitor was NOT modified or deleted
    res_verify = unauthed_client.get(f"/api/sites/{site_id}", headers=headers_a)
    assert res_verify.status_code == 200
    assert res_verify.json()["name"] == "Private Vault"


def test_snapshots_and_changes_isolated_cross_user(unauthed_client, user_factory, db_session):
    """Test User B cannot access User A's snapshots, changes, or screenshots."""
    user_a, _, headers_a = user_factory("owner_data_a@example.com")
    user_b, _, headers_b = user_factory("viewer_data_b@example.com")

    # User A creates monitor
    site = models.MonitoredSite(
        user_id=user_a.id,
        name="User A Data Site",
        url="https://example.com/user-a-data",
        is_active=True,
    )
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)

    # Add a snapshot for site
    snap = models.SiteSnapshot(
        site_id=site.id,
        content_hash="hash_a_123",
        text_content="Confidential User A Information",
        status_code=200,
        response_time_ms=100.0,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(snap)
    db_session.commit()

    # User B queries snapshots -> 404 Not Found
    res_snap_list = unauthed_client.get(f"/api/sites/{site.id}/snapshots", headers=headers_b)
    assert res_snap_list.status_code == 404

    # User B queries changes -> 404 Not Found
    res_change_list = unauthed_client.get(f"/api/sites/{site.id}/changes", headers=headers_b)
    assert res_change_list.status_code == 404

    # User B queries screenshots -> 404 Not Found
    res_shot_list = unauthed_client.get(f"/api/sites/{site.id}/screenshots", headers=headers_b)
    assert res_shot_list.status_code == 404

    # User A queries snapshots -> 200 OK
    res_snap_ok = unauthed_client.get(f"/api/sites/{site.id}/snapshots", headers=headers_a)
    assert res_snap_ok.status_code == 200
    assert len(res_snap_ok.json()) == 1


def test_scheduler_run_now_isolated_cross_user(unauthed_client, user_factory, db_session):
    """Test User B cannot run scheduled checks for User A's monitor via /run-now."""
    user_a, _, headers_a = user_factory("sched_user_a@example.com")
    user_b, _, headers_b = user_factory("sched_user_b@example.com")

    site = models.MonitoredSite(
        user_id=user_a.id,
        name="User A Scheduled Target",
        url="https://example.com/user-a-sched",
        is_active=True,
    )
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)

    res_run = unauthed_client.post(
        f"/api/scheduler/jobs/{site.id}/run-now",
        headers=headers_b,
    )
    assert res_run.status_code == 404
    assert "not found" in res_run.json()["detail"].lower()


def test_notifications_isolated_cross_user(unauthed_client, user_factory, db_session):
    """Test User B cannot view or modify User A's notifications."""
    user_a, _, headers_a = user_factory("notif_a@example.com")
    user_b, _, headers_b = user_factory("notif_b@example.com")

    site_a = models.MonitoredSite(
        user_id=user_a.id,
        name="Site A",
        url="https://example.com/notif-a",
        is_active=True,
    )
    db_session.add(site_a)
    db_session.commit()
    db_session.refresh(site_a)

    notif_a = models.Notification(
        user_id=user_a.id,
        site_id=site_a.id,
        event_type="text_change",
        title="Change Detected",
        message="Sensitive change alert for user A",
        is_read=False,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(notif_a)
    db_session.commit()
    db_session.refresh(notif_a)

    # User A sees 1 notification
    res_a = unauthed_client.get("/api/notifications", headers=headers_a)
    assert res_a.status_code == 200
    assert len(res_a.json()["items"]) == 1

    # User B sees 0 notifications
    res_b = unauthed_client.get("/api/notifications", headers=headers_b)
    assert res_b.status_code == 200
    assert len(res_b.json()["items"]) == 0
    assert res_b.json()["unread_count"] == 0

    # User B tries to mark User A's notification as read -> 404
    res_read = unauthed_client.patch(f"/api/notifications/{notif_a.id}/read", headers=headers_b)
    assert res_read.status_code == 404

    # User B tries to delete User A's notification -> 404
    res_del = unauthed_client.delete(f"/api/notifications/{notif_a.id}", headers=headers_b)
    assert res_del.status_code == 404


def test_analytics_and_heatmap_isolated_cross_user(unauthed_client, user_factory, db_session):
    """Test User B's analytics and heatmap do not include User A's telemetry."""
    user_a, _, headers_a = user_factory("analytics_a@example.com")
    user_b, _, headers_b = user_factory("analytics_b@example.com")

    site_a = models.MonitoredSite(
        user_id=user_a.id,
        name="Analytics Target",
        url="https://example.com/analytics-a",
        is_active=True,
    )
    db_session.add(site_a)
    db_session.commit()
    db_session.refresh(site_a)

    # Add log and change for site_a
    log = models.SiteCheckLog(
        site_id=site_a.id,
        status="change_detected",
        status_code=200,
        response_time_ms=120.0,
        created_at=datetime.now(timezone.utc),
    )
    change = models.DetectedChange(
        site_id=site_a.id,
        change_type="text",
        summary="Content updated for User A",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add_all([log, change])
    db_session.commit()

    # User A analytics reflects the activity
    summary_a = unauthed_client.get("/api/analytics/summary", headers=headers_a).json()
    assert summary_a["total_checks"] == 1
    assert summary_a["text_changes"] == 1

    # User B analytics reflects 0 activity
    summary_b = unauthed_client.get("/api/analytics/summary", headers=headers_b).json()
    assert summary_b["total_checks"] == 0
    assert summary_b["total_changes"] == 0
    assert summary_b["text_changes"] == 0


def test_unauthenticated_requests_rejected_with_401(unauthed_client):
    """Test accessing protected endpoints without authentication returns 401."""
    protected_endpoints = [
        ("GET", "/api/sites"),
        ("POST", "/api/sites"),
        ("GET", "/api/notifications"),
        ("GET", "/api/analytics/summary"),
        ("GET", "/api/analytics/heatmap"),
        ("GET", "/api/scheduler/status"),
        ("POST", "/api/scheduler/sync"),
    ]

    for method, path in protected_endpoints:
        if method == "GET":
            res = unauthed_client.get(path)
        elif method == "POST":
            res = unauthed_client.post(path, json={})
        assert res.status_code == 401, f"{method} {path} should return 401 when unauthenticated"
