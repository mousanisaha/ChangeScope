"""Automated test suite for ChangeScope Change Heatmap & Monitoring Analytics.

Verifies:
- Analytics summary endpoint with empty database and populated data.
- Heatmap endpoint with empty database and populated data.
- Aggregation of total checks, text changes, visual changes, and failed checks.
- Date range filtering (days parameter).
- Individual monitor filtering (site_id parameter).
- Proper HTTP 404 for nonexistent monitor IDs.
- Parameter validation for days range (HTTP 422 for invalid values).
- Deterministic calculation of hourly and daily heatmap matrices.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest

from backend.database import get_db
from backend import models

MOCK_ADDRINFO = [(2, 1, 6, "", ("93.184.216.34", 0))]


def test_analytics_summary_empty_database(client):
    """Verify analytics summary returns safe, honest defaults on an empty database."""
    res = client.get("/api/analytics/summary")
    assert res.status_code == 200
    data = res.json()

    assert data["total_checks"] == 0
    assert data["total_changes"] == 0
    assert data["text_changes"] == 0
    assert data["visual_changes"] == 0
    assert data["failed_checks"] == 0
    assert data["change_rate_percent"] == 0.0
    assert data["avg_response_time_ms"] is None
    assert data["status_distribution"] == {}
    assert data["top_sites"] == []
    assert len(data["timeline"]) == 30


def test_analytics_heatmap_empty_database(client):
    """Verify heatmap returns safe 168-cell matrix and 0 counts on an empty database."""
    res = client.get("/api/analytics/heatmap")
    assert res.status_code == 200
    data = res.json()

    assert data["total_changes"] == 0
    assert len(data["hourly_matrix"]) == 168  # 7 days * 24 hours
    assert all(cell["count"] == 0 for cell in data["hourly_matrix"])
    assert data["peak_day"] is None
    assert data["peak_hour"] is None
    assert len(data["daily_matrix"]) == 30
    assert all(cell["count"] == 0 for cell in data["daily_matrix"])


def test_analytics_invalid_site_id_returns_404(client):
    """Verify requesting analytics or heatmap for nonexistent site ID returns 404."""
    summary_res = client.get("/api/analytics/summary?site_id=99999")
    assert summary_res.status_code == 404
    assert "99999" in summary_res.json()["detail"]

    heatmap_res = client.get("/api/analytics/heatmap?site_id=99999")
    assert heatmap_res.status_code == 404
    assert "99999" in heatmap_res.json()["detail"]


def test_analytics_invalid_days_validation(client):
    """Verify invalid days query parameter triggers FastAPI 422 validation error."""
    res1 = client.get("/api/analytics/summary?days=-5")
    assert res1.status_code == 422

    res2 = client.get("/api/analytics/heatmap?days=9999")
    assert res2.status_code == 422


def test_analytics_summary_with_real_activity(client):
    """Verify analytics correctly tallies baseline, unchanged, changes, and failures."""
    with patch("socket.getaddrinfo", return_value=MOCK_ADDRINFO):
        # Create 2 sites
        s1 = client.post("/api/sites", json={"name": "Site Alpha", "url": "https://example.com/alpha"}).json()
        s2 = client.post("/api/sites", json={"name": "Site Beta", "url": "https://example.com/beta"}).json()

        id1, id2 = s1["id"], s2["id"]

        # 1. Site 1: Baseline check (200 OK)
        m1 = MagicMock(ok=True, status_code=200, text="<html><body>Initial Content</body></html>")
        with patch("requests.Session.get", return_value=m1):
            client.post(f"/api/sites/{id1}/check")

        # 2. Site 1: Unchanged check (200 OK)
        with patch("requests.Session.get", return_value=m1):
            client.post(f"/api/sites/{id1}/check")

        # 3. Site 1: Text change check (200 OK)
        m2 = MagicMock(ok=True, status_code=200, text="<html><body>Updated Content Alpha</body></html>")
        with patch("requests.Session.get", return_value=m2):
            client.post(f"/api/sites/{id1}/check")

        # 4. Site 2: Baseline check (200 OK)
        m_beta = MagicMock(ok=True, status_code=200, text="<html><body>Beta Baseline</body></html>")
        with patch("requests.Session.get", return_value=m_beta):
            client.post(f"/api/sites/{id2}/check")

        # 5. Site 2: Failed check (500 Server Error)
        m_err = MagicMock(ok=False, status_code=500, text="Internal Server Error")
        with patch("requests.Session.get", return_value=m_err):
            client.post(f"/api/sites/{id2}/check")

    # Fetch summary for all monitors
    res = client.get("/api/analytics/summary?days=7")
    assert res.status_code == 200
    data = res.json()

    assert data["total_checks"] == 5
    assert data["total_changes"] == 1
    assert data["text_changes"] == 1
    assert data["visual_changes"] == 0
    assert data["failed_checks"] == 1
    assert data["change_rate_percent"] == 20.0  # 1 change / 5 checks = 20%
    assert data["status_distribution"].get("200") == 4
    assert data["status_distribution"].get("500") == 1
    assert data["avg_response_time_ms"] is not None
    assert len(data["top_sites"]) == 2

    # Site 1 should be top of leaderboard with 1 change
    assert data["top_sites"][0]["site_id"] == id1
    assert data["top_sites"][0]["total_changes"] == 1
    assert data["top_sites"][0]["total_checks"] == 3

    # Site 2 has 0 changes, 2 checks, 1 failure
    assert data["top_sites"][1]["site_id"] == id2
    assert data["top_sites"][1]["total_changes"] == 0
    assert data["top_sites"][1]["failed_checks"] == 1


def test_analytics_heatmap_deterministic_matrices(client):
    """Verify hourly and calendar heatmap cells accurately group changes by day and hour."""
    with patch("socket.getaddrinfo", return_value=MOCK_ADDRINFO):
        site = client.post("/api/sites", json={"name": "Heatmap Test Site", "url": "https://example.com/hm"}).json()
        site_id = site["id"]

    # Insert deterministic DetectedChange records directly into DB session
    from backend.main import app
    db_gen = app.dependency_overrides.get(get_db, get_db)()
    db = next(db_gen)

    try:
        # Create 3 changes on a deterministic date: 2026-04-15 (Wednesday), at 14:00 UTC (hour 14)
        target_dt = datetime(2026, 4, 15, 14, 30, 0, tzinfo=timezone.utc)
        target_dow = target_dt.weekday()  # 2 for Wednesday

        for i in range(3):
            c = models.DetectedChange(
                site_id=site_id,
                change_type="text" if i < 2 else "visual",
                summary=f"Synthetic Change {i}",
                created_at=target_dt,
            )
            db.add(c)

        # Create 1 change on Tuesday 09:00 UTC
        dt2 = datetime(2026, 4, 14, 9, 15, 0, tzinfo=timezone.utc)
        c2 = models.DetectedChange(
            site_id=site_id,
            change_type="text",
            summary="Tuesday Morning Change",
            created_at=dt2,
        )
        db.add(c2)
        db.commit()
    finally:
        db.close()

    # Query heatmap with days=0 (all time)
    res = client.get(f"/api/sites/{site_id}/analytics" if False else f"/api/analytics/heatmap?site_id={site_id}&days=0")
    assert res.status_code == 200
    data = res.json()

    assert data["total_changes"] == 4
    assert data["peak_day"] == "Wednesday"
    assert data["peak_hour"] == 14

    # Verify hourly matrix cell for Wednesday (2) at 14:00
    wed_14_cell = next(
        cell for cell in data["hourly_matrix"]
        if cell["day_of_week"] == 2 and cell["hour"] == 14
    )
    assert wed_14_cell["count"] == 3
    assert wed_14_cell["site_ids"] == [site_id]

    # Verify hourly matrix cell for Tuesday (1) at 09:00
    tue_9_cell = next(
        cell for cell in data["hourly_matrix"]
        if cell["day_of_week"] == 1 and cell["hour"] == 9
    )
    assert tue_9_cell["count"] == 1

    # Verify daily matrix has 2026-04-15 with count=3, intensity=2 (3-5 changes)
    day_15 = next((d for d in data["daily_matrix"] if d["date"] == "2026-04-15"), None)
    assert day_15 is not None
    assert day_15["count"] == 3
    assert day_15["text_changes"] == 2
    assert day_15["visual_changes"] == 1
    assert day_15["intensity"] == 2


def test_analytics_date_filter_cutoff(client):
    """Verify that date filter excludes events that occurred prior to cutoff."""
    with patch("socket.getaddrinfo", return_value=MOCK_ADDRINFO):
        site = client.post("/api/sites", json={"name": "Date Filter Site", "url": "https://example.com/cutoff"}).json()
        site_id = site["id"]

    from backend.main import app
    db_gen = app.dependency_overrides.get(get_db, get_db)()
    db = next(db_gen)

    now = datetime.now(timezone.utc)
    try:
        # Change 1: 45 days ago (outside 30-day window)
        c_old = models.DetectedChange(
            site_id=site_id,
            change_type="text",
            summary="Old change",
            created_at=now - timedelta(days=45),
        )
        db.add(c_old)

        # Change 2: 3 days ago (inside 7-day and 30-day windows)
        c_recent = models.DetectedChange(
            site_id=site_id,
            change_type="text",
            summary="Recent change",
            created_at=now - timedelta(days=3),
        )
        db.add(c_recent)
        db.commit()
    finally:
        db.close()

    # Query with days=7 -> Should see only 1 change for this site
    res7 = client.get(f"/api/analytics/summary?site_id={site_id}&days=7")
    assert res7.status_code == 200
    assert res7.json()["total_changes"] == 1

    # Query with days=30 -> Should see only 1 change for this site
    res30 = client.get(f"/api/analytics/summary?site_id={site_id}&days=30")
    assert res30.status_code == 200
    assert res30.json()["total_changes"] == 1

    # Query with days=60 -> Should see both (2 changes) for this site
    res60 = client.get(f"/api/analytics/summary?site_id={site_id}&days=60")
    assert res60.status_code == 200
    assert res60.json()["total_changes"] == 2

    # Query with days=0 (All Time) -> Should see both (2 changes) for this site
    res_all = client.get(f"/api/analytics/summary?site_id={site_id}&days=0")
    assert res_all.status_code == 200
    assert res_all.json()["total_changes"] == 2
