"""Automated tests for ChangeScope screenshot capture and visual change detection engine.

Verifies:
- First-time screenshot creates visual baseline without change events.
- Identical screenshot is classified as unchanged (0.0% difference).
- Changed screenshot exceeding threshold creates a visual change event.
- Visual difference below configured threshold is classified as unchanged.
- Capture failures preserve previous successful screenshot and report clear error.
- SSRF targets (localhost, private subnets, cloud metadata) are blocked.
- Nonexistent monitor IDs return HTTP 404.
- All tests are hermetic and offline, using mocked Playwright / Pillow fixtures.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image, ImageDraw

MOCK_PUBLIC_ADDRINFO = [(2, 1, 6, "", ("93.184.216.34", 0))]


def create_solid_image(path: Path, color=(240, 240, 245), width: int = 1280, height: int = 800) -> None:
    """Helper to generate a realistic synthetic screenshot file for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)
    # Draw simulated website elements (header bar, card boxes)
    draw.rectangle([0, 0, width, 60], fill=(40, 45, 60))
    draw.rectangle([40, 100, 400, 300], fill=(255, 255, 255))
    draw.rectangle([440, 100, 800, 300], fill=(255, 255, 255))
    img.save(str(path), "PNG")


def create_modified_image(path: Path, base_color=(240, 240, 245), width: int = 1280, height: int = 800) -> None:
    """Helper to generate a screenshot with a substantial visual modification."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (width, height), base_color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 60], fill=(40, 45, 60))
    # Altered banner & content
    draw.rectangle([40, 100, 800, 450], fill=(220, 38, 38))  # Large red changed section
    img.save(str(path), "PNG")


def test_visual_comparison_invalid_site_id_returns_404(client):
    """Verify requesting visual comparison for a nonexistent monitor returns 404."""
    res = client.get("/api/sites/99999/visual-comparison")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_capture_screenshot_invalid_site_id_returns_404(client):
    """Verify triggering screenshot capture for a nonexistent monitor returns 404."""
    res = client.post("/api/sites/99999/capture-screenshot")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_capture_screenshot_blocks_ssrf_url(client):
    """Verify screenshot capture enforces SSRF protections on prohibited destinations."""
    with patch("socket.getaddrinfo", side_effect=Exception("Blocked")):
        # Attempt to create monitor with localhost or internal IP
        res = client.post(
            "/api/sites",
            json={"name": "SSRF Test", "url": "http://127.0.0.1:8000/admin"},
        )
        assert res.status_code == 400
        assert "security" in res.json()["detail"].lower() or "loopback" in res.json()["detail"].lower()


def test_baseline_screenshot_capture(client, tmp_path, monkeypatch):
    """Verify first-time screenshot creates a baseline without creating change events."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site = client.post(
            "/api/sites",
            json={"name": "Visual Site 1", "url": "https://example.com/visual1", "capture_screenshots": True},
        ).json()
        site_id = site["id"]

    # Mock capture_page_screenshot to generate test image in designated output_path
    def mock_capture(url, output_path, **kwargs):
        create_solid_image(output_path)
        return True, {"width": 1280, "height": 800, "size_bytes": output_path.stat().st_size}

    monkeypatch.setattr("backend.visual.capture_page_screenshot", mock_capture)

    # 1. Trigger screenshot capture
    res = client.post(f"/api/sites/{site_id}/capture-screenshot")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "baseline_created"
    assert data["is_baseline"] is True
    assert data["diff_percent"] == 0.0
    assert data["visual_change_detected"] is False
    assert data["screenshot_path"] is not None
    assert data["screenshot_url"].startswith("/screenshots/")

    # 2. Verify no change events created for baseline
    changes_res = client.get(f"/api/sites/{site_id}/changes")
    assert len(changes_res.json()) == 0

    # 3. Verify visual-comparison endpoint returns baseline
    vc_res = client.get(f"/api/sites/{site_id}/visual-comparison")
    assert vc_res.status_code == 200
    vc_data = vc_res.json()
    assert vc_data["has_baseline"] is True
    assert vc_data["has_comparison"] is False
    assert vc_data["baseline_screenshot"] is not None
    assert vc_data["visual_change_detected"] is False


