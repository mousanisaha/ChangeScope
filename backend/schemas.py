"""Pydantic schemas for request validation and response serialization.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator


class HealthResponse(BaseModel):
    """Schema for GET /api/health endpoint."""
    status: str = Field(..., example="ok")
    app: str = Field(..., example="ChangeScope")
    version: str = Field(..., example="0.1.0")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")
    database: str = Field(..., example="connected")


class MonitoredSiteBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=120, description="Friendly label for the website")
    url: str = Field(..., description="Target web address to monitor")
    check_interval_minutes: int = Field(default=60, ge=1, le=1440, description="Check frequency in minutes")
    is_active: bool = Field(default=True, description="Whether monitoring is enabled")
    capture_screenshots: bool = Field(default=False, description="Whether to capture screenshots during checks")
    visual_threshold: float = Field(default=1.0, ge=0.0, le=100.0, description="Visual difference threshold percentage")


class MonitoredSiteCreate(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048, description="Target web address to monitor")
    name: Optional[str] = Field(default=None, max_length=120, description="Optional friendly label for the website")
    check_interval_minutes: int = Field(default=60, ge=1, le=1440, description="Check frequency in minutes")
    is_active: bool = Field(default=True, description="Whether monitoring is enabled")
    capture_screenshots: bool = Field(default=False, description="Whether to capture screenshots during checks")
    visual_threshold: float = Field(default=1.0, ge=0.0, le=100.0, description="Visual difference threshold percentage")


class MonitoredSiteUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120, description="Friendly label for the website")
    url: Optional[str] = Field(default=None, max_length=2048, description="Target web address to monitor")
    check_interval_minutes: Optional[int] = Field(default=None, ge=1, le=1440, description="Check frequency in minutes")
    is_active: Optional[bool] = Field(default=None, description="Whether monitoring is enabled")
    capture_screenshots: Optional[bool] = Field(default=None, description="Whether to capture screenshots during checks")
    visual_threshold: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Visual difference threshold percentage")


class MonitoredSiteResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    name: str
    url: str
    check_interval_minutes: int
    is_active: bool
    capture_screenshots: bool = False
    visual_threshold: float = 1.0
    last_status_code: Optional[int] = None
    last_response_time_ms: Optional[float] = None
    last_checked_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CheckResultResponse(BaseModel):
    """Result of triggering a manual or scheduled site check."""
    site_id: int
    status: str  # "baseline_created" | "unchanged" | "change_detected" | "check_failed"
    message: str
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    content_hash: Optional[str] = None
    change_id: Optional[int] = None
    timestamp: datetime
    # Visual check status if performed
    screenshot_path: Optional[str] = None
    screenshot_url: Optional[str] = None
    visual_diff_percent: Optional[float] = None
    visual_change_detected: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


class SiteSnapshotResponse(BaseModel):
    id: int
    site_id: int
    status_code: int
    response_time_ms: Optional[float] = None
    content_hash: str
    text_content: Optional[str] = None
    created_at: datetime
    # Visual telemetry
    screenshot_path: Optional[str] = None
    screenshot_url: Optional[str] = None
    screenshot_width: Optional[int] = None
    screenshot_height: Optional[int] = None
    screenshot_size_bytes: Optional[int] = None
    visual_diff_percent: Optional[float] = None
    visual_change_detected: Optional[bool] = None
    screenshot_error: Optional[str] = None
    # Enriched timeline telemetry
    change_label: Optional[str] = None  # "baseline" | "unchanged" | "change_detected"
    has_change: Optional[bool] = None
    line_count: Optional[int] = None
    char_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class ScreenshotMetadataResponse(BaseModel):
    """Detailed metadata for an individual captured screenshot."""
    snapshot_id: int
    site_id: int
    screenshot_path: str
    screenshot_url: str
    width: Optional[int] = None
    height: Optional[int] = None
    size_bytes: Optional[int] = None
    # Compatibility aliases for frontend
    screenshot_width: Optional[int] = None
    screenshot_height: Optional[int] = None
    screenshot_size_bytes: Optional[int] = None
    is_baseline: bool = False
    visual_diff_percent: Optional[float] = None
    visual_change_detected: Optional[bool] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VisualComparisonResponse(BaseModel):
    """Visual comparison results between baseline and latest screenshot for a monitor."""
    site_id: int
    site_name: Optional[str] = None
    site_url: Optional[str] = None
    has_baseline: bool
    has_comparison: bool
    status: Optional[str] = None  # "no_screenshots" | "baseline_only" | "comparison_ready"
    message: Optional[str] = None
    baseline_screenshot: Optional[ScreenshotMetadataResponse] = None
    latest_screenshot: Optional[ScreenshotMetadataResponse] = None
    # Compatibility aliases for frontend
    baseline_snapshot: Optional[ScreenshotMetadataResponse] = None
    previous_snapshot: Optional[ScreenshotMetadataResponse] = None
    latest_snapshot: Optional[ScreenshotMetadataResponse] = None
    diff_image_url: Optional[str] = None
    diff_percent: Optional[float] = None
    visual_change_detected: bool = False
    threshold: float = 1.0
    visual_threshold: Optional[float] = None
    last_captured_at: Optional[datetime] = None
    error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CaptureScreenshotResponse(BaseModel):
    """Result of triggering a screenshot capture and visual change comparison."""
    site_id: int
    status: str  # "baseline_created" | "unchanged" | "visual_change_detected" | "screenshot_failed"
    message: str
    snapshot_id: Optional[int] = None
    screenshot_path: Optional[str] = None
    screenshot_url: Optional[str] = None
    diff_percent: Optional[float] = None
    visual_change_detected: bool = False
    is_baseline: bool = False
    timestamp: datetime
    error: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SnapshotComparisonResponse(BaseModel):
    base_snapshot_id: int
    target_snapshot_id: int
    site_id: int
    site_name: Optional[str] = None
    site_url: Optional[str] = None
    base_created_at: datetime
    target_created_at: datetime
    is_identical: bool
    summary: str
    diff_text: str
    added_lines_count: int
    removed_lines_count: int
    base_text: str
    target_text: str

    model_config = ConfigDict(from_attributes=True)


class DetectedChangeResponse(BaseModel):
    id: int
    site_id: int
    site_name: Optional[str] = None
    site_url: Optional[str] = None
    change_type: str
    summary: str
    details: Optional[str] = None
    previous_content: Optional[str] = None
    new_content: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Analytics & Change Heatmap Schemas (Prompt 7)
# ---------------------------------------------------------------------------

class SiteMetric(BaseModel):
    """Activity metrics for an individual monitored website within a time window."""
    site_id: int
    name: str
    url: str
    total_checks: int = 0
    total_changes: int = 0
    text_changes: int = 0
    visual_changes: int = 0
    failed_checks: int = 0
    change_rate_percent: float = 0.0
    last_change_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DailyMetricPoint(BaseModel):
    """Daily aggregated telemetry point for time-series charts."""
    date: str  # "YYYY-MM-DD"
    checks_count: int = 0
    total_changes: int = 0
    text_changes: int = 0
    visual_changes: int = 0
    failed_checks: int = 0


class AnalyticsSummaryResponse(BaseModel):
    """Aggregated analytics response covering checks, changes, and health metrics."""
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    days: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    total_checks: int = 0
    total_changes: int = 0
    text_changes: int = 0
    visual_changes: int = 0
    failed_checks: int = 0
    change_rate_percent: float = 0.0
    avg_response_time_ms: Optional[float] = None
    status_distribution: dict[str, int] = {}
    top_sites: List[SiteMetric] = []
    timeline: List[DailyMetricPoint] = []


class HeatmapCell(BaseModel):
    """A single cell in the Day-of-Week × Hour-of-Day heatmap matrix."""
    day_of_week: int  # 0=Monday, 1=Tuesday, ..., 6=Sunday
    hour: int         # 0..23
    count: int = 0
    site_ids: List[int] = []


class DailyHeatmapCell(BaseModel):
    """Calendar activity cell for daily change frequency representation."""
    date: str          # "YYYY-MM-DD"
    day_of_week: int   # 0=Monday..6=Sunday
    count: int = 0
    text_changes: int = 0
    visual_changes: int = 0
    intensity: int = 0  # 0=none, 1=low (1-2), 2=medium (3-5), 3=high (6+)


class HeatmapResponse(BaseModel):
    """Aggregated change heatmap dataset for calendar and hourly visualization."""
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    days: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    total_changes: int = 0
    hourly_matrix: List[HeatmapCell] = []
    daily_matrix: List[DailyHeatmapCell] = []
    peak_day: Optional[str] = None
    peak_hour: Optional[int] = None
    sites_activity: List[SiteMetric] = []


# ---------------------------------------------------------------------------
# Notifications & Alerts Schemas (Prompt 8)
# ---------------------------------------------------------------------------

class NotificationResponse(BaseModel):
    """Schema for individual persistent notification alert."""
    id: int
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    site_url: Optional[str] = None
    event_type: str  # "text_change", "visual_change", "check_failed"
    title: str
    message: str
    link_type: Optional[str] = None  # "change", "visual", "monitor"
    link_id: Optional[int] = None
    dedup_key: Optional[str] = None
    is_read: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationListResponse(BaseModel):
    """Paginated or filtered list of notifications with metadata."""
    items: List[NotificationResponse] = []
    total: int = 0
    unread_count: int = 0


class UnreadCountResponse(BaseModel):
    """Lightweight response for topbar and badge polling."""
    unread_count: int = 0


class NotificationPreferenceResponse(BaseModel):
    """Alert event preferences configured by user in Settings."""
    notify_text_change: bool = True
    notify_visual_change: bool = True
    notify_check_failed: bool = True
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class NotificationPreferenceUpdate(BaseModel):
    """Payload to update notification preferences."""
    notify_text_change: Optional[bool] = None
    notify_visual_change: Optional[bool] = None
    notify_check_failed: Optional[bool] = None


class MarkAllReadResponse(BaseModel):
    """Response returned when marking multiple notifications as read."""
    marked_read: int = 0
    unread_count: int = 0


class ScheduledJobInfo(BaseModel):
    """Metadata for an individual scheduled monitoring job."""
    site_id: int
    site_name: str
    site_url: str
    is_active: bool
    check_interval_minutes: int
    next_run_time: Optional[datetime] = None
    last_checked_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_status_code: Optional[int] = None
    job_status: str  # "scheduled", "paused", "disabled_globally"

    model_config = ConfigDict(from_attributes=True)


class RecentOutcomeInfo(BaseModel):
    """Summary of a recent monitoring check log entry."""
    id: int
    site_id: int
    site_name: Optional[str] = None
    status: str
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SchedulerStatusResponse(BaseModel):
    """Detailed runtime status of the automated background scheduler."""
    is_running: bool
    auto_checks_enabled: bool
    active_jobs_count: int
    total_monitors_count: int
    active_monitors_count: int
    paused_monitors_count: int
    max_concurrent_jobs: int
    next_scheduled_check: Optional[datetime] = None
    jobs: List[ScheduledJobInfo] = []
    recent_outcomes: List[RecentOutcomeInfo] = []


class SchedulerSettingsResponse(BaseModel):
    """Global scheduler configuration settings."""
    auto_checks_enabled: bool
    max_concurrent_jobs: int
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SchedulerSettingsUpdate(BaseModel):
    """Request payload to update global scheduler settings."""
    auto_checks_enabled: Optional[bool] = None
    max_concurrent_jobs: Optional[int] = Field(None, ge=1, le=20)


class SchedulerActionResponse(BaseModel):
    """Response returned upon lifecycle actions on the scheduler."""
    success: bool
    message: str
    is_running: bool
    auto_checks_enabled: bool


# ==============================================================================
# Authentication & User Account Schemas (Prompt 10)
# ==============================================================================

class UserRegisterRequest(BaseModel):
    """Payload for user registration."""
    email: str = Field(..., min_length=5, max_length=255, description="User email address")
    password: str = Field(..., min_length=8, max_length=128, description="Account password (min 8 characters)")
    full_name: Optional[str] = Field(default=None, max_length=120, description="Optional full name or display name")

    @field_validator("email")
    @classmethod
    def validate_email_format(cls, v: str) -> str:
        cleaned = v.strip().lower()
        if "@" not in cleaned or "." not in cleaned.split("@")[-1] or len(cleaned) < 5:
            raise ValueError("Invalid email address format.")
        return cleaned


class UserLoginRequest(BaseModel):
    """Payload for user authentication."""
    email: str = Field(..., min_length=3, max_length=255, description="Registered email address")
    password: str = Field(..., min_length=1, max_length=128, description="Account password")


class UserResponse(BaseModel):
    """Public user profile information."""
    id: int
    email: str
    full_name: Optional[str] = None
    is_active: bool = True
    is_admin: bool = False
    auto_checks_enabled: bool = True
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenResponse(BaseModel):
    """Authentication token response returned on register/login."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class UserUpdateRequest(BaseModel):
    """Payload for updating user profile or account-level preferences."""
    full_name: Optional[str] = Field(default=None, max_length=120)
    auto_checks_enabled: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    current_password: Optional[str] = Field(default=None, max_length=128)
    new_password: Optional[str] = Field(default=None, min_length=8, max_length=128)


