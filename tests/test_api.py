"""Automated tests for ChangeScope REST API endpoints.

Covers full CRUD lifecycle for Monitored Sites, SSRF protection, duplicate detection,
and error handling. Uses isolated in-memory SQLite database and mocked DNS resolution.
"""

from unittest.mock import patch
from datetime import datetime
import pytest

# Safe mock public IP for hermetic testing (example.com -> 93.184.216.34)
MOCK_PUBLIC_ADDRINFO = [(2, 1, 6, "", ("93.184.216.34", 0))]


def test_health_endpoint(client):
    """Verify that GET /api/health returns 200 OK and valid health telemetry."""
    response = client.get("/api/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "ChangeScope"
    assert data["version"] == "0.1.0"
    assert data["database"] == "connected"

    # Verify that the timestamp is a valid ISO 8601 string
    parsed_time = datetime.fromisoformat(data["timestamp"])
    assert parsed_time is not None


def test_cors_headers_present(client):
    """Verify that CORS headers are configured for local frontend flexibility."""
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" in response.headers


def test_list_sites_initially_empty(client):
    """Verify that GET /api/sites returns an honest empty list when no sites are configured."""
    response = client.get("/api/sites")
    assert response.status_code == 200

    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


def test_create_monitor_success_with_explicit_name(client):
    """Verify creating a monitor with explicit URL and display name."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        payload = {
            "name": "Example Production",
            "url": "https://example.com/pricing",
            "check_interval_minutes": 30,
            "is_active": True,
        }
        response = client.post("/api/sites", json=payload)
        assert response.status_code == 201

        data = response.json()
        assert data["id"] is not None
        assert data["name"] == "Example Production"
        assert data["url"] == "https://example.com/pricing"
        assert data["check_interval_minutes"] == 30
        assert data["is_active"] is True
        assert data["last_status_code"] is None
        assert data["created_at"] is not None


def test_create_monitor_success_with_inferred_name(client):
    """Verify creating a monitor without a display name infers it from URL."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        payload = {
            "url": "https://example.com/blog",
            "check_interval_minutes": 60,
        }
        response = client.post("/api/sites", json=payload)
        assert response.status_code == 201

        data = response.json()
        assert data["name"] == "example.com/blog"
        assert data["url"] == "https://example.com/blog"
        assert data["is_active"] is True


def test_create_monitor_rejects_duplicate_url(client):
    """Verify that creating two monitors with the exact same URL returns 409 Conflict."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        payload = {
            "name": "Original Site",
            "url": "https://example.com/unique-page",
        }
        res1 = client.post("/api/sites", json=payload)
        assert res1.status_code == 201

        # Attempt to create duplicate
        res2 = client.post("/api/sites", json=payload)
        assert res2.status_code == 409
        assert "already exists" in res2.json()["detail"].lower()


@pytest.mark.parametrize(
    "prohibited_url",
    [
        "http://localhost:8000",
        "http://127.0.0.1:3000/api",
        "http://10.0.0.1/admin",
        "http://192.168.1.1/setup",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "ftp://ftp.example.com",
        "not-a-valid-url",
    ],
)
def test_create_monitor_ssrf_and_invalid_urls_rejected(client, prohibited_url):
    """Verify that SSRF targets and invalid schemes are blocked with 400 Bad Request."""
    payload = {
        "name": "Malicious or Invalid",
        "url": prohibited_url,
    }
    response = client.post("/api/sites", json=payload)
    assert response.status_code == 400
    assert "detail" in response.json()


def test_get_single_monitor(client):
    """Verify retrieving an individual monitor by its ID."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        create_res = client.post("/api/sites", json={"name": "Fetch Me", "url": "https://example.com/fetch"})
        assert create_res.status_code == 201
        site_id = create_res.json()["id"]

        get_res = client.get(f"/api/sites/{site_id}")
        assert get_res.status_code == 200
        assert get_res.json()["id"] == site_id
        assert get_res.json()["name"] == "Fetch Me"


def test_get_nonexistent_monitor_returns_404(client):
    """Verify querying an unknown monitor ID returns 404 Not Found."""
    response = client.get("/api/sites/999999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_update_monitor_success(client):
    """Verify updating monitor attributes (name, interval, is_active, URL)."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        # Create
        create_res = client.post(
            "/api/sites",
            json={"name": "Initial Name", "url": "https://example.com/initial", "check_interval_minutes": 60},
        )
        assert create_res.status_code == 201
        site_id = create_res.json()["id"]

        # Update name and interval
        update_res = client.put(
            f"/api/sites/{site_id}",
            json={"name": "Renamed Site", "check_interval_minutes": 15, "is_active": False},
        )
        assert update_res.status_code == 200
        updated = update_res.json()
        assert updated["name"] == "Renamed Site"
        assert updated["check_interval_minutes"] == 15
        assert updated["is_active"] is False
        assert updated["url"] == "https://example.com/initial"

        # Update URL
        update_url_res = client.put(
            f"/api/sites/{site_id}",
            json={"url": "https://example.com/updated-url"},
        )
        assert update_url_res.status_code == 200
        assert update_url_res.json()["url"] == "https://example.com/updated-url"


def test_update_monitor_rejects_ssrf_url(client):
    """Verify that updating a monitor's URL to a prohibited SSRF address is blocked."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        create_res = client.post("/api/sites", json={"name": "Good Site", "url": "https://example.com/good"})
        site_id = create_res.json()["id"]

        update_res = client.put(f"/api/sites/{site_id}", json={"url": "http://127.0.0.1:8000/admin"})
        assert update_res.status_code == 400
        assert "invalid or prohibited url" in update_res.json()["detail"].lower()


def test_update_monitor_rejects_duplicate_url(client):
    """Verify that updating a monitor's URL to one already used by another site returns 409."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site1 = client.post("/api/sites", json={"name": "Site One", "url": "https://example.com/site1"}).json()
        site2 = client.post("/api/sites", json={"name": "Site Two", "url": "https://example.com/site2"}).json()

        # Try updating site2 to site1's URL
        update_res = client.put(f"/api/sites/{site2['id']}", json={"url": "https://example.com/site1"})
        assert update_res.status_code == 409
        assert "already exists" in update_res.json()["detail"].lower()


def test_update_nonexistent_monitor_returns_404(client):
    """Verify updating a non-existent monitor returns 404."""
    response = client.put("/api/sites/888888", json={"name": "Phantom"})
    assert response.status_code == 404


def test_delete_monitor_success(client):
    """Verify deleting an existing monitor returns 204 and removes it."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        create_res = client.post("/api/sites", json={"name": "To Be Deleted", "url": "https://example.com/delete-me"})
        assert create_res.status_code == 201
        site_id = create_res.json()["id"]

        # Delete
        del_res = client.delete(f"/api/sites/{site_id}")
        assert del_res.status_code == 204

        # Verify 404 on get
        get_res = client.get(f"/api/sites/{site_id}")
        assert get_res.status_code == 404


def test_delete_nonexistent_monitor_returns_404(client):
    """Verify attempting to delete a non-existent monitor returns 404."""
    response = client.delete("/api/sites/777777")
    assert response.status_code == 404
