"""Website monitoring, content extraction, and change detection engine for ChangeScope.

Includes Server-Side Request Forgery (SSRF) validation, HTML text extraction,
diff analysis, and persistent snapshot state management.
"""

from datetime import datetime, timezone
import difflib
import hashlib
import ipaddress
import re
import socket
import time
from typing import Optional, Tuple
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from backend import models

USER_AGENT = "ChangeScope/0.1.0 (+Intelligent Website Change Detector; contact: admin@changescope.local)"


def utc_now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def validate_target_url(url: str) -> Tuple[bool, str]:
    """Validate a target URL to protect against SSRF and invalid protocols.

    Enforces:
    1. Scheme must be 'http' or 'https'.
    2. Hostname must be present.
    3. Hostname cannot be localhost or resolve to:
       - Loopback addresses (127.0.0.0/8, ::1)
       - Private addresses (RFC 1918: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
       - Link-local and cloud metadata addresses (169.254.0.0/16)
       - Multicast, broadcast, or reserved IP ranges

    Returns:
        (is_safe, reason): Tuple with boolean status and explanation if rejected.
    """
    if not url or not isinstance(url, str):
        return False, "URL must be a non-empty string"

    url = url.strip()

    try:
        parsed = urlparse(url)
    except Exception as exc:
        return False, f"Malformed URL: {exc}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Unsupported URL scheme '{parsed.scheme}'. Only HTTP and HTTPS are permitted."

    hostname = parsed.hostname
    if not hostname:
        return False, "Target URL missing valid hostname."

    hostname_lower = hostname.lower()

    # Reject obvious localhost / internal hostnames
    if hostname_lower in ("localhost", "localhost.localdomain", "broadcasthost"):
        return False, "Access to localhost or internal loopback is prohibited (SSRF protection)."

    # Reject cloud metadata hostnames directly
    if hostname_lower in ("metadata.google.internal", "instance-data", "metadata"):
        return False, "Access to cloud metadata endpoints is prohibited (SSRF protection)."

    # Check if hostname is directly an IP literal (IPv4/IPv6) to prevent SSRF immediately
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_loopback:
            return False, f"URL targets loopback IP ({hostname}), which is blocked for security."
        if ip.is_private:
            return False, f"URL targets private network IP ({hostname}), which is blocked for security."
        if ip.is_link_local:
            return False, f"URL targets link-local / cloud metadata IP ({hostname}), which is blocked for security."
        if ip.is_multicast:
            return False, f"URL targets multicast IP ({hostname}), which is blocked for security."
        if ip.is_reserved:
            return False, f"URL targets reserved IP ({hostname}), which is blocked for security."
        if ip.is_unspecified:
            return False, f"URL targets unspecified IP ({hostname}), which is blocked for security."
        return True, "URL is valid and safe"
    except ValueError:
        pass

    # Resolve IP addresses for the hostname to prevent DNS rebinding / internal resolution
    try:
        addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        return False, f"Could not resolve hostname '{hostname}': {exc}"

    resolved_ips = set()
    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        resolved_ips.add(ip_str)

    if not resolved_ips:
        return False, f"Hostname '{hostname}' did not resolve to any IP address."

    # Inspect each resolved IP address
    for ip_str in resolved_ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False, f"Invalid resolved IP address: {ip_str}"

        if ip.is_loopback:
            return False, f"URL resolves to loopback IP ({ip_str}), which is blocked for security."

        if ip.is_private:
            return False, f"URL resolves to private network IP ({ip_str}), which is blocked for security."

        if ip.is_link_local:
            return False, f"URL resolves to link-local / cloud metadata IP ({ip_str}), which is blocked for security."

        if ip.is_multicast:
            return False, f"URL resolves to multicast IP ({ip_str}), which is blocked for security."

        if ip.is_reserved:
            return False, f"URL resolves to reserved IP ({ip_str}), which is blocked for security."

        if ip.is_unspecified:
            return False, f"URL resolves to unspecified IP ({ip_str}), which is blocked for security."

    return True, "URL is valid and safe"


