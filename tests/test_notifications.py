"""Hermetic automated tests for ChangeScope Notification and Alert System (Prompt 8).

Verifies notification creation on text changes, visual changes, and failures,
deduplication logic, read/unread status updates, preferences suppression,
and error handling with zero external network dependencies.
"""

from unittest.mock import patch, MagicMock
import pytest

from backend import models


def test_empty_notifications_endpoint(client):
    """Verify empty notifications endpoint returns clean structure with zero counts."""
    res = client.get("/api/notifications")
    assert res.status_code == 200
    data = res.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["unread_count"] == 0

    count_res = client.get("/api/notifications/unread-count")
    assert count_res.status_code == 200
    assert count_res.json()["unread_count"] == 0


def test_notification_created_on_text_change(client):
    """Verify notification is created ONLY when a text change is detected, not on baseline or unchanged checks."""
    site_res = client.post("/api/sites", json={"url": "https://example.com/alerts-text", "name": "Text Alert Target"})
    assert site_res.status_code == 201
    site_id = site_res.json()["id"]

    # 1. Baseline Check -> NO notification
    with patch("backend.monitoring.requests.Session.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><h1>Initial Baseline Document</h1></body></html>"
        mock_get.return_value = mock_resp

        chk1 = client.post(f"/api/sites/{site_id}/check")
        assert chk1.status_code == 200
        assert chk1.json()["status"] == "baseline_created"

    notif_res = client.get("/api/notifications")
    assert notif_res.json()["total"] == 0

    # 2. Unchanged Check -> NO notification
    with patch("backend.monitoring.requests.Session.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><h1>Initial Baseline Document</h1></body></html>"
        mock_get.return_value = mock_resp

        chk2 = client.post(f"/api/sites/{site_id}/check")
        assert chk2.status_code == 200
        assert chk2.json()["status"] == "unchanged"

    notif_res = client.get("/api/notifications")
    assert notif_res.json()["total"] == 0

    # 3. Changed Check -> YES notification
    with patch("backend.monitoring.requests.Session.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><h1>Modified Content Document</h1><p>New line added.</p></body></html>"
        mock_get.return_value = mock_resp

        chk3 = client.post(f"/api/sites/{site_id}/check")
        assert chk3.status_code == 200
        assert chk3.json()["status"] == "change_detected"

    notif_res = client.get("/api/notifications")
    assert notif_res.status_code == 200
    data = notif_res.json()
    assert data["total"] == 1
    assert data["unread_count"] == 1

    item = data["items"][0]
    assert item["site_id"] == site_id
    assert item["event_type"] == "text_change"
    assert "Text Changed" in item["title"]
    assert item["link_type"] == "change"
    assert item["link_id"] is not None
    assert item["is_read"] is False


def test_notification_created_on_check_failure(client):
    """Verify notification is created when a website check encounters an HTTP error or failure."""
    site_res = client.post("/api/sites", json={"url": "https://example.com/fail-test", "name": "Fail Test Target"})
    site_id = site_res.json()["id"]

    with patch("backend.monitoring.requests.Session.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 502
        mock_resp.text = "Bad Gateway"
        mock_get.return_value = mock_resp

        chk = client.post(f"/api/sites/{site_id}/check")
        assert chk.status_code == 200
        assert chk.json()["status"] == "check_failed"

    notif_res = client.get("/api/notifications?event_type=check_failed")
    assert notif_res.status_code == 200
    data = notif_res.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["site_id"] == site_id
    assert item["event_type"] == "check_failed"
    assert "Check Failed" in item["title"]
    assert "HTTP 502" in item["message"]
    assert item["link_type"] == "monitor"
    assert item["link_id"] == site_id


def test_notification_created_on_visual_change(client):
    """Verify notification is created when Playwright/Pillow visual difference exceeds threshold."""
    site_res = client.post(
        "/api/sites",
        json={"url": "https://example.com/visual-alert", "name": "Visual Alert Target", "capture_screenshots": True, "visual_threshold": 2.0},
    )
    site_id = site_res.json()["id"]

    # First capture establishes baseline -> NO notification
    with patch("backend.visual.capture_page_screenshot") as mock_capture:
        mock_capture.return_value = (True, {"width": 1280, "height": 800, "size_bytes": 1024})
        cap1 = client.post(f"/api/sites/{site_id}/capture-screenshot")
        assert cap1.status_code == 200
        assert cap1.json()["is_baseline"] is True

    notifs1 = client.get("/api/notifications?event_type=visual_change")
    assert notifs1.json()["total"] == 0

    # Second capture exceeds threshold (5.5% > 2.0%) -> YES notification
    with patch("backend.visual.capture_page_screenshot") as mock_capture, \
         patch("backend.visual.compare_images") as mock_compare:
        mock_capture.return_value = (True, {"width": 1280, "height": 800, "size_bytes": 1024})
        mock_compare.return_value = (5.5, True, "diff_overlay.png")

        cap2 = client.post(f"/api/sites/{site_id}/capture-screenshot")
        assert cap2.status_code == 200
        assert cap2.json()["visual_change_detected"] is True

    notifs2 = client.get("/api/notifications?event_type=visual_change")
    assert notifs2.status_code == 200
    data = notifs2.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["site_id"] == site_id
    assert item["event_type"] == "visual_change"
    assert "Visual Change" in item["title"]
    assert "5.5%" in item["message"]
    assert item["link_type"] == "visual"


def test_notification_deduplication(client, db_session):
    """Verify duplicate notification dispatches with identical dedup_key are prevented."""
    from backend import notifications

    # Create site
    site = models.MonitoredSite(name="Dedup Target", url="https://example.com/dedup")
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)

    # First insert
    n1 = notifications.create_notification(
        db=db_session,
        site_id=site.id,
        event_type="text_change",
        title="Change 1",
        message="Modified content",
        dedup_key="unique_event_key_123",
    )
    assert n1 is not None

    # Duplicate insert with exact same key
    n2 = notifications.create_notification(
        db=db_session,
        site_id=site.id,
        event_type="text_change",
        title="Change 1",
        message="Modified content",
        dedup_key="unique_event_key_123",
    )
    assert n2 is not None
    assert n1.id == n2.id

    # Total rows in DB must be 1
    total = db_session.query(models.Notification).filter(models.Notification.site_id == site.id).count()
    assert total == 1


def test_consecutive_failure_deduplication(client):
    """Verify consecutive checks failing with the exact same error do not spam unread notifications."""
    site_res = client.post("/api/sites", json={"url": "https://example.com/fail-spam", "name": "Fail Spam Target"})
    site_id = site_res.json()["id"]

    with patch("backend.monitoring.requests.Session.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"
        mock_get.return_value = mock_resp

        # Check 1
        chk1 = client.post(f"/api/sites/{site_id}/check")
        assert chk1.status_code == 200

        # Check 2 (exact same error)
        chk2 = client.post(f"/api/sites/{site_id}/check")
        assert chk2.status_code == 200

    notif_res = client.get(f"/api/notifications?site_id={site_id}&event_type=check_failed")
    assert notif_res.status_code == 200
    # Should only create 1 notification, avoiding noisy spam
    assert notif_res.json()["total"] == 1


def test_mark_as_read_and_unread_lifecycle(client, db_session):
    """Test marking individual notification as read and unread."""
    from backend import notifications

    site = models.MonitoredSite(name="Lifecycle Target", url="https://example.com/lifecycle")
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)

    notif = notifications.create_notification(
        db=db_session,
        site_id=site.id,
        event_type="text_change",
        title="Test Alert",
        message="Alert details",
    )
    notif_id = notif.id

    # Initial state: unread
    count_res1 = client.get("/api/notifications/unread-count")
    assert count_res1.json()["unread_count"] == 1

    # Mark as read
    read_res = client.patch(f"/api/notifications/{notif_id}/read")
    assert read_res.status_code == 200
    assert read_res.json()["is_read"] is True

    count_res2 = client.get("/api/notifications/unread-count")
    assert count_res2.json()["unread_count"] == 0

    # Mark as unread
    unread_res = client.patch(f"/api/notifications/{notif_id}/unread")
    assert unread_res.status_code == 200
    assert unread_res.json()["is_read"] is False

    count_res3 = client.get("/api/notifications/unread-count")
    assert count_res3.json()["unread_count"] == 1


def test_mark_all_read(client, db_session):
    """Verify mark-all-read endpoint marks all unread alerts across sites."""
    from backend import notifications

    site = models.MonitoredSite(name="Mark All Target", url="https://example.com/mark-all")
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)

    for i in range(3):
        notifications.create_notification(
            db=db_session,
            site_id=site.id,
            event_type="text_change",
            title=f"Alert {i}",
            message=f"Details {i}",
        )

    assert client.get("/api/notifications/unread-count").json()["unread_count"] == 3

    mark_all_res = client.post("/api/notifications/mark-all-read")
    assert mark_all_res.status_code == 200
    assert mark_all_res.json()["marked_read"] == 3
    assert mark_all_res.json()["unread_count"] == 0

    # Verify unread list is now empty
    unread_list = client.get("/api/notifications?unread_only=true")
    assert unread_list.json()["total"] == 0


def test_delete_notification(client, db_session):
    """Verify deleting a notification."""
    from backend import notifications

    site = models.MonitoredSite(name="Delete Target", url="https://example.com/delete-test")
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)

    notif = notifications.create_notification(
        db=db_session,
        site_id=site.id,
        event_type="check_failed",
        title="Delete Alert",
        message="Delete me",
    )
    notif_id = notif.id

    del_res = client.delete(f"/api/notifications/{notif_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Subsequent delete returns 404
    del_res_404 = client.delete(f"/api/notifications/{notif_id}")
    assert del_res_404.status_code == 404


def test_invalid_notification_ids_return_404(client):
    """Verify 404 is returned when reading or deleting a nonexistent notification."""
    assert client.patch("/api/notifications/999999/read").status_code == 404
    assert client.patch("/api/notifications/999999/unread").status_code == 404
    assert client.delete("/api/notifications/999999").status_code == 404


def test_notification_preferences_suppression(client):
    """Verify disabling specific alert types in preferences suppresses notification creation."""
    # 1. Verify default preferences (all true)
    prefs_res = client.get("/api/notifications/preferences")
    assert prefs_res.status_code == 200
    prefs = prefs_res.json()
    assert prefs["notify_text_change"] is True
    assert prefs["notify_visual_change"] is True
    assert prefs["notify_check_failed"] is True

    # 2. Disable check_failed notifications
    update_res = client.put(
        "/api/notifications/preferences",
        json={"notify_check_failed": False, "notify_text_change": False, "notify_visual_change": False},
    )
    assert update_res.status_code == 200
    assert update_res.json()["notify_check_failed"] is False
    assert update_res.json()["notify_text_change"] is False
    assert update_res.json()["notify_visual_change"] is False

    site_res = client.post("/api/sites", json={"url": "https://example.com/suppressed", "name": "Suppressed Target"})
    site_id = site_res.json()["id"]

    # Trigger failure
    with patch("backend.monitoring.requests.Session.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_get.return_value = mock_resp

        client.post(f"/api/sites/{site_id}/check")

    # Verify no notification created
    notifs = client.get(f"/api/notifications?site_id={site_id}")
    assert notifs.json()["total"] == 0

    # 3. Re-enable preferences
    re_enable = client.put(
        "/api/notifications/preferences",
        json={"notify_check_failed": True, "notify_text_change": True, "notify_visual_change": True},
    )
    assert re_enable.status_code == 200
    assert re_enable.json()["notify_check_failed"] is True