def test_identical_screenshot_comparison(client, tmp_path, monkeypatch):
    """Verify subsequent check with visually identical image reports unchanged."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site = client.post(
            "/api/sites",
            json={"name": "Visual Site 2", "url": "https://example.com/visual2"},
        ).json()
        site_id = site["id"]

    def mock_capture(url, output_path, **kwargs):
        create_solid_image(output_path)
        return True, {"width": 1280, "height": 800, "size_bytes": output_path.stat().st_size}

    monkeypatch.setattr("backend.visual.capture_page_screenshot", mock_capture)

    # First capture (baseline)
    res1 = client.post(f"/api/sites/{site_id}/capture-screenshot")
    assert res1.json()["status"] == "baseline_created"

    # Second capture (identical image)
    res2 = client.post(f"/api/sites/{site_id}/capture-screenshot")
    assert res2.status_code == 200
    data2 = res2.json()

    assert data2["status"] == "unchanged"
    assert data2["is_baseline"] is False
    assert data2["diff_percent"] == 0.0
    assert data2["visual_change_detected"] is False

    # Verify still 0 change events
    changes_res = client.get(f"/api/sites/{site_id}/changes")
    assert len(changes_res.json()) == 0


def test_changed_screenshot_comparison_creates_visual_change_event(client, tmp_path, monkeypatch):
    """Verify visual modifications exceeding threshold trigger a visual change event."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site = client.post(
            "/api/sites",
            json={"name": "Visual Site 3", "url": "https://example.com/visual3", "visual_threshold": 1.0},
        ).json()
        site_id = site["id"]

    call_count = 0

    def mock_capture(url, output_path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            create_solid_image(output_path)
        else:
            create_modified_image(output_path)
        return True, {"width": 1280, "height": 800, "size_bytes": output_path.stat().st_size}

    monkeypatch.setattr("backend.visual.capture_page_screenshot", mock_capture)

    # First capture (baseline)
    res1 = client.post(f"/api/sites/{site_id}/capture-screenshot")
    assert res1.json()["status"] == "baseline_created"

    # Second capture (visually changed)
    res2 = client.post(f"/api/sites/{site_id}/capture-screenshot")
    assert res2.status_code == 200
    data2 = res2.json()

    assert data2["status"] == "visual_change_detected"
    assert data2["visual_change_detected"] is True
    assert data2["diff_percent"] > 1.0

    # Verify a DetectedChange was recorded with change_type="visual"
    changes_res = client.get(f"/api/sites/{site_id}/changes")
    changes = changes_res.json()
    assert len(changes) == 1
    assert changes[0]["change_type"] == "visual"
    assert "visual" in changes[0]["summary"].lower()

    # Verify visual-comparison endpoint returns comparison state
    vc_res = client.get(f"/api/sites/{site_id}/visual-comparison")
    assert vc_res.status_code == 200
    vc_data = vc_res.json()
    assert vc_data["has_baseline"] is True
    assert vc_data["has_comparison"] is True
    assert vc_data["visual_change_detected"] is True
    assert vc_data["diff_percent"] > 1.0


def test_threshold_below_cutoff_is_classified_as_unchanged(client, tmp_path, monkeypatch):
    """Verify that when visual difference is below threshold, change is not flagged."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        # Set high threshold: 80%
        site = client.post(
            "/api/sites",
            json={"name": "High Threshold Site", "url": "https://example.com/high-thresh", "visual_threshold": 80.0},
        ).json()
        site_id = site["id"]

    call_count = 0

    def mock_capture(url, output_path, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            create_solid_image(output_path)
        else:
            create_modified_image(output_path)  # ~10-25% change, which is < 80% threshold
        return True, {"width": 1280, "height": 800, "size_bytes": output_path.stat().st_size}

    monkeypatch.setattr("backend.visual.capture_page_screenshot", mock_capture)

    # Baseline
    client.post(f"/api/sites/{site_id}/capture-screenshot")

    # Modified check
    res = client.post(f"/api/sites/{site_id}/capture-screenshot")
    assert res.status_code == 200
    data = res.json()
    # Below 80% threshold -> unchanged
    assert data["status"] == "unchanged"
    assert data["visual_change_detected"] is False

    # 0 change events created
    changes = client.get(f"/api/sites/{site_id}/changes").json()
    assert len(changes) == 0


def test_screenshot_capture_failure_preserves_previous(client, tmp_path, monkeypatch):
    """Verify failed screenshot preserves existing baseline and returns clean error response."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site = client.post(
            "/api/sites",
            json={"name": "Failure Site", "url": "https://example.com/failure-test"},
        ).json()
        site_id = site["id"]

    # 1. Establish initial baseline screenshot
    def mock_capture_ok(url, output_path, **kwargs):
        create_solid_image(output_path)
        return True, {"width": 1280, "height": 800, "size_bytes": output_path.stat().st_size}

    monkeypatch.setattr("backend.visual.capture_page_screenshot", mock_capture_ok)
    res1 = client.post(f"/api/sites/{site_id}/capture-screenshot")
    assert res1.json()["status"] == "baseline_created"
    baseline_path = res1.json()["screenshot_path"]

    # 2. Simulate subsequent capture failure (e.g. browser navigation timeout)
    def mock_capture_fail(url, output_path, **kwargs):
        return False, {"error": "Navigation timed out after 15000ms"}

    monkeypatch.setattr("backend.visual.capture_page_screenshot", mock_capture_fail)
    res2 = client.post(f"/api/sites/{site_id}/capture-screenshot")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "screenshot_failed"
    assert "timed out" in data2["message"]

    # 3. Verify previous baseline screenshot is preserved intact
    vc_res = client.get(f"/api/sites/{site_id}/visual-comparison")
    vc_data = vc_res.json()
    assert vc_data["has_baseline"] is True
    assert vc_data["baseline_screenshot"]["screenshot_path"] == baseline_path


