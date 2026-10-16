"""Automated test suite for ChangeScope Time Machine & Version History.

Verifies:
- Chronological ordering of snapshots (asc vs desc).
- Timeline labels assignment (baseline, unchanged, change_detected).
- Retrieval of individual snapshots by ID.
- Handling of invalid snapshot IDs (HTTP 404).
- Comparison of two snapshots (unified diff, additions, deletions).
- Comparison of two identical snapshots (is_identical=True).
- Handling of invalid snapshot IDs in comparison endpoint (HTTP 404).
- Empty history behavior for monitors with zero snapshots.
"""

from unittest.mock import MagicMock, patch
import pytest

MOCK_ADDRINFO = [(2, 1, 6, "", ("93.184.216.34", 0))]


def test_empty_snapshot_history_returns_empty_list(client):
    """Verify that a newly created monitor with no checks returns an empty snapshot list."""
    with patch("socket.getaddrinfo", return_value=MOCK_ADDRINFO):
        res = client.post("/api/sites", json={"url": "https://example.com/fresh-site", "name": "Fresh Site"})
        assert res.status_code == 201
        site_id = res.json()["id"]

        snap_res = client.get(f"/api/sites/{site_id}/snapshots")
        assert snap_res.status_code == 200
        assert snap_res.json() == []


def test_snapshots_chronological_ordering_and_timeline_labels(client):
    """Verify chronological ('asc') and reverse ('desc') ordering and timeline labels."""
    with patch("socket.getaddrinfo", return_value=MOCK_ADDRINFO):
        res = client.post("/api/sites", json={"url": "https://example.com/timeline-site", "name": "Timeline Site"})
        site_id = res.json()["id"]

        # 1. First check -> Baseline
        mock1 = MagicMock(ok=True, status_code=200, text="<html><body><h1>Title 1</h1><p>Alpha</p></body></html>")
        with patch("requests.Session.get", return_value=mock1):
            c1 = client.post(f"/api/sites/{site_id}/check")
            assert c1.status_code == 200
            assert c1.json()["status"] == "baseline_created"

        # 2. Second check -> Unchanged
        with patch("requests.Session.get", return_value=mock1):
            c2 = client.post(f"/api/sites/{site_id}/check")
            assert c2.status_code == 200
            assert c2.json()["status"] == "unchanged"

        # 3. Third check -> Content Changed
        mock2 = MagicMock(ok=True, status_code=200, text="<html><body><h1>Title 1</h1><p>Beta Modified</p></body></html>")
        with patch("requests.Session.get", return_value=mock2):
            c3 = client.post(f"/api/sites/{site_id}/check")
            assert c3.status_code == 200
            assert c3.json()["status"] == "change_detected"

        # Fetch in chronological order (asc)
        asc_res = client.get(f"/api/sites/{site_id}/snapshots?order=asc")
        assert asc_res.status_code == 200
        snaps_asc = asc_res.json()
        assert len(snaps_asc) == 3

        # Check chronological order (oldest to newest)
        assert snaps_asc[0]["id"] < snaps_asc[1]["id"] < snaps_asc[2]["id"]

        # Verify timeline labels
        assert snaps_asc[0]["change_label"] == "baseline"
        assert snaps_asc[0]["has_change"] is False

        assert snaps_asc[1]["change_label"] == "unchanged"
        assert snaps_asc[1]["has_change"] is False

        assert snaps_asc[2]["change_label"] == "change_detected"
        assert snaps_asc[2]["has_change"] is True

        # Fetch in reverse chronological order (desc, default)
        desc_res = client.get(f"/api/sites/{site_id}/snapshots?order=desc")
        assert desc_res.status_code == 200
        snaps_desc = desc_res.json()
        assert len(snaps_desc) == 3
        assert snaps_desc[0]["id"] == snaps_asc[2]["id"]
        assert snaps_desc[2]["id"] == snaps_asc[0]["id"]