def compute_content_hash(content: str) -> str:
    """Compute deterministic SHA-256 hex digest for normalized string content."""
    normalized = content.strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def extract_clean_text(html: str) -> str:
    """Extract clean, normalized textual content from HTML by stripping non-content tags.

    Strips script, style, SVG, and metadata tags while normalizing line whitespace
    to prevent insignificant formatting fluctuations from triggering false positives.
    """
    if not html:
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # Decompose script, style, and metadata tags
    for tag in soup(["script", "style", "noscript", "svg", "meta", "link", "template"]):
        tag.decompose()

    # Extract text with space separators so inline tags (e.g. <strong>) flow naturally
    raw_text = soup.get_text(separator=" ")

    # Normalize multiple spaces and collapse lines
    cleaned = re.sub(r"[ \t]+", " ", raw_text)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    return "\n".join(lines)


def generate_diff_summary(old_text: str, new_text: str) -> Tuple[str, str]:
    """Generate concise change summary and unified diff string between snapshots."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile="Previous Baseline",
            tofile="Current Version",
            lineterm="",
        )
    )

    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

    if added == 0 and removed == 0:
        summary = "Text content slightly modified"
    else:
        parts = []
        if added > 0:
            parts.append(f"+{added} line{'s' if added != 1 else ''}")
        if removed > 0:
            parts.append(f"-{removed} line{'s' if removed != 1 else ''}")
        summary = f"Text modified ({', '.join(parts)})"

    diff_text = "\n".join(diff_lines)
    return summary, diff_text


def fetch_site_content(
    url: str,
    timeout: int = 15,
    session: Optional[requests.Session] = None,
) -> dict:
    """Safely fetch a webpage using Requests, enforcing SSRF validation and measuring latency.

    Returns a dict with:
        is_success: bool
        status_code: Optional[int]
        response_time_ms: Optional[float]
        html: Optional[str]
        error: Optional[str]
    """
    is_safe, error_reason = validate_target_url(url)
    if not is_safe:
        return {
            "is_success": False,
            "status_code": None,
            "response_time_ms": None,
            "html": None,
            "error": f"Security validation failed: {error_reason}",
        }

    client = session or requests.Session()
    headers = {"User-Agent": USER_AGENT}

    start_time = time.perf_counter()
    try:
        response = client.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

        return {
            "is_success": response.ok,
            "status_code": response.status_code,
            "response_time_ms": elapsed_ms,
            "html": response.text,
            "error": None if response.ok else f"HTTP {response.status_code}",
        }
    except requests.exceptions.RequestException as exc:
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "is_success": False,
            "status_code": None,
            "response_time_ms": elapsed_ms,
            "html": None,
            "error": str(exc),
        }


def perform_site_check(
    site: models.MonitoredSite,
    db: Session,
    session: Optional[requests.Session] = None,
    capture_screenshot: Optional[bool] = None,
) -> dict:
    """Execute a complete check cycle for a monitored website.

    Lifecycle:
    1. Verify target URL against SSRF rules.
    2. Fetch live webpage and measure response latency.
    3. If request fails (HTTP 4xx/5xx, timeout, network error):
       - Update monitor telemetry.
       - Do NOT overwrite existing baseline or create change events.
       - Return status="check_failed".
    4. If request succeeds:
       - Extract clean readable text and calculate deterministic SHA-256 hash.
       - If no prior snapshot exists:
         * Create initial baseline snapshot (status="baseline_created", no change event).
       - If prior snapshot matches content hash:
         * Record check without creating change event (status="unchanged").
       - If content hash differs from latest snapshot:
         * Generate concise summary and unified diff.
         * Save DetectedChange event with before/after text.
         * Save new snapshot with new hash (status="change_detected").
    5. Optionally capture a visual screenshot via Playwright if enabled for the monitor.
    """
    check_time = utc_now()

    # 1. SSRF Pre-flight
    is_safe, error_reason = validate_target_url(site.url)
    if not is_safe:
        site.last_checked_at = check_time
        check_log = models.SiteCheckLog(
            site_id=site.id,
            status="check_failed",
            status_code=None,
            response_time_ms=None,
            error_message=f"Security validation failed: {error_reason}",
            created_at=check_time,
        )
        db.add(check_log)
        db.commit()
        db.refresh(check_log)

        from backend import notifications
        notifications.create_notification(
            db=db,
            site_id=site.id,
            event_type="check_failed",
            title=f"Check Blocked: {site.name}",
            message=f"Monitoring check blocked for {site.name}: Security validation failed ({error_reason})",
            link_type="monitor",
            link_id=site.id,
            dedup_key=f"check_failed:{site.id}:{check_log.id}",
        )
        return {
            "site_id": site.id,
            "status": "check_failed",
            "message": f"Security validation failed: {error_reason}",
            "status_code": None,
            "response_time_ms": None,
            "content_hash": None,
            "change_id": None,
            "timestamp": check_time,
        }

    # 2. Network Fetch
    fetch_res = fetch_site_content(site.url, session=session)

    site.last_checked_at = check_time
    site.last_response_time_ms = fetch_res["response_time_ms"]
    site.last_status_code = fetch_res["status_code"]

    # 3. Handle HTTP / Connection Failures
    if not fetch_res["is_success"] or fetch_res["status_code"] is None or fetch_res["status_code"] >= 400:
        error_msg = fetch_res["error"] or f"HTTP {fetch_res['status_code']}"
        check_log = models.SiteCheckLog(
            site_id=site.id,
            status="check_failed",
            status_code=fetch_res["status_code"],
            response_time_ms=fetch_res["response_time_ms"],
            error_message=error_msg,
            created_at=check_time,
        )
        db.add(check_log)
        db.commit()
        db.refresh(check_log)

        from backend import notifications
        notifications.create_notification(
            db=db,
            site_id=site.id,
            event_type="check_failed",
            title=f"Check Failed: {site.name}",
            message=f"Monitoring check failed for {site.name} ({site.url}): {error_msg}",
            link_type="monitor",
            link_id=site.id,
            dedup_key=f"check_failed:{site.id}:{check_log.id}",
        )
        return {
            "site_id": site.id,
            "status": "check_failed",
            "message": f"Check failed: {error_msg}",
            "status_code": fetch_res["status_code"],
            "response_time_ms": fetch_res["response_time_ms"],
            "content_hash": None,
            "change_id": None,
            "timestamp": check_time,
        }

    # 4. Content Processing
    clean_text = extract_clean_text(fetch_res["html"])
    new_hash = compute_content_hash(clean_text)

    # Retrieve most recent snapshot for this site
    latest_snapshot = (
        db.query(models.SiteSnapshot)
        .filter(models.SiteSnapshot.site_id == site.id)
        .order_by(models.SiteSnapshot.created_at.desc())
        .first()
    )

    should_capture_visual = (
        capture_screenshot
        if capture_screenshot is not None
        else getattr(site, "capture_screenshots", False)
    )

    saved_snapshot: Optional[models.SiteSnapshot] = None
    ret_dict: dict = {}

    # 4A. Baseline Creation (First successful check)
    if not latest_snapshot:
        baseline_snapshot = models.SiteSnapshot(
            site_id=site.id,
            status_code=fetch_res["status_code"],
            response_time_ms=fetch_res["response_time_ms"],
            content_hash=new_hash,
            text_content=clean_text,
            created_at=check_time,
        )
        db.add(baseline_snapshot)
        check_log = models.SiteCheckLog(
            site_id=site.id,
            status="baseline_created",
            status_code=fetch_res["status_code"],
            response_time_ms=fetch_res["response_time_ms"],
            created_at=check_time,
        )
        db.add(check_log)
        db.commit()
        db.refresh(baseline_snapshot)
        saved_snapshot = baseline_snapshot

        ret_dict = {
            "site_id": site.id,
            "status": "baseline_created",
            "message": "Initial baseline snapshot created successfully.",
            "status_code": fetch_res["status_code"],
            "response_time_ms": fetch_res["response_time_ms"],
            "content_hash": new_hash,
            "change_id": None,
            "timestamp": check_time,
        }

    # 4B. Unchanged Content (Hash matches previous snapshot)
    elif latest_snapshot.content_hash == new_hash:
        snapshot = models.SiteSnapshot(
            site_id=site.id,
            status_code=fetch_res["status_code"],
            response_time_ms=fetch_res["response_time_ms"],
            content_hash=new_hash,
            text_content=clean_text,
            created_at=check_time,
        )
        db.add(snapshot)
        check_log = models.SiteCheckLog(
            site_id=site.id,
            status="unchanged",
            status_code=fetch_res["status_code"],
            response_time_ms=fetch_res["response_time_ms"],
            created_at=check_time,
        )
        db.add(check_log)
        db.commit()
        db.refresh(snapshot)
        saved_snapshot = snapshot

        ret_dict = {
            "site_id": site.id,
            "status": "unchanged",
            "message": "No content modifications detected (hash matches baseline).",
            "status_code": fetch_res["status_code"],
            "response_time_ms": fetch_res["response_time_ms"],
            "content_hash": new_hash,
            "change_id": None,
            "timestamp": check_time,
        }

    # 4C. Change Detected (Hash differs from latest snapshot)
    else:
        summary, diff_text = generate_diff_summary(latest_snapshot.text_content or "", clean_text)

        change_record = models.DetectedChange(
            site_id=site.id,
            change_type="text",
            summary=summary,
            details=diff_text,
            previous_content=latest_snapshot.text_content,
            new_content=clean_text,
            created_at=check_time,
        )
        db.add(change_record)
        db.flush()

        new_snapshot = models.SiteSnapshot(
            site_id=site.id,
            status_code=fetch_res["status_code"],
            response_time_ms=fetch_res["response_time_ms"],
            content_hash=new_hash,
            text_content=clean_text,
            created_at=check_time,
        )
        db.add(new_snapshot)
        check_log = models.SiteCheckLog(
            site_id=site.id,
            status="change_detected",
            status_code=fetch_res["status_code"],
            response_time_ms=fetch_res["response_time_ms"],
            created_at=check_time,
        )
        db.add(check_log)
        db.commit()
        db.refresh(new_snapshot)
        saved_snapshot = new_snapshot

        from backend import notifications
        notifications.create_notification(
            db=db,
            site_id=site.id,
            event_type="text_change",
            title=f"Text Changed: {site.name}",
            message=f"Detected content modification on {site.name}: {summary}",
            link_type="change",
            link_id=change_record.id,
            dedup_key=f"text_change:{change_record.id}",
        )

        ret_dict = {
            "site_id": site.id,
            "status": "change_detected",
            "message": summary,
            "status_code": fetch_res["status_code"],
            "response_time_ms": fetch_res["response_time_ms"],
            "content_hash": new_hash,
            "change_id": change_record.id,
            "timestamp": check_time,
        }

    # 5. Visual Screenshot Processing (if enabled)
    if should_capture_visual and saved_snapshot:
        try:
            from backend.visual import capture_and_process_visual_snapshot
            v_res = capture_and_process_visual_snapshot(site, saved_snapshot, db)
            ret_dict["screenshot_path"] = v_res.get("screenshot_path")
            ret_dict["screenshot_url"] = v_res.get("screenshot_url")
            ret_dict["visual_diff_percent"] = v_res.get("diff_percent")
            ret_dict["visual_change_detected"] = v_res.get("visual_change_detected")
        except Exception as v_err:
            ret_dict["screenshot_error"] = str(v_err)

    return ret_dict