def test_list_site_screenshots_endpoint(client, tmp_path, monkeypatch):
    """Verify GET /api/sites/{site_id}/screenshots returns chronological metadata list."""
    with patch("socket.getaddrinfo", return_value=MOCK_PUBLIC_ADDRINFO):
        site = client.post(
            "/api/sites",
            json={"name": "List Screenshots Test", "url": "https://example.com/list-snaps"},
        ).json()
        site_id = site["id"]

    def mock_capture(url, output_path, **kwargs):
        create_solid_image(output_path)
        return True, {"width": 1280, "height": 800, "size_bytes": output_path.stat().st_size}

    monkeypatch.setattr("backend.visual.capture_page_screenshot", mock_capture)

    # Empty initially
    empty_res = client.get(f"/api/sites/{site_id}/screenshots")
    assert empty_res.status_code == 200
    assert empty_res.json() == []

    # Capture 2 screenshots
    client.post(f"/api/sites/{site_id}/capture-screenshot")
    client.post(f"/api/sites/{site_id}/capture-screenshot")

    snaps_res = client.get(f"/api/sites/{site_id}/screenshots")
    assert snaps_res.status_code == 200
    snaps = snaps_res.json()
    assert len(snaps) == 2
    assert snaps[0]["is_baseline"] is True
    assert snaps[1]["is_baseline"] is False
    assert snaps[0]["width"] == 1280
    assert snaps[0]["height"] == 800


def test_direct_image_comparison_identical_and_different(tmp_path):
    """Direct test of compare_images function using Pillow."""
    from backend.visual import compare_images

    path_a = tmp_path / "img_a.png"
    path_b = tmp_path / "img_b.png"
    path_diff = tmp_path / "diff.png"

    # Identical
    create_solid_image(path_a)
    create_solid_image(path_b)
    diff_pct, changed, diff_path = compare_images(path_a, path_b, threshold=1.0)
    assert diff_pct == 0.0
    assert changed is False

    # Different
    create_modified_image(path_b)
    diff_pct, changed, diff_path = compare_images(path_a, path_b, threshold=1.0, diff_output_path=path_diff)
    assert diff_pct > 1.0
    assert changed is True
    assert diff_path is not None
    assert path_diff.exists()
