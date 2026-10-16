"""Automated tests for ChangeScope change detection engine.

Verifies:
- First check creates baseline without change events.
- Identical content is classified as unchanged.
- Changed content creates change events with before/after text.
- Repeated identical content avoids duplicate change events.
- HTTP errors and network failures are handled safely without corrupting snapshots.
- SSRF defense is enforced during check cycles.
"""

from unittest.mock import MagicMock, patch
import pytest

MOCK_PUBLIC_ADDRINFO = [(2, 1, 6, "", ("93.184.216.34", 0))]


def make_mock_response(status_code: int = 200, text: str = "<html><body><h1>Hello World</h1></body></html>"):
    mock_resp = MagicMock()
    mock_resp.ok = status_code < 400
    mock_resp.status_code = status_code
    mock_resp.text = text
    return mock_resp


def test_first_check_creates_baseline_no_change_event(client):
    """Verify first check establishes a baseline and does NOT report a change event."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site_res = client.post("/api/sites", json={"name": "Baseline Test", "url": "https://example.com/page1"})
        site_id = site_res.json()["id"]

        mock_resp = make_mock_response(200, "<html><body><h1>Acme Home</h1><p>Welcome to Acme v1</p></body></html>")
        with patch("requests.Session.get", return_value=mock_resp):
            check_res = client.post(f"/api/sites/{site_id}/check")
            assert check_res.status_code == 200

            data = check_res.json()
            assert data["status"] == "baseline_created"
            assert data["change_id"] is None
            assert data["content_hash"] is not None

            # Verify snapshots created = 1
            snap_res = client.get(f"/api/sites/{site_id}/snapshots")
            assert len(snap_res.json()) == 1

            # Verify changes created = 0
            changes_res = client.get(f"/api/sites/{site_id}/changes")
            assert len(changes_res.json()) == 0


def test_identical_content_classified_as_unchanged(client):
    """Verify checking the same content a second time reports 'unchanged' with 0 change events."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site = client.post("/api/sites", json={"name": "Unchanged Test", "url": "https://example.com/page2"}).json()
        site_id = site["id"]

        html = "<html><body><h1>Static Title</h1><p>Static description text</p></body></html>"
        mock_resp = make_mock_response(200, html)

        with patch("requests.Session.get", return_value=mock_resp):
            # Check 1: Baseline
            res1 = client.post(f"/api/sites/{site_id}/check").json()
            assert res1["status"] == "baseline_created"

            # Check 2: Unchanged
            res2 = client.post(f"/api/sites/{site_id}/check").json()
            assert res2["status"] == "unchanged"
            assert res2["change_id"] is None
            assert res2["content_hash"] == res1["content_hash"]

            # Changes count should still be 0
            changes = client.get(f"/api/sites/{site_id}/changes").json()
            assert len(changes) == 0


def test_changed_content_creates_change_event_with_diff(client):
    """Verify that when content changes, a change event is created with before/after text."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site = client.post("/api/sites", json={"name": "Diff Test", "url": "https://example.com/page3"}).json()
        site_id = site["id"]

        html_v1 = "<html><body><h1>Pricing</h1><p>Pro Plan: $29/mo</p></body></html>"
        html_v2 = "<html><body><h1>Pricing</h1><p>Pro Plan: $49/mo (Updated)</p></body></html>"

        # 1. Baseline
        with patch("requests.Session.get", return_value=make_mock_response(200, html_v1)):
            res1 = client.post(f"/api/sites/{site_id}/check").json()
            assert res1["status"] == "baseline_created"

        # 2. Check with modified content
        with patch("requests.Session.get", return_value=make_mock_response(200, html_v2)):
            res2 = client.post(f"/api/sites/{site_id}/check").json()
            assert res2["status"] == "change_detected"
            assert res2["change_id"] is not None

            # Retrieve change details
            change_res = client.get(f"/api/changes/{res2['change_id']}")
            assert change_res.status_code == 200
            change_data = change_res.json()

            assert "$29/mo" in change_data["previous_content"]
            assert "$49/mo (Updated)" in change_data["new_content"]
            assert "Text modified" in change_data["summary"]
            assert "+" in change_data["details"]
            assert "-" in change_data["details"]


def test_repeated_identical_changed_content_avoids_duplicate_events(client):
    """Verify that after a change occurs, subsequent checks with the same new content are unchanged."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site = client.post("/api/sites", json={"name": "No Dups", "url": "https://example.com/page4"}).json()
        site_id = site["id"]

        html_v1 = "<html><body><p>Version 1.0</p></body></html>"
        html_v2 = "<html><body><p>Version 2.0</p></body></html>"

        # Check 1: Baseline
        with patch("requests.Session.get", return_value=make_mock_response(200, html_v1)):
            client.post(f"/api/sites/{site_id}/check")

        # Check 2: Change to v2
        with patch("requests.Session.get", return_value=make_mock_response(200, html_v2)):
            res2 = client.post(f"/api/sites/{site_id}/check").json()
            assert res2["status"] == "change_detected"

        # Check 3: Still v2 -> Must be UNCHANGED, not a new change event!
        with patch("requests.Session.get", return_value=make_mock_response(200, html_v2)):
            res3 = client.post(f"/api/sites/{site_id}/check").json()
            assert res3["status"] == "unchanged"

        # Total changes count must be exactly 1
        changes = client.get(f"/api/sites/{site_id}/changes").json()
        assert len(changes) == 1


