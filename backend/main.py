"""ChangeScope — Intelligent Website Change Detector.

Main FastAPI application entrypoint with REST API routes for website monitoring,
text & visual change detection, analytics, notifications, scheduling, and user authentication.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.auth import (
    auth_limiter,
    create_access_token,
    delete_auth_cookie,
    get_current_user,
    hash_password,
    set_auth_cookie,
    verify_password,
)
from backend.database import get_db, init_db
from backend.monitoring import generate_diff_summary, perform_site_check, validate_target_url
from backend.schemas import (
    AnalyticsSummaryResponse,
    CaptureScreenshotResponse,
    CheckResultResponse,
    DetectedChangeResponse,
    HealthResponse,
    HeatmapResponse,
    MarkAllReadResponse,
    MonitoredSiteCreate,
    MonitoredSiteResponse,
    MonitoredSiteUpdate,
    NotificationListResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdate,
    NotificationResponse,
    RecentOutcomeInfo,
    ScheduledJobInfo,
    SchedulerActionResponse,
    SchedulerSettingsResponse,
    SchedulerSettingsUpdate,
    SchedulerStatusResponse,
    ScreenshotMetadataResponse,
    SiteSnapshotResponse,
    SnapshotComparisonResponse,
    TokenResponse,
    UnreadCountResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
    UserUpdateRequest,
    VisualComparisonResponse,
)
from backend.visual import (
    SCREENSHOTS_DIR,
    capture_and_process_visual_snapshot,
    get_screenshot_url,
)
from backend import analytics, models, notifications, scheduler


def normalize_url(url: str) -> str:
    """Normalize input URL by stripping outer whitespace."""
    if not url:
        return ""
    return url.strip()


def infer_name_from_url(url: str) -> str:
    """Derive a friendly display name from a target URL if not provided by user."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or url
        if hostname.startswith("www."):
            hostname = hostname[4:]
        path = parsed.path.rstrip("/")
        if path and path != "":
            return f"{hostname}{path}"
        return hostname
    except Exception:
        return url[:50]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events: initialize database tables and background modules on startup."""
    init_db()
    scheduler.start_scheduler()
    yield
    if scheduler.is_scheduler_running():
        scheduler.stop_scheduler()


# Ensure tables are initialized upon module load
init_db()

app = FastAPI(
    title="ChangeScope API",
    description="Intelligent Website Change Detector backend API",
    version="0.1.0",
    lifespan=lifespan,
)

# Enable CORS for local development flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Diagnostics & Health Check
# ---------------------------------------------------------------------------

@app.get(
    "/api/health",
    response_model=HealthResponse,
    tags=["Diagnostics"],
    summary="Application and database health check",
)
def get_health(db: Session = Depends(get_db)):
    """Health check endpoint returning backend status and verifying SQLite connectivity."""
    db_status = "connected"
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"error: {str(exc)}"

    return HealthResponse(
        status="ok",
        app="ChangeScope",
        version="0.1.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
        database=db_status,
    )


# ---------------------------------------------------------------------------
# Authentication & User Accounts (Prompt 10)
# ---------------------------------------------------------------------------

@app.post(
    "/api/auth/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Authentication"],
    summary="Register a new user account",
)
def register(
    user_in: UserRegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Register a new user account with secure password hashing and auto-login."""
    client_ip = request.client.host if request.client else "unknown"
    auth_limiter.check_rate_limit(client_ip)

    email = user_in.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        auth_limiter.record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid email format.",
        )

    if len(user_in.password) < 8:
        auth_limiter.record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters.",
        )

    existing = db.query(models.User).filter(models.User.email == email).first()
    if existing:
        auth_limiter.record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists.",
        )

    hashed_pw = hash_password(user_in.password)
    user = models.User(
        email=email,
        hashed_password=hashed_pw,
        full_name=user_in.full_name.strip() if user_in.full_name else None,
        is_active=True,
        is_admin=False,
        auto_checks_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    auth_limiter.reset(client_ip)
    access_token = create_access_token({"sub": str(user.id), "email": user.email})
    set_auth_cookie(response, access_token)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@app.post(
    "/api/auth/login",
    response_model=TokenResponse,
    tags=["Authentication"],
    summary="Authenticate with email and password",
)
def login(
    login_in: UserLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Authenticate existing user credentials, issue JWT, and set HTTP-only cookie."""
    client_ip = request.client.host if request.client else "unknown"
    auth_limiter.check_rate_limit(client_ip)

    email = login_in.email.strip().lower()
    user = db.query(models.User).filter(models.User.email == email).first()

    # Constant-time-like safe error: do not reveal whether the email exists
    if not user or not verify_password(login_in.password, user.hashed_password):
        auth_limiter.record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        auth_limiter.record_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    auth_limiter.reset(client_ip)
    access_token = create_access_token({"sub": str(user.id), "email": user.email})
    set_auth_cookie(response, access_token)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@app.post(
    "/api/auth/logout",
    tags=["Authentication"],
    summary="Log out and clear session cookie",
)
def logout(response: Response):
    """Clear session cookie and invalidate client authentication."""
    delete_auth_cookie(response)
    return {"success": True, "message": "Logged out successfully."}


@app.get(
    "/api/auth/me",
    response_model=UserResponse,
    tags=["Authentication"],
    summary="Get profile of currently logged-in user",
)
def get_me(current_user: models.User = Depends(get_current_user)):
    """Retrieve profile and preferences for the currently authenticated user."""
    return UserResponse.model_validate(current_user)


@app.put(
    "/api/auth/me",
    response_model=UserResponse,
    tags=["Authentication"],
    summary="Update profile or preferences of currently logged-in user",
)
def update_me(
    user_update: UserUpdateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update display name, password, or account automation settings."""
    if user_update.full_name is not None:
        current_user.full_name = user_update.full_name.strip() if user_update.full_name else None
    if user_update.auto_checks_enabled is not None:
        current_user.auto_checks_enabled = user_update.auto_checks_enabled
    
    if user_update.current_password or user_update.new_password:
        if not user_update.current_password or not user_update.new_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both current password and new password are required.",
            )
        if not verify_password(user_update.current_password, current_user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect.",
            )
        if len(user_update.new_password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must be at least 8 characters.",
            )
        current_user.hashed_password = hash_password(user_update.new_password)
    elif user_update.password is not None:
        if len(user_update.password) < 8:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters.",
            )
        current_user.hashed_password = hash_password(user_update.password)

    current_user.updated_at = models.utc_now()
    db.commit()
    db.refresh(current_user)
    return UserResponse.model_validate(current_user)


