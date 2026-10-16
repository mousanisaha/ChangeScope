"""Visual change detection and screenshot capture engine for ChangeScope.

Leverages Playwright for headless browser automation with SSRF safeguards
and Pillow for pixel-level visual difference analysis and threshold classification.
"""

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Optional, Tuple
import uuid

from PIL import Image, ImageChops, ImageEnhance
from sqlalchemy.orm import Session

from backend import models
from backend.monitoring import validate_target_url

# Dedicated screenshots storage directory
SCREENSHOTS_DIR = (Path(__file__).resolve().parent.parent / "data" / "screenshots").resolve()
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

# Standard browser viewport and capture timeouts
DEFAULT_VIEWPORT_WIDTH = 1280
DEFAULT_VIEWPORT_HEIGHT = 800
DEFAULT_CAPTURE_TIMEOUT_MS = 15000  # 15 seconds


def utc_now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def get_screenshot_url(relative_path: Optional[str]) -> Optional[str]:
    """Convert a stored relative screenshot path to a static API URL."""
    if not relative_path:
        return None
    normalized = relative_path.replace("\\", "/").lstrip("/")
    return f"/screenshots/{normalized}"


def resolve_screenshot_path(relative_path: Optional[str]) -> Optional[Path]:
    """Resolve a relative screenshot path to an absolute Path on disk."""
    if not relative_path:
        return None
    normalized = relative_path.replace("\\", "/").lstrip("/")
    full_path = SCREENSHOTS_DIR / normalized
    return full_path if full_path.exists() else None


def capture_page_screenshot(
    url: str,
    output_path: Path,
    timeout_ms: int = DEFAULT_CAPTURE_TIMEOUT_MS,
    viewport_width: int = DEFAULT_VIEWPORT_WIDTH,
    viewport_height: int = DEFAULT_VIEWPORT_HEIGHT,
) -> Tuple[bool, dict]:
    """Safely capture a full or viewport screenshot of a webpage using Playwright.

    Security & SSRF Protections:
    1. Pre-navigation validation of the target URL against SSRF rules.
    2. Request interception on every HTTP request and redirect to block
       localhost, private IPs, and cloud metadata access.
    3. Post-navigation verification of final page URL.
    """
    # 1. Pre-navigation SSRF check
    is_safe, error_reason = validate_target_url(url)
    if not is_safe:
        return False, {"error": f"Security validation failed: {error_reason}"}

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            # Launch headless chromium with isolated sandbox
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
            )
            context = browser.new_context(
                viewport={"width": viewport_width, "height": viewport_height},
                user_agent="ChangeScope/0.1.0 (+Intelligent Website Visual Detector; contact: admin@changescope.local)",
                ignore_https_errors=False,
            )
            page = context.new_page()
            page.set_default_navigation_timeout(timeout_ms)

            # 2. SSRF Route Interception (blocks redirects & subrequests to internal/private targets)
            def intercept_route(route):
                req_url = route.request.url
                if req_url.startswith("data:") or req_url.startswith("about:"):
                    route.continue_()
                    return

                req_safe, reason = validate_target_url(req_url)
                if not req_safe:
                    route.abort("blockedbyclient")
                    return
                route.continue_()

            page.route("**/*", intercept_route)

            # Navigate to target
            response = page.goto(url, wait_until="load", timeout=timeout_ms)

            # 3. Post-navigation verification of destination URL
            final_url = page.url
            final_safe, final_reason = validate_target_url(final_url)
            if not final_safe:
                browser.close()
                return False, {"error": f"Navigation redirected to prohibited destination: {final_reason}"}

            # Capture viewport screenshot (standardized resolution and reasonable file size)
            page.screenshot(path=str(output_path), full_page=False)
            browser.close()

        # Verify output file using Pillow
        if not output_path.exists() or output_path.stat().st_size == 0:
            return False, {"error": "Screenshot file was not generated"}

        with Image.open(output_path) as img:
            width, height = img.size

        size_bytes = output_path.stat().st_size
        return True, {
            "width": width,
            "height": height,
            "size_bytes": size_bytes,
            "path": str(output_path),
        }

    except Exception as exc:
        # Clean up partial file on failure
        if output_path.exists():
            try:
                output_path.unlink()
            except OSError:
                pass
        return False, {"error": str(exc)}