def test_get_single_snapshot_by_id(client):
    """Verify retrieving an individual snapshot by ID and its detailed fields."""
    with patch("socket.getaddrinfo", return_value=MOCK_ADDRINFO):
        site_res = client.post("/api/sites", json={"url": "https://example.com/snap-single", "name": "Snap Single"})
        site_id = site_res.json()["id"]

        mock_resp = MagicMock(ok=True, status_code=200, text="<html><body><h1>Product</h1><p>Price: $99</p></body></html>")
        with patch("requests.Session.get", return_value=mock_resp):
            check_res = client.post(f"/api/sites/{site_id}/check")
            snap_id = client.get(f"/api/sites/{site_id}/snapshots").json()[0]["id"]

        res = client.get(f"/api/snapshots/{snap_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == snap_id
        assert data["site_id"] == site_id
        assert data["status_code"] == 200
        assert "Price: $99" in data["text_content"]
        assert data["content_hash"] is not None
        assert data["change_label"] == "baseline"
        assert data["line_count"] >= 1
        assert data["char_count"] >= 5


def test_get_invalid_snapshot_id_returns_404(client):
    """Verify that requesting a nonexistent snapshot ID returns HTTP 404."""
    res = client.get("/api/snapshots/999999")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_compare_two_different_snapshots(client):
    """Verify comparing two snapshots with differences returns unified diff and stats."""
    with patch("socket.getaddrinfo", return_value=MOCK_ADDRINFO):
        site = client.post("/api/sites", json={"url": "https://example.com/compare-site", "name": "Compare Site"}).json()
        site_id = site["id"]

        # Version 1
        mock1 = MagicMock(ok=True, status_code=200, text="<html><body><p>Feature: Basic</p><p>Status: Draft</p></body></html>")
        with patch("requests.Session.get", return_value=mock1):
            client.post(f"/api/sites/{site_id}/check")

        # Version 2
        mock2 = MagicMock(ok=True, status_code=200, text="<html><body><p>Feature: Pro Edition</p><p>Status: Published</p><p>New Extra</p></body></html>")
        with patch("requests.Session.get", return_value=mock2):
            client.post(f"/api/sites/{site_id}/check")

        snaps = client.get(f"/api/sites/{site_id}/snapshots?order=asc").json()
        snap1_id = snaps[0]["id"]
        snap2_id = snaps[1]["id"]

        # Compare version 1 to version 2
        comp_res = client.get(f"/api/snapshots/compare?base_id={snap1_id}&target_id={snap2_id}")
        assert comp_res.status_code == 200
        comp_data = comp_res.json()

        assert comp_data["base_snapshot_id"] == snap1_id
        assert comp_data["target_snapshot_id"] == snap2_id
        assert comp_data["is_identical"] is False
        assert comp_data["added_lines_count"] > 0
        assert comp_data["removed_lines_count"] > 0
        assert "+Feature: Pro Edition" in comp_data["diff_text"]
        assert "-Feature: Basic" in comp_data["diff_text"]
        assert "Draft" in comp_data["base_text"]
        assert "Published" in comp_data["target_text"]


def test_compare_identical_snapshots(client):
    """Verify comparing two snapshots with identical content reports is_identical=True."""
    with patch("socket.getaddrinfo", return_value=MOCK_ADDRINFO):
        site = client.post("/api/sites", json={"url": "https://example.com/identical-site", "name": "Identical Site"}).json()
        site_id = site["id"]

        mock = MagicMock(ok=True, status_code=200, text="<html><body><p>Unchanged Page</p></body></html>")
        with patch("requests.Session.get", return_value=mock):
            client.post(f"/api/sites/{site_id}/check")
            client.post(f"/api/sites/{site_id}/check")

        snaps = client.get(f"/api/sites/{site_id}/snapshots?order=asc").json()
        snap1_id = snaps[0]["id"]
        snap2_id = snaps[1]["id"]

        comp_res = client.get(f"/api/snapshots/compare?base_id={snap1_id}&target_id={snap2_id}")
        assert comp_res.status_code == 200
        comp = comp_res.json()
        assert comp["is_identical"] is True
        assert comp["added_lines_count"] == 0
        assert comp["removed_lines_count"] == 0
        assert "Identical" in comp["summary"]


def test_compare_with_invalid_snapshot_ids_returns_404(client):
    """Verify comparing with invalid snapshot IDs returns HTTP 404."""
    # Invalid base_id
    res1 = client.get("/api/snapshots/compare?base_id=888888&target_id=1")
    assert res1.status_code == 404
    assert "888888" in res1.json()["detail"]

    # Invalid target_id
    with patch("socket.getaddrinfo", return_value=MOCK_ADDRINFO):
        site = client.post("/api/sites", json={"url": "https://example.com/valid-snap-site", "name": "Valid Snap Site"}).json()
        mock = MagicMock(ok=True, status_code=200, text="<p>Test</p>")
        with patch("requests.Session.get", return_value=mock):
            client.post(f"/api/sites/{site['id']}/check")
        snap_id = client.get(f"/api/sites/{site['id']}/snapshots").json()[0]["id"]

    res2 = client.get(f"/api/snapshots/compare?base_id={snap_id}&target_id=999999")
    assert res2.status_code == 404
    assert "999999" in res2.json()["detail"]