# ---------------------------------------------------------------------------
# Monitor Management Endpoints (Multi-Tenant Scoped)
# ---------------------------------------------------------------------------

@app.get(
    "/api/sites",
    response_model=List[MonitoredSiteResponse],
    tags=["Sites"],
    summary="List all registered monitored sites for current user",
)
def list_sites(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return monitored websites belonging to the authenticated user."""
    sites = (
        db.query(models.MonitoredSite)
        .filter(models.MonitoredSite.user_id == current_user.id)
        .order_by(models.MonitoredSite.created_at.desc())
        .all()
    )
    return sites


@app.post(
    "/api/sites",
    response_model=MonitoredSiteResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Sites"],
    summary="Register a new website for automated monitoring",
)
def create_site(
    site_in: MonitoredSiteCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Register a new website monitor with SSRF security verification and duplicate detection."""
    normalized_url = normalize_url(site_in.url)

    # 1. Enforce SSRF and protocol validations
    is_safe, error_msg = validate_target_url(normalized_url)
    if not is_safe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or prohibited URL: {error_msg}",
        )

    # 2. Check for duplicate monitors for this user
    existing = (
        db.query(models.MonitoredSite)
        .filter(
            models.MonitoredSite.url == normalized_url,
            models.MonitoredSite.user_id == current_user.id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A monitor for URL '{normalized_url}' already exists in your account (ID #{existing.id}: {existing.name}).",
        )

    # 3. Determine site name (fallback to hostname/path if not supplied)
    site_name = site_in.name.strip() if (site_in.name and site_in.name.strip()) else infer_name_from_url(normalized_url)

    # 4. Save to persistent SQLite database
    site = models.MonitoredSite(
        user_id=current_user.id,
        name=site_name,
        url=normalized_url,
        check_interval_minutes=site_in.check_interval_minutes,
        is_active=site_in.is_active,
        capture_screenshots=site_in.capture_screenshots,
        visual_threshold=site_in.visual_threshold,
    )
    db.add(site)
    db.commit()
    db.refresh(site)
    scheduler.sync_site_job(site)
    return site


@app.get(
    "/api/sites/{site_id}",
    response_model=MonitoredSiteResponse,
    tags=["Sites"],
    summary="Retrieve details of a single monitored site",
)
def get_site(
    site_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve an individual monitored website by its unique identifier."""
    site = (
        db.query(models.MonitoredSite)
        .filter(models.MonitoredSite.id == site_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with ID {site_id} not found.",
        )
    return site


@app.put(
    "/api/sites/{site_id}",
    response_model=MonitoredSiteResponse,
    tags=["Sites"],
    summary="Update an existing monitored site",
)
@app.patch(
    "/api/sites/{site_id}",
    response_model=MonitoredSiteResponse,
    tags=["Sites"],
    include_in_schema=False,
)
def update_site(
    site_id: int,
    site_update: MonitoredSiteUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update settings (name, URL, interval, active status) of an existing monitor."""
    site = (
        db.query(models.MonitoredSite)
        .filter(models.MonitoredSite.id == site_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with ID {site_id} not found.",
        )

    # If URL is being modified, re-validate SSRF and check for duplicate collisions within account
    if site_update.url is not None:
        normalized_url = normalize_url(site_update.url)
        if normalized_url != site.url:
            is_safe, error_msg = validate_target_url(normalized_url)
            if not is_safe:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid or prohibited URL: {error_msg}",
                )

            existing = (
                db.query(models.MonitoredSite)
                .filter(
                    models.MonitoredSite.url == normalized_url,
                    models.MonitoredSite.id != site_id,
                    models.MonitoredSite.user_id == current_user.id,
                )
                .first()
            )
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"A monitor for URL '{normalized_url}' already exists in your account (ID #{existing.id}: {existing.name}).",
                )
            site.url = normalized_url

    if site_update.name is not None:
        name_val = site_update.name.strip()
        site.name = name_val if name_val else infer_name_from_url(site.url)

    if site_update.check_interval_minutes is not None:
        site.check_interval_minutes = site_update.check_interval_minutes

    if site_update.is_active is not None:
        site.is_active = site_update.is_active

    if site_update.capture_screenshots is not None:
        site.capture_screenshots = site_update.capture_screenshots

    if site_update.visual_threshold is not None:
        site.visual_threshold = site_update.visual_threshold

    site.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(site)
    scheduler.sync_site_job(site)
    return site


@app.delete(
    "/api/sites/{site_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Sites"],
    summary="Delete a monitored site",
)
def delete_site(
    site_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a monitored site and all its associated historical records from the database."""
    site = (
        db.query(models.MonitoredSite)
        .filter(models.MonitoredSite.id == site_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with ID {site_id} not found.",
        )
    scheduler.remove_site_job(site_id)
    db.delete(site)
    db.commit()
    return None


@app.post(
    "/api/sites/{site_id}/check",
    response_model=CheckResultResponse,
    tags=["Monitoring Engine"],
    summary="Trigger immediate check and change detection cycle for a site",
)
def trigger_site_check(
    site_id: int,
    capture_screenshot: Optional[bool] = Query(None, description="Force capture or skip screenshot for this check"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch website, extract clean text, compare against baseline snapshot, and detect changes."""
    site = (
        db.query(models.MonitoredSite)
        .filter(models.MonitoredSite.id == site_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with ID {site_id} not found.",
        )

    if not scheduler.acquire_site_check_lock(site.id):
        return CheckResultResponse(
            site_id=site.id,
            status="check_failed",
            message=f"Check skipped: Another check is already in progress for '{site.name}'.",
            timestamp=datetime.now(timezone.utc),
        )

    try:
        result = perform_site_check(site, db, capture_screenshot=capture_screenshot)
    finally:
        scheduler.release_site_check_lock(site.id)

    return CheckResultResponse(**result)


# ---------------------------------------------------------------------------
# Change History & Diff Endpoints (Multi-Tenant Scoped)
# ---------------------------------------------------------------------------

@app.get(
    "/api/changes",
    response_model=List[DetectedChangeResponse],
    tags=["Changes"],
    summary="List all detected change events across user's monitored sites",
)
def list_all_changes(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve all detected change events belonging to the user's monitors."""
    changes = (
        db.query(models.DetectedChange)
        .join(models.MonitoredSite)
        .filter(models.MonitoredSite.user_id == current_user.id)
        .order_by(models.DetectedChange.created_at.desc())
        .all()
    )
    results = []
    for c in changes:
        results.append(
            DetectedChangeResponse(
                id=c.id,
                site_id=c.site_id,
                site_name=c.site.name if c.site else None,
                site_url=c.site.url if c.site else None,
                change_type=c.change_type,
                summary=c.summary,
                details=c.details,
                previous_content=c.previous_content,
                new_content=c.new_content,
                created_at=c.created_at,
            )
        )
    return results


@app.get(
    "/api/sites/{site_id}/changes",
    response_model=List[DetectedChangeResponse],
    tags=["Changes"],
    summary="List all detected change events for a specific site",
)
def list_site_changes(
    site_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve detected change events specifically for the given monitor."""
    site = (
        db.query(models.MonitoredSite)
        .filter(models.MonitoredSite.id == site_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with ID {site_id} not found.",
        )

    changes = (
        db.query(models.DetectedChange)
        .filter(models.DetectedChange.site_id == site_id)
        .order_by(models.DetectedChange.created_at.desc())
        .all()
    )
    results = []
    for c in changes:
        results.append(
            DetectedChangeResponse(
                id=c.id,
                site_id=c.site_id,
                site_name=site.name,
                site_url=site.url,
                change_type=c.change_type,
                summary=c.summary,
                details=c.details,
                previous_content=c.previous_content,
                new_content=c.new_content,
                created_at=c.created_at,
            )
        )
    return results


@app.get(
    "/api/changes/{change_id}",
    response_model=DetectedChangeResponse,
    tags=["Changes"],
    summary="Retrieve details and before/after diff for a specific change event",
)
def get_change_details(
    change_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve detailed before/after textual diff for an individual change event."""
    c = (
        db.query(models.DetectedChange)
        .join(models.MonitoredSite)
        .filter(models.DetectedChange.id == change_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not c:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Change event with ID {change_id} not found.",
        )

    return DetectedChangeResponse(
        id=c.id,
        site_id=c.site_id,
        site_name=c.site.name if c.site else None,
        site_url=c.site.url if c.site else None,
        change_type=c.change_type,
        summary=c.summary,
        details=c.details,
        previous_content=c.previous_content,
        new_content=c.new_content,
        created_at=c.created_at,
    )


# ---------------------------------------------------------------------------
# Snapshots & Time Machine Endpoints (Multi-Tenant Scoped)
# ---------------------------------------------------------------------------

@app.get(
    "/api/sites/{site_id}/snapshots",
    response_model=List[SiteSnapshotResponse],
    tags=["Snapshots"],
    summary="List historical snapshots for a specific site with timeline labels",
)
def list_site_snapshots(
    site_id: int,
    order: str = Query("desc", pattern="^(asc|desc)$"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve historical snapshots recorded for the given monitor, with chronological or reverse ordering."""
    site = (
        db.query(models.MonitoredSite)
        .filter(models.MonitoredSite.id == site_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with ID {site_id} not found.",
        )

    chronological_snaps = (
        db.query(models.SiteSnapshot)
        .filter(models.SiteSnapshot.site_id == site_id)
        .order_by(models.SiteSnapshot.created_at.asc(), models.SiteSnapshot.id.asc())
        .all()
    )

    enriched: List[SiteSnapshotResponse] = []
    prev_hash = None
    for idx, snap in enumerate(chronological_snaps):
        if idx == 0:
            label = "baseline"
            has_change = False
        elif snap.content_hash != prev_hash:
            label = "change_detected"
            has_change = True
        else:
            label = "unchanged"
            has_change = False

        prev_hash = snap.content_hash
        text_body = snap.text_content or ""
        lines = len(text_body.splitlines()) if text_body else 0
        chars = len(text_body)

        enriched.append(
            SiteSnapshotResponse(
                id=snap.id,
                site_id=snap.site_id,
                status_code=snap.status_code,
                response_time_ms=snap.response_time_ms,
                content_hash=snap.content_hash,
                text_content=snap.text_content,
                created_at=snap.created_at,
                screenshot_path=snap.screenshot_path,
                screenshot_url=get_screenshot_url(snap.screenshot_path),
                screenshot_width=snap.screenshot_width,
                screenshot_height=snap.screenshot_height,
                screenshot_size_bytes=snap.screenshot_size_bytes,
                visual_diff_percent=snap.visual_diff_percent,
                visual_change_detected=snap.visual_change_detected,
                screenshot_error=snap.screenshot_error,
                change_label=label,
                has_change=has_change,
                line_count=lines,
                char_count=chars,
            )
        )

    if order == "desc":
        enriched.reverse()

    return enriched


@app.get(
    "/api/snapshots/compare",
    response_model=SnapshotComparisonResponse,
    tags=["Snapshots"],
    summary="Compare two snapshots and return text diff highlights",
)
def compare_snapshots(
    base_id: int = Query(..., description="Base snapshot ID"),
    target_id: int = Query(..., description="Target snapshot ID"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Compare extracted text content between two snapshots belonging to the authenticated user."""
    base_snap = (
        db.query(models.SiteSnapshot)
        .join(models.MonitoredSite)
        .filter(models.SiteSnapshot.id == base_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not base_snap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot with ID {base_id} not found.",
        )

    target_snap = (
        db.query(models.SiteSnapshot)
        .join(models.MonitoredSite)
        .filter(models.SiteSnapshot.id == target_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not target_snap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot with ID {target_id} not found.",
        )

    base_text = base_snap.text_content or ""
    target_text = target_snap.text_content or ""
    is_identical = (base_snap.content_hash == target_snap.content_hash)

    summary, diff_text = generate_diff_summary(base_text, target_text)
    if is_identical:
        summary = "Identical content (0 modifications)"

    diff_lines = diff_text.splitlines() if diff_text else []
    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

    site = base_snap.site or target_snap.site

    return SnapshotComparisonResponse(
        base_snapshot_id=base_snap.id,
        target_snapshot_id=target_snap.id,
        site_id=base_snap.site_id,
        site_name=site.name if site else None,
        site_url=site.url if site else None,
        base_created_at=base_snap.created_at,
        target_created_at=target_snap.created_at,
        is_identical=is_identical,
        summary=summary,
        diff_text=diff_text,
        added_lines_count=added,
        removed_lines_count=removed,
        base_text=base_text,
        target_text=target_text,
    )


@app.get(
    "/api/snapshots/{snapshot_id}",
    response_model=SiteSnapshotResponse,
    tags=["Snapshots"],
    summary="Retrieve a specific historical snapshot by ID",
)
def get_snapshot(
    snapshot_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve an individual historical snapshot by its unique identifier."""
    snap = (
        db.query(models.SiteSnapshot)
        .join(models.MonitoredSite)
        .filter(models.SiteSnapshot.id == snapshot_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not snap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Snapshot with ID {snapshot_id} not found.",
        )

    prev_snap = (
        db.query(models.SiteSnapshot)
        .filter(models.SiteSnapshot.site_id == snap.site_id, models.SiteSnapshot.created_at < snap.created_at)
        .order_by(models.SiteSnapshot.created_at.desc(), models.SiteSnapshot.id.desc())
        .first()
    )

    if not prev_snap:
        label = "baseline"
        has_change = False
    elif prev_snap.content_hash != snap.content_hash:
        label = "change_detected"
        has_change = True
    else:
        label = "unchanged"
        has_change = False

    text_body = snap.text_content or ""
    lines = len(text_body.splitlines()) if text_body else 0
    chars = len(text_body)

    return SiteSnapshotResponse(
        id=snap.id,
        site_id=snap.site_id,
        status_code=snap.status_code,
        response_time_ms=snap.response_time_ms,
        content_hash=snap.content_hash,
        text_content=snap.text_content,
        created_at=snap.created_at,
        screenshot_path=snap.screenshot_path,
        screenshot_url=get_screenshot_url(snap.screenshot_path),
        screenshot_width=snap.screenshot_width,
        screenshot_height=snap.screenshot_height,
        screenshot_size_bytes=snap.screenshot_size_bytes,
        visual_diff_percent=snap.visual_diff_percent,
        visual_change_detected=snap.visual_change_detected,
        screenshot_error=snap.screenshot_error,
        change_label=label,
        has_change=has_change,
        line_count=lines,
        char_count=chars,
    )


# ---------------------------------------------------------------------------
# Visual Screenshot Capture & Change Detection Endpoints
# ---------------------------------------------------------------------------

@app.post(
    "/api/sites/{site_id}/capture-screenshot",
    response_model=CaptureScreenshotResponse,
    tags=["Visual Monitoring"],
    summary="Capture a screenshot and run visual change detection for a monitor",
)
def capture_site_screenshot(
    site_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger Playwright to capture a visual screenshot, compare against previous baseline, and record changes."""
    site = (
        db.query(models.MonitoredSite)
        .filter(models.MonitoredSite.id == site_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with ID {site_id} not found.",
        )

    # Pre-flight SSRF check
    is_safe, error_reason = validate_target_url(site.url)
    if not is_safe:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Security validation failed: {error_reason}",
        )

    res = capture_and_process_visual_snapshot(site, snapshot=None, db=db)
    return CaptureScreenshotResponse(**res)


@app.get(
    "/api/sites/{site_id}/visual-comparison",
    response_model=VisualComparisonResponse,
    tags=["Visual Monitoring"],
    summary="Retrieve latest visual comparison results and screenshots for a monitor",
)
def get_visual_comparison(
    site_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve metadata and URLs for baseline vs latest screenshot comparison."""
    site = (
        db.query(models.MonitoredSite)
        .filter(models.MonitoredSite.id == site_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with ID {site_id} not found.",
        )

    snaps = (
        db.query(models.SiteSnapshot)
        .filter(models.SiteSnapshot.site_id == site_id, models.SiteSnapshot.screenshot_path.isnot(None))
        .order_by(models.SiteSnapshot.created_at.asc(), models.SiteSnapshot.id.asc())
        .all()
    )

    if not snaps:
        return VisualComparisonResponse(
            site_id=site.id,
            site_name=site.name,
            site_url=site.url,
            has_baseline=False,
            has_comparison=False,
            status="no_screenshots",
            message="No visual snapshots captured yet.",
            threshold=site.visual_threshold or 1.0,
            visual_threshold=site.visual_threshold or 1.0,
        )

    baseline = snaps[0]
    latest = snaps[-1]
    has_comparison = len(snaps) > 1
    status_str = "comparison_ready" if has_comparison else "baseline_only"
    status_msg = (
        "Visual screenshot comparison ready."
        if has_comparison
        else "Initial visual baseline screenshot recorded."
    )

    base_meta = ScreenshotMetadataResponse(
        snapshot_id=baseline.id,
        site_id=site.id,
        screenshot_path=baseline.screenshot_path,
        screenshot_url=get_screenshot_url(baseline.screenshot_path),
        width=baseline.screenshot_width,
        height=baseline.screenshot_height,
        size_bytes=baseline.screenshot_size_bytes,
        screenshot_width=baseline.screenshot_width,
        screenshot_height=baseline.screenshot_height,
        screenshot_size_bytes=baseline.screenshot_size_bytes,
        is_baseline=True,
        visual_diff_percent=0.0,
        visual_change_detected=False,
        created_at=baseline.created_at,
    )

    latest_meta = ScreenshotMetadataResponse(
        snapshot_id=latest.id,
        site_id=site.id,
        screenshot_path=latest.screenshot_path,
        screenshot_url=get_screenshot_url(latest.screenshot_path),
        width=latest.screenshot_width,
        height=latest.screenshot_height,
        size_bytes=latest.screenshot_size_bytes,
        screenshot_width=latest.screenshot_width,
        screenshot_height=latest.screenshot_height,
        screenshot_size_bytes=latest.screenshot_size_bytes,
        is_baseline=(baseline.id == latest.id),
        visual_diff_percent=latest.visual_diff_percent,
        visual_change_detected=latest.visual_change_detected or False,
        created_at=latest.created_at,
    )

    prev_meta = None
    if len(snaps) > 1:
        prev_snap = snaps[-2]
        prev_meta = ScreenshotMetadataResponse(
            snapshot_id=prev_snap.id,
            site_id=site.id,
            screenshot_path=prev_snap.screenshot_path,
            screenshot_url=get_screenshot_url(prev_snap.screenshot_path),
            width=prev_snap.screenshot_width,
            height=prev_snap.screenshot_height,
            size_bytes=prev_snap.screenshot_size_bytes,
            screenshot_width=prev_snap.screenshot_width,
            screenshot_height=prev_snap.screenshot_height,
            screenshot_size_bytes=prev_snap.screenshot_size_bytes,
            is_baseline=(baseline.id == prev_snap.id),
            visual_diff_percent=prev_snap.visual_diff_percent,
            visual_change_detected=prev_snap.visual_change_detected or False,
            created_at=prev_snap.created_at,
        )

    return VisualComparisonResponse(
        site_id=site.id,
        site_name=site.name,
        site_url=site.url,
        has_baseline=True,
        has_comparison=has_comparison,
        status=status_str,
        message=status_msg,
        baseline_screenshot=base_meta,
        latest_screenshot=latest_meta,
        baseline_snapshot=base_meta,
        previous_snapshot=prev_meta or base_meta,
        latest_snapshot=latest_meta,
        diff_percent=latest.visual_diff_percent,
        visual_change_detected=latest.visual_change_detected or False,
        threshold=site.visual_threshold or 1.0,
        visual_threshold=site.visual_threshold or 1.0,
        last_captured_at=latest.created_at,
        error=latest.screenshot_error,
    )


@app.get(
    "/api/sites/{site_id}/screenshots",
    response_model=List[ScreenshotMetadataResponse],
    tags=["Visual Monitoring"],
    summary="List all captured screenshots for a monitor",
)
def list_site_screenshots(
    site_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all screenshot captures recorded for a monitor."""
    site = (
        db.query(models.MonitoredSite)
        .filter(models.MonitoredSite.id == site_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with ID {site_id} not found.",
        )

    snaps = (
        db.query(models.SiteSnapshot)
        .filter(models.SiteSnapshot.site_id == site_id, models.SiteSnapshot.screenshot_path.isnot(None))
        .order_by(models.SiteSnapshot.created_at.asc(), models.SiteSnapshot.id.asc())
        .all()
    )

    results = []
    for idx, s in enumerate(snaps):
        results.append(
            ScreenshotMetadataResponse(
                snapshot_id=s.id,
                site_id=s.site_id,
                screenshot_path=s.screenshot_path,
                screenshot_url=get_screenshot_url(s.screenshot_path),
                width=s.screenshot_width,
                height=s.screenshot_height,
                size_bytes=s.screenshot_size_bytes,
                is_baseline=(idx == 0),
                visual_diff_percent=s.visual_diff_percent,
                visual_change_detected=s.visual_change_detected,
                created_at=s.created_at,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Analytics & Heatmap Endpoints (Multi-Tenant Scoped)
# ---------------------------------------------------------------------------

@app.get(
    "/api/analytics/summary",
    response_model=AnalyticsSummaryResponse,
    tags=["Analytics"],
    summary="Get aggregated monitoring analytics summary",
)
def get_analytics_summary_endpoint(
    site_id: Optional[int] = Query(None, description="Optional monitor ID to filter by"),
    days: Optional[int] = Query(30, ge=0, le=365, description="Filter to past N days (0 or omitted for all time)"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve aggregated change, check, uptime, and latency analytics."""
    return analytics.get_analytics_summary(db=db, site_id=site_id, days=days, user_id=current_user.id)


@app.get(
    "/api/analytics/heatmap",
    response_model=HeatmapResponse,
    tags=["Analytics"],
    summary="Get change heatmap matrix dataset",
)
def get_change_heatmap_endpoint(
    site_id: Optional[int] = Query(None, description="Optional monitor ID to filter by"),
    days: Optional[int] = Query(30, ge=0, le=365, description="Filter to past N days (0 or omitted for all time)"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve hourly and calendar change frequency heatmap data."""
    return analytics.get_change_heatmap(db=db, site_id=site_id, days=days, user_id=current_user.id)


# ---------------------------------------------------------------------------
# Notifications & Alerts Endpoints (Multi-Tenant Scoped)
# ---------------------------------------------------------------------------

@app.get(
    "/api/notifications",
    response_model=NotificationListResponse,
    tags=["Notifications"],
    summary="List all notifications with unread, monitor, and event type filters",
)
def list_notifications_endpoint(
    unread_only: bool = Query(False, description="Filter for unread alerts only"),
    site_id: Optional[int] = Query(None, description="Filter alerts by monitor ID"),
    event_type: Optional[str] = Query(None, description="Filter by event type (text_change, visual_change, check_failed)"),
    limit: int = Query(50, ge=1, le=200, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve chronologically ordered notification alerts."""
    return notifications.list_notifications(
        db=db,
        unread_only=unread_only,
        site_id=site_id,
        event_type=event_type,
        limit=limit,
        offset=offset,
        user_id=current_user.id,
    )


@app.get(
    "/api/notifications/unread-count",
    response_model=UnreadCountResponse,
    tags=["Notifications"],
    summary="Get count of unread notifications",
)
def get_unread_count_endpoint(
    site_id: Optional[int] = Query(None, description="Optional monitor ID to filter by"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve the total count of unread notifications."""
    count = notifications.get_unread_count(db=db, site_id=site_id, user_id=current_user.id)
    return UnreadCountResponse(unread_count=count)


@app.patch(
    "/api/notifications/{notification_id}/read",
    response_model=NotificationResponse,
    tags=["Notifications"],
    summary="Mark a notification as read",
)
def mark_notification_read_endpoint(
    notification_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a specific notification alert as read."""
    notif = notifications.mark_notification_as_read(db=db, notification_id=notification_id, user_id=current_user.id)
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification with ID {notification_id} not found.",
        )
    return NotificationResponse(
        id=notif.id,
        site_id=notif.site_id,
        site_name=notif.site.name if notif.site else None,
        site_url=notif.site.url if notif.site else None,
        event_type=notif.event_type,
        title=notif.title,
        message=notif.message,
        link_type=notif.link_type,
        link_id=notif.link_id,
        dedup_key=notif.dedup_key,
        is_read=notif.is_read,
        created_at=notif.created_at,
    )


@app.patch(
    "/api/notifications/{notification_id}/unread",
    response_model=NotificationResponse,
    tags=["Notifications"],
    summary="Mark a notification as unread",
)
def mark_notification_unread_endpoint(
    notification_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark a specific notification alert as unread."""
    notif = notifications.mark_notification_as_unread(db=db, notification_id=notification_id, user_id=current_user.id)
    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification with ID {notification_id} not found.",
        )
    return NotificationResponse(
        id=notif.id,
        site_id=notif.site_id,
        site_name=notif.site.name if notif.site else None,
        site_url=notif.site.url if notif.site else None,
        event_type=notif.event_type,
        title=notif.title,
        message=notif.message,
        link_type=notif.link_type,
        link_id=notif.link_id,
        dedup_key=notif.dedup_key,
        is_read=notif.is_read,
        created_at=notif.created_at,
    )


@app.post(
    "/api/notifications/mark-all-read",
    response_model=MarkAllReadResponse,
    tags=["Notifications"],
    summary="Mark all unread notifications as read",
)
def mark_all_notifications_read_endpoint(
    site_id: Optional[int] = Query(None, description="Optional monitor ID to filter by"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark all unread notifications as read."""
    return notifications.mark_all_notifications_as_read(db=db, site_id=site_id, user_id=current_user.id)


@app.delete(
    "/api/notifications/{notification_id}",
    tags=["Notifications"],
    summary="Delete a notification",
)
def delete_notification_endpoint(
    notification_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a notification alert by ID."""
    deleted = notifications.delete_notification(db=db, notification_id=notification_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notification with ID {notification_id} not found.",
        )
    return {"status": "deleted", "notification_id": notification_id}


@app.get(
    "/api/notifications/preferences",
    response_model=NotificationPreferenceResponse,
    tags=["Notifications"],
    summary="Get user notification preferences",
)
def get_notification_preferences_endpoint(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve notification preferences for text changes, visual changes, and failures."""
    return notifications.get_notification_preferences(db=db, user_id=current_user.id)


@app.put(
    "/api/notifications/preferences",
    response_model=NotificationPreferenceResponse,
    tags=["Notifications"],
    summary="Update user notification preferences",
)
def update_notification_preferences_endpoint(
    prefs_in: NotificationPreferenceUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update notification preferences for text changes, visual changes, and failures."""
    return notifications.update_notification_preferences(db=db, update_data=prefs_in, user_id=current_user.id)


# ---------------------------------------------------------------------------
# Scheduler Endpoints (Multi-Tenant Scoped)
# ---------------------------------------------------------------------------

@app.get(
    "/api/scheduler/status",
    response_model=SchedulerStatusResponse,
    tags=["Scheduler"],
    summary="Get background monitoring scheduler runtime status, next checks, and outcomes",
)
def get_scheduler_status(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve status of the scheduler background runner and jobs scoped to the user."""
    return scheduler.get_scheduler_status(db, user_id=current_user.id)


@app.post(
    "/api/scheduler/start",
    response_model=SchedulerActionResponse,
    tags=["Scheduler"],
    summary="Start or resume the background monitoring scheduler",
)
def start_scheduler_endpoint(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Activate the APScheduler background runner and synchronize all active monitor jobs."""
    success = scheduler.start_scheduler()
    return SchedulerActionResponse(
        success=success,
        message="Background monitoring scheduler started successfully." if success else "Failed to start scheduler.",
        is_running=scheduler.is_scheduler_running(),
        auto_checks_enabled=current_user.auto_checks_enabled,
    )


@app.post(
    "/api/scheduler/stop",
    response_model=SchedulerActionResponse,
    tags=["Scheduler"],
    summary="Stop or pause the background monitoring scheduler",
)
def stop_scheduler_endpoint(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Safely stop the APScheduler background runner and pause all scheduled polling."""
    scheduler.stop_scheduler()
    return SchedulerActionResponse(
        success=True,
        message="Background monitoring scheduler stopped successfully.",
        is_running=scheduler.is_scheduler_running(),
        auto_checks_enabled=current_user.auto_checks_enabled,
    )


@app.post(
    "/api/scheduler/sync",
    response_model=SchedulerActionResponse,
    tags=["Scheduler"],
    summary="Synchronize scheduler jobs with current database monitors",
)
def sync_scheduler_endpoint(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Reconcile all scheduled jobs with active and paused monitors in SQLite."""
    if not scheduler.is_scheduler_running():
        scheduler.start_scheduler()
    scheduler.sync_all_monitor_jobs(db)
    return SchedulerActionResponse(
        success=True,
        message="Scheduler jobs synchronized successfully with database monitors.",
        is_running=scheduler.is_scheduler_running(),
        auto_checks_enabled=current_user.auto_checks_enabled,
    )


@app.get(
    "/api/scheduler/settings",
    response_model=SchedulerSettingsResponse,
    tags=["Scheduler"],
    summary="Retrieve scheduler and automation preferences for current user",
)
def get_scheduler_settings_endpoint(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve user automation preferences (auto_checks_enabled, max_concurrent_jobs)."""
    setting = scheduler.get_scheduler_settings(db)
    return SchedulerSettingsResponse(
        auto_checks_enabled=current_user.auto_checks_enabled,
        max_concurrent_jobs=setting.max_concurrent_jobs,
        updated_at=current_user.updated_at,
    )


@app.put(
    "/api/scheduler/settings",
    response_model=SchedulerSettingsResponse,
    tags=["Scheduler"],
    summary="Update scheduler and automation preferences for current user",
)
def update_scheduler_settings_endpoint(
    settings_in: SchedulerSettingsUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Enable or disable automated checks for current user, or configure worker concurrency (admins)."""
    if settings_in.auto_checks_enabled is not None:
        current_user.auto_checks_enabled = settings_in.auto_checks_enabled
        current_user.updated_at = models.utc_now()
        db.commit()
        db.refresh(current_user)
        # Update scheduler global setting and synchronize jobs
        scheduler.update_scheduler_settings(db, auto_checks_enabled=settings_in.auto_checks_enabled)

    setting = scheduler.get_scheduler_settings(db)
    if settings_in.max_concurrent_jobs is not None:
        if current_user.is_admin:
            setting = scheduler.update_scheduler_settings(db, max_concurrent_jobs=settings_in.max_concurrent_jobs)

    return SchedulerSettingsResponse(
        auto_checks_enabled=current_user.auto_checks_enabled,
        max_concurrent_jobs=setting.max_concurrent_jobs,
        updated_at=current_user.updated_at,
    )


@app.post(
    "/api/scheduler/jobs/{site_id}/run-now",
    response_model=CheckResultResponse,
    tags=["Scheduler"],
    summary="Trigger immediate check run via the scheduler pipeline",
)
def run_scheduled_job_now_endpoint(
    site_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger an immediate check execution for a monitor through the scheduler worker."""
    site = (
        db.query(models.MonitoredSite)
        .filter(models.MonitoredSite.id == site_id, models.MonitoredSite.user_id == current_user.id)
        .first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor with ID {site_id} not found.",
        )

    result = scheduler.run_scheduled_site_check(site_id, trigger_source="manual")
    if not result:
        if scheduler.is_check_running(site_id):
            return CheckResultResponse(
                site_id=site_id,
                status="check_failed",
                message=f"Check skipped: Another check is already in progress for '{site.name}'.",
                timestamp=datetime.now(timezone.utc),
            )
        result = perform_site_check(site, db)

    return CheckResultResponse(**result)


# Mount screenshots directory for image serving
if SCREENSHOTS_DIR.exists():
    app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")

# Mount frontend directory for seamless single-server serving
frontend_path = Path(__file__).resolve().parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")