def compare_images(
    path_a: Path,
    path_b: Path,
    threshold: float = 1.0,
    diff_output_path: Optional[Path] = None,
) -> Tuple[float, bool, Optional[str]]:
    """Compare two screenshot images using Pillow to calculate a visual difference percentage.

    Returns:
        (diff_percent, visual_change_detected, diff_image_rel_path)
    """
    if not path_a.exists() or not path_b.exists():
        return 0.0, False, None

    with Image.open(path_a) as img_a_raw, Image.open(path_b) as img_b_raw:
        img_a = img_a_raw.convert("RGB")
        img_b = img_b_raw.convert("RGB")

    # Standardize dimensions if they differ
    if img_a.size != img_b.size:
        img_b = img_b.resize(img_a.size, Image.Resampling.BILINEAR)

    # Compute pixel-by-pixel difference
    diff = ImageChops.difference(img_a, img_b)

    # Convert difference to grayscale and threshold noise (ignore subtle rendering anti-aliasing)
    diff_gray = diff.convert("L")
    mask = diff_gray.point(lambda p: 255 if p > 12 else 0)

    # Count differing pixels
    hist = mask.histogram()
    diff_pixels = hist[255] if len(hist) > 255 else 0
    total_pixels = img_a.width * img_a.height

    if total_pixels == 0:
        diff_percent = 0.0
    else:
        diff_percent = round((diff_pixels / total_pixels) * 100.0, 2)

    visual_change_detected = (diff_percent >= threshold)

    diff_rel_path = None
    # Generate diff visual highlight image if requested and changes are detected
    if diff_output_path and diff_pixels > 0:
        try:
            diff_output_path.parent.mkdir(parents=True, exist_ok=True)
            # Desaturate base image and overlay differing pixels in vibrant crimson
            faded_base = ImageEnhance.Color(img_b).enhance(0.25)
            highlight_color = Image.new("RGB", img_a.size, (235, 35, 75))
            diff_image = Image.composite(highlight_color, faded_base, mask)
            diff_image.save(str(diff_output_path), "PNG")
            try:
                diff_rel_path = str(diff_output_path.relative_to(SCREENSHOTS_DIR)).replace("\\", "/")
            except ValueError:
                diff_rel_path = str(diff_output_path).replace("\\", "/")
        except Exception:
            pass

    return diff_percent, visual_change_detected, diff_rel_path


