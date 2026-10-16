"""Hermetic unit and integration tests for Prompt 9: Automated Monitoring Scheduler.

Validates APScheduler lifecycle, job synchronization, overlapping check guards,
interval respect, pause/resume behavior, global setting toggles, and API endpoints.
All tests are 100% offline, deterministic, and mock external operations.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from backend import models, scheduler


def test_scheduler_status_initial_state(client):
    """Test GET /api/scheduler/status returns proper structure on fresh database."""
    res = client.get("/api/scheduler/status")
    assert res.status_code == 200
    data = res.json()

    assert data["is_running"] is True
    assert data["auto_checks_enabled"] is True
    assert data["total_monitors_count"] == 0
    assert data["active_monitors_count"] == 0
    assert data["paused_monitors_count"] == 0
    assert data["active_jobs_count"] == 0
    assert data["jobs"] == []
    assert data["recent_outcomes"] == []


def test_scheduler_start_stop_lifecycle_endpoints(client):
    """Test POST /api/scheduler/stop and POST /api/scheduler/start endpoints."""
    # Stop scheduler
    res_stop = client.post("/api/scheduler/stop")
    assert res_stop.status_code == 200
    assert res_stop.json()["is_running"] is False
    assert scheduler.is_scheduler_running() is False

    # Start scheduler
    res_start = client.post("/api/scheduler/start")
    assert res_start.status_code == 200
    assert res_start.json()["is_running"] is True
    assert scheduler.is_scheduler_running() is True


def test_scheduler_syncs_jobs_on_monitor_creation(client, db_session):
    """Test that creating an active monitor registers an APScheduler job, while a paused one does not."""
    # 1. Create active monitor with 30 min interval
    res_active = client.post(
        "/api/sites",
        json={
            "url": "https://example.com/scheduler-active",
            "name": "Active Target",
            "check_interval_minutes": 30,
            "is_active": True,
        },
    )
    assert res_active.status_code == 201
    active_id = res_active.json()["id"]

    # 2. Create paused monitor
    res_paused = client.post(
        "/api/sites",
        json={
            "url": "https://example.com/scheduler-paused",
            "name": "Paused Target",
            "check_interval_minutes": 60,
            "is_active": False,
        },
    )
    assert res_paused.status_code == 201
    paused_id = res_paused.json()["id"]

    # Check scheduler status
    res_status = client.get("/api/scheduler/status")
    assert res_status.status_code == 200
    status_data = res_status.json()

    assert status_data["total_monitors_count"] == 2
    assert status_data["active_monitors_count"] == 1
    assert status_data["paused_monitors_count"] == 1
    assert status_data["active_jobs_count"] == 1

    active_job = next(j for j in status_data["jobs"] if j["site_id"] == active_id)
    assert active_job["job_status"] == "scheduled"
    assert active_job["check_interval_minutes"] == 30
    assert active_job["next_run_time"] is not None

    paused_job = next(j for j in status_data["jobs"] if j["site_id"] == paused_id)
    assert paused_job["job_status"] == "paused"
    assert paused_job["next_run_time"] is None


def test_scheduler_updates_job_when_monitor_is_modified(client, db_session):
    """Test that updating interval or toggling active/paused status updates scheduler jobs."""
    # Create monitor
    res_create = client.post(
        "/api/sites",
        json={
            "url": "https://example.com/scheduler-modify",
            "name": "Modifiable Monitor",
            "check_interval_minutes": 15,
            "is_active": True,
        },
    )
    site_id = res_create.json()["id"]

    # Verify initial schedule
    inst = scheduler.get_scheduler_instance()
    job = inst.get_job(f"site_check_{site_id}")
    assert job is not None

    # 1. Pause monitor -> job should be removed
    res_pause = client.put(f"/api/sites/{site_id}", json={"is_active": False})
    assert res_pause.status_code == 200
    assert inst.get_job(f"site_check_{site_id}") is None

    # 2. Resume monitor with new interval of 45m -> job should be re-scheduled
    res_resume = client.put(
        f"/api/sites/{site_id}",
        json={"is_active": True, "check_interval_minutes": 45},
    )
    assert res_resume.status_code == 200
    job_re = inst.get_job(f"site_check_{site_id}")
    assert job_re is not None

    status_data = client.get("/api/scheduler/status").json()
    job_info = next(j for j in status_data["jobs"] if j["site_id"] == site_id)
    assert job_info["job_status"] == "scheduled"
    assert job_info["check_interval_minutes"] == 45


def test_scheduler_removes_job_on_monitor_deletion(client):
    """Test that deleting a monitor removes its scheduled job from APScheduler."""
    res_create = client.post(
        "/api/sites",
        json={
            "url": "https://example.com/scheduler-delete",
            "name": "To Delete",
            "is_active": True,
        },
    )
    site_id = res_create.json()["id"]

    inst = scheduler.get_scheduler_instance()
    assert inst.get_job(f"site_check_{site_id}") is not None

    # Delete monitor
    res_del = client.delete(f"/api/sites/{site_id}")
    assert res_del.status_code == 204

    # Verify job was removed
    assert inst.get_job(f"site_check_{site_id}") is None


def test_scheduler_global_auto_checks_toggle(client, db_session):
    """Test that toggling global auto_checks_enabled suspends and resumes active jobs."""
    # Create an active monitor
    res_create = client.post(
        "/api/sites",
        json={
            "url": "https://example.com/scheduler-global-toggle",
            "name": "Global Target",
            "is_active": True,
        },
    )
    site_id = res_create.json()["id"]

    # 1. Disable auto-checks globally
    res_settings_off = client.put(
        "/api/scheduler/settings",
        json={"auto_checks_enabled": False},
    )
    assert res_settings_off.status_code == 200
    assert res_settings_off.json()["auto_checks_enabled"] is False

    inst = scheduler.get_scheduler_instance()
    # All site check jobs should be removed/suspended
    assert inst.get_job(f"site_check_{site_id}") is None

    status_off = client.get("/api/scheduler/status").json()
    assert status_off["auto_checks_enabled"] is False
    assert status_off["active_jobs_count"] == 0
    job_info_off = next(j for j in status_off["jobs"] if j["site_id"] == site_id)
    assert job_info_off["job_status"] == "disabled_globally"

    # 2. Re-enable auto-checks globally
    res_settings_on = client.put(
        "/api/scheduler/settings",
        json={"auto_checks_enabled": True},
    )
    assert res_settings_on.status_code == 200
    assert res_settings_on.json()["auto_checks_enabled"] is True

    # Active monitor job should be restored
    assert inst.get_job(f"site_check_{site_id}") is not None
    status_on = client.get("/api/scheduler/status").json()
    assert status_on["active_jobs_count"] == 1


def test_scheduler_prevents_overlapping_checks(client, db_session):
    """Test that acquire_site_check_lock prevents concurrent checks for the exact same monitor."""
    site = models.MonitoredSite(
        name="Lock Test Site",
        url="https://example.com/lock-test",
        is_active=True,
    )
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)

    # Acquire lock manually
    assert scheduler.acquire_site_check_lock(site.id) is True

    # Subsequent attempt to acquire must fail
    assert scheduler.acquire_site_check_lock(site.id) is False
    assert scheduler.is_check_running(site.id) is True

    # Attempting to trigger check via API should report that check is already in progress
    res_check = client.post(f"/api/sites/{site.id}/check")
    assert res_check.status_code == 200
    assert res_check.json()["status"] == "check_failed"
    assert "already in progress" in res_check.json()["message"]

    # Release lock
    scheduler.release_site_check_lock(site.id)
    assert scheduler.is_check_running(site.id) is False

    # Now lock can be acquired again
    assert scheduler.acquire_site_check_lock(site.id) is True
    scheduler.release_site_check_lock(site.id)


def test_scheduler_run_scheduled_site_check_success(client, db_session):
    """Test run_scheduled_site_check executes successfully and updates last_checked_at."""
    site = models.MonitoredSite(
        name="Scheduled Exec Site",
        url="https://example.com/exec-test",
        is_active=True,
    )
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)

    mock_result = {
        "site_id": site.id,
        "status": "baseline_created",
        "message": "Baseline snapshot created.",
        "status_code": 200,
        "response_time_ms": 125.0,
        "content_hash": "a1b2c3d4e5f6",
        "change_id": None,
        "timestamp": datetime.now(timezone.utc),
    }

    with patch("backend.monitoring.perform_site_check", return_value=mock_result) as mock_perform:
        res = scheduler.run_scheduled_site_check(site.id, trigger_source="scheduler")
        assert res is not None
        assert res["status"] == "baseline_created"
        assert mock_perform.called

    # Lock must be released
    assert scheduler.is_check_running(site.id) is False


def test_scheduler_run_scheduled_site_check_handles_exceptions_safely(db_session):
    """Test that exceptions during scheduled check execution do not crash scheduler or retain lock."""
    site = models.MonitoredSite(
        name="Error Handling Site",
        url="https://example.com/error-handling",
        is_active=True,
    )
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)

    with patch("backend.monitoring.perform_site_check", side_effect=RuntimeError("Simulated unexpected crash")):
        res = scheduler.run_scheduled_site_check(site.id, trigger_source="scheduler")
        assert res is None

    # Lock must be properly cleared even on unhandled exception
    assert scheduler.is_check_running(site.id) is False


def test_scheduler_run_now_endpoint(client, db_session):
    """Test POST /api/scheduler/jobs/{site_id}/run-now executes check via scheduler pipeline."""
    res_create = client.post(
        "/api/sites",
        json={
            "url": "https://example.com/scheduler-run-now",
            "name": "Run Now Target",
            "is_active": True,
        },
    )
    site_id = res_create.json()["id"]

    mock_result = {
        "site_id": site_id,
        "status": "unchanged",
        "message": "Content unchanged.",
        "status_code": 200,
        "response_time_ms": 95.0,
        "content_hash": "hash123",
        "change_id": None,
        "timestamp": datetime.now(timezone.utc),
    }

    with patch("backend.monitoring.perform_site_check", return_value=mock_result):
        res_run = client.post(f"/api/scheduler/jobs/{site_id}/run-now")
        assert res_run.status_code == 200
        assert res_run.json()["status"] == "unchanged"


def test_scheduler_run_now_invalid_id_returns_404(client):
    """Test POST /api/scheduler/jobs/{site_id}/run-now returns 404 for nonexistent monitor."""
    res = client.post("/api/scheduler/jobs/999999/run-now")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_scheduler_sync_endpoint(client):
    """Test POST /api/scheduler/sync reconciles jobs with monitors in SQLite."""
    res = client.post("/api/scheduler/sync")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "synchronized" in data["message"].lower()


def test_scheduler_recent_outcomes_populated(client, db_session):
    """Test that recent check outcomes are reported in /api/scheduler/status."""
    site = models.MonitoredSite(
        name="Telemetry Site",
        url="https://example.com/telemetry-target",
        is_active=True,
    )
    db_session.add(site)
    db_session.commit()
    db_session.refresh(site)

    # Add a check log
    log = models.SiteCheckLog(
        site_id=site.id,
        status="change_detected",
        status_code=200,
        response_time_ms=110.0,
        error_message=None,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(log)
    db_session.commit()

    res_status = client.get("/api/scheduler/status")
    assert res_status.status_code == 200
    data = res_status.json()

    assert len(data["recent_outcomes"]) >= 1
    recent = data["recent_outcomes"][0]
    assert recent["site_id"] == site.id
    assert recent["status"] == "change_detected"
    assert recent["status_code"] == 200
    assert recent["site_name"] == "Telemetry Site"