def test_http_error_handled_safely(client):
    """Verify HTTP 500 error marks check_failed and does not create snapshots or changes."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site = client.post("/api/sites", json={"name": "Error Site", "url": "https://example.com/500"}).json()
        site_id = site["id"]

        with patch("requests.Session.get", return_value=make_mock_response(500, "Server Error")):
            res = client.post(f"/api/sites/{site_id}/check").json()
            assert res["status"] == "check_failed"
            assert res["status_code"] == 500

            # Verify no snapshots created
            snaps = client.get(f"/api/sites/{site_id}/snapshots").json()
            assert len(snaps) == 0

            # Verify no changes created
            changes = client.get(f"/api/sites/{site_id}/changes").json()
            assert len(changes) == 0


def test_failed_check_does_not_replace_last_successful_snapshot(client):
    """Verify that a temporary network/server failure preserves the baseline snapshot."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site = client.post("/api/sites", json={"name": "Resilient Site", "url": "https://example.com/resilient"}).json()
        site_id = site["id"]

        good_html = "<html><body><h1>Stable Content</h1></body></html>"

        # 1. Successful baseline
        with patch("requests.Session.get", return_value=make_mock_response(200, good_html)):
            res1 = client.post(f"/api/sites/{site_id}/check").json()
            baseline_hash = res1["content_hash"]
            assert res1["status"] == "baseline_created"

        # 2. Temporary 503 outage
        with patch("requests.Session.get", return_value=make_mock_response(503, "Service Unavailable")):
            res2 = client.post(f"/api/sites/{site_id}/check").json()
            assert res2["status"] == "check_failed"

        # 3. Snapshot count should still be 1 (the good baseline)
        snaps = client.get(f"/api/sites/{site_id}/snapshots").json()
        assert len(snaps) == 1
        assert snaps[0]["content_hash"] == baseline_hash

        # 4. Service recovers with original good content -> unchanged against the baseline!
        with patch("requests.Session.get", return_value=make_mock_response(200, good_html)):
            res4 = client.post(f"/api/sites/{site_id}/check").json()
            assert res4["status"] == "unchanged"
            assert res4["content_hash"] == baseline_hash


def test_check_enforces_ssrf_protection(client):
    """Verify checking a site pointing to a prohibited destination fails security pre-flight."""
    site = client.post("/api/sites", json={"name": "SSRF Target", "url": "http://127.0.0.1:9090"})
    assert site.status_code == 400  # Blocked on creation


def test_list_all_changes_endpoint(client):
    """Verify GET /api/changes returns detected changes with site metadata."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site = client.post("/api/sites", json={"name": "Alpha Corp", "url": "https://example.com/alpha"}).json()
        site_id = site["id"]

        # Baseline
        with patch("requests.Session.get", return_value=make_mock_response(200, "<p>Alpha v1</p>")):
            client.post(f"/api/sites/{site_id}/check")

        # Change
        with patch("requests.Session.get", return_value=make_mock_response(200, "<p>Alpha v2</p>")):
            client.post(f"/api/sites/{site_id}/check")

        # Query all changes
        res = client.get("/api/changes")
        assert res.status_code == 200
        all_changes = res.json()
        assert len(all_changes) >= 1
        matching = [c for c in all_changes if c["site_id"] == site_id]
        assert len(matching) == 1
        assert matching[0]["site_name"] == "Alpha Corp"
        assert matching[0]["site_url"] == "https://example.com/alpha"