def capture_and_process_visual_snapshot(
    site: models.MonitoredSite,
    snapshot: Optional[models.SiteSnapshot],
    db: Session,
) -> dict:
    """Capture a screenshot for a monitored site, compare it against the previous
    successful baseline screenshot, and update database records.
    """
    check_time = utc_now()
    site_dir = SCREENSHOTS_DIR / f"site_{site.id}"
    site_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = check_time.strftime("%Y%m%d_%H%M%S")
    filename = f"snap_{site.id}_{timestamp_str}_{uuid.uuid4().hex[:6]}.png"
    target_path = site_dir / filename
    rel_path = f"site_{site.id}/{filename}"

    # Capture the screenshot
    success, result = capture_page_screenshot(site.url, target_path)

    if not success:
        error_msg = result.get("error", "Unknown screenshot capture error")
        if snapshot:
            snapshot.screenshot_error = error_msg
            db.commit()

        return {
            "site_id": site.id,
            "status": "screenshot_failed",
            "message": f"Visual capture failed: {error_msg}",
            "snapshot_id": snapshot.id if snapshot else None,
            "screenshot_path": None,
            "screenshot_url": None,
            "diff_percent": None,
            "visual_change_detected": False,
            "is_baseline": False,
            "timestamp": check_time,
            "error": error_msg,
        }

    # Successfully captured screenshot
    width = result.get("width")
    height = result.get("height")
    size_bytes = result.get("size_bytes")

    # Locate latest previous snapshot with a valid screenshot for this monitor
    prev_query = (
        db.query(models.SiteSnapshot)
        .filter(
            models.SiteSnapshot.site_id == site.id,
            models.SiteSnapshot.screenshot_path.isnot(None),
        )
    )
    if snapshot and snapshot.id:
        prev_query = prev_query.filter(models.SiteSnapshot.id != snapshot.id)

    prev_snapshot = prev_query.order_by(models.SiteSnapshot.created_at.desc(), models.SiteSnapshot.id.desc()).first()

    # Case A: First successful screenshot -> Baseline
    if not prev_snapshot or not prev_snapshot.screenshot_path:
        if snapshot:
            snapshot.screenshot_path = rel_path
            snapshot.screenshot_width = width
            snapshot.screenshot_height = height
            snapshot.screenshot_size_bytes = size_bytes
            snapshot.visual_diff_percent = 0.0
            snapshot.visual_change_detected = False
            snapshot.screenshot_error = None
        else:
            snapshot = models.SiteSnapshot(
                site_id=site.id,
                status_code=site.last_status_code or 200,
                response_time_ms=site.last_response_time_ms,
                content_hash="visual_baseline",
                text_content=None,
                screenshot_path=rel_path,
                screenshot_width=width,
                screenshot_height=height,
                screenshot_size_bytes=size_bytes,
                visual_diff_percent=0.0,
                visual_change_detected=False,
                screenshot_error=None,
                created_at=check_time,
            )
            db.add(snapshot)

        db.commit()

        return {
            "site_id": site.id,
            "status": "baseline_created",
            "message": "Initial visual baseline screenshot captured successfully.",
            "snapshot_id": snapshot.id,
            "screenshot_path": rel_path,
            "screenshot_url": get_screenshot_url(rel_path),
            "diff_percent": 0.0,
            "visual_change_detected": False,
            "is_baseline": True,
            "timestamp": check_time,
            "error": None,
        }

    # Case B: Subsequent screenshot -> Compare with previous baseline
    prev_full_path = SCREENSHOTS_DIR / prev_snapshot.screenshot_path.replace("\\", "/").lstrip("/")
    diff_filename = f"diff_{site.id}_{timestamp_str}_{uuid.uuid4().hex[:6]}.png"
    diff_output_path = site_dir / diff_filename

    threshold = site.visual_threshold if site.visual_threshold is not None else 1.0
    diff_percent, visual_change_detected, diff_rel_path = compare_images(
        prev_full_path, target_path, threshold=threshold, diff_output_path=diff_output_path
    )

    if snapshot:
        snapshot.screenshot_path = rel_path
        snapshot.screenshot_width = width
        snapshot.screenshot_height = height
        snapshot.screenshot_size_bytes = size_bytes
        snapshot.visual_diff_percent = diff_percent
        snapshot.visual_change_detected = visual_change_detected
        snapshot.screenshot_error = None
    else:
        snapshot = models.SiteSnapshot(
            site_id=site.id,
            status_code=site.last_status_code or 200,
            response_time_ms=site.last_response_time_ms,
            content_hash="visual_check",
            text_content=None,
            screenshot_path=rel_path,
            screenshot_width=width,
            screenshot_height=height,
            screenshot_size_bytes=size_bytes,
            visual_diff_percent=diff_percent,
            visual_change_detected=visual_change_detected,
            screenshot_error=None,
            created_at=check_time,
        )
        db.add(snapshot)

    # Record DetectedChange event if visual difference exceeds threshold
    if visual_change_detected:
        change_summary = f"Visual appearance modified ({diff_percent}% difference)"
        change_record = models.DetectedChange(
            site_id=site.id,
            change_type="visual",
            summary=change_summary,
            details=f"Visual difference of {diff_percent}% exceeded the configured threshold of {threshold}%.",
            previous_content=prev_snapshot.screenshot_path,
            new_content=rel_path,
            created_at=check_time,
        )
        db.add(change_record)

    db.commit()

    if visual_change_detected:
        from backend import notifications
        notifications.create_notification(
            db=db,
            site_id=site.id,
            event_type="visual_change",
            title=f"Visual Change: {site.name}",
            message=f"Visual change detected on {site.name}: {diff_percent}% difference (exceeded {threshold}% threshold).",
            link_type="visual",
            link_id=snapshot.id,
            dedup_key=f"visual_change:{site.id}:{snapshot.id}",
        )

    status_str = "visual_change_detected" if visual_change_detected else "unchanged"
    message_str = (
        f"Visual change detected ({diff_percent}% pixel difference)."
        if visual_change_detected
        else f"No visual modifications detected ({diff_percent}% difference, below {threshold}% threshold)."
    )

    return {
        "site_id": site.id,
        "status": status_str,
        "message": message_str,
        "snapshot_id": snapshot.id,
        "screenshot_path": rel_path,
        "screenshot_url": get_screenshot_url(rel_path),
        "diff_percent": diff_percent,
        "visual_change_detected": visual_change_detected,
        "is_baseline": False,
        "timestamp": check_time,
        "error": None,
    }
