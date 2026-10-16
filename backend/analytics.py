"""Analytics and Heatmap aggregation engine for ChangeScope.

Processes real snapshots, detected changes, and telemetry logs to compute
calendar heatmaps, hourly distribution matrices, change rates, and uptime analytics.
"""

from datetime import datetime, timedelta, timezone, date
from typing import Dict, List, Optional, Set, Tuple
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend import models, schemas


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def normalize_to_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware and represented in UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_date_bounds(
    days: Optional[int],
    earliest_available: Optional[datetime] = None,
) -> Tuple[datetime, Optional[datetime], date, date]:
    """Compute UTC cutoff datetime and calendar date boundaries."""
    now = datetime.now(timezone.utc)
    today = now.date()

    if days is not None and days > 0:
        cutoff = now - timedelta(days=days)
        start_date = (now - timedelta(days=days - 1)).date()
    else:
        cutoff = None
        if earliest_available:
            start_date = normalize_to_utc(earliest_available).date()
        else:
            start_date = today - timedelta(days=29)

    return now, cutoff, start_date, today


def get_analytics_summary(
    db: Session,
    site_id: Optional[int] = None,
    days: Optional[int] = 30,
    user_id: Optional[int] = None,
) -> schemas.AnalyticsSummaryResponse:
    """Compute aggregated summary analytics for monitors over a selectable time window."""
    site_name: Optional[str] = None
    if site_id is not None:
        q = db.query(models.MonitoredSite).filter(models.MonitoredSite.id == site_id)
        if user_id is not None:
            q = q.filter(models.MonitoredSite.user_id == user_id)
        site = q.first()
        if not site:
            raise HTTPException(status_code=404, detail=f"Monitored site with ID {site_id} not found.")
        site_name = site.name

    # Determine allowed site IDs for multi-tenancy
    if site_id is not None:
        allowed_site_ids = [site_id]
        sites = [site]
    elif user_id is not None:
        sites = db.query(models.MonitoredSite).filter(models.MonitoredSite.user_id == user_id).all()
        allowed_site_ids = [s.id for s in sites]
    else:
        sites = db.query(models.MonitoredSite).all()
        allowed_site_ids = [s.id for s in sites]

    # Determine earliest record to set bounds when days is 0/None
    if not allowed_site_ids:
        earliest_record = None
    else:
        earliest_record = (
            db.query(func.min(models.SiteSnapshot.created_at))
            .filter(models.SiteSnapshot.site_id.in_(allowed_site_ids))
            .scalar()
        )

    now, cutoff, start_date, end_date = resolve_date_bounds(days, earliest_record)

    # 1. Query Snapshots
    if not allowed_site_ids:
        snapshots = []
    else:
        snap_q = db.query(models.SiteSnapshot).filter(models.SiteSnapshot.site_id.in_(allowed_site_ids))
        snapshots = snap_q.order_by(models.SiteSnapshot.created_at.asc()).all()

    # 2. Query Check Logs
    if not allowed_site_ids:
        check_logs = []
    else:
        log_q = db.query(models.SiteCheckLog).filter(models.SiteCheckLog.site_id.in_(allowed_site_ids))
        check_logs = log_q.order_by(models.SiteCheckLog.created_at.asc()).all()

    # 3. Query Detected Changes
    if not allowed_site_ids:
        changes = []
    else:
        change_q = db.query(models.DetectedChange).filter(models.DetectedChange.site_id.in_(allowed_site_ids))
        changes = change_q.order_by(models.DetectedChange.created_at.asc()).all()

    # Apply timezone-safe cutoff filtering
    if cutoff is not None:
        norm_cutoff = normalize_to_utc(cutoff)
        snapshots = [s for s in snapshots if normalize_to_utc(s.created_at) >= norm_cutoff]
        check_logs = [l for l in check_logs if normalize_to_utc(l.created_at) >= norm_cutoff]
        changes = [c for c in changes if normalize_to_utc(c.created_at) >= norm_cutoff]

    # Metrics Computation
    total_changes = len(changes)
    text_changes = sum(1 for c in changes if c.change_type == "text")
    visual_changes = sum(1 for c in changes if c.change_type == "visual")

    failed_from_logs = sum(1 for log in check_logs if log.status == "check_failed")
    failed_from_snaps = sum(1 for s in snapshots if s.status_code >= 400 or (s.screenshot_error is not None and not s.screenshot_path))
    failed_checks = max(failed_from_logs, failed_from_snaps)

    total_checks = max(len(check_logs), len(snapshots) + failed_from_logs)

    change_rate = round((total_changes / total_checks) * 100.0, 1) if total_checks > 0 else 0.0

    # Response Time & Status Distribution
    status_distribution: Dict[str, int] = {}
    latencies: List[float] = []

    for s in snapshots:
        if s.response_time_ms is not None:
            latencies.append(s.response_time_ms)
        code_str = str(s.status_code)
        status_distribution[code_str] = status_distribution.get(code_str, 0) + 1

    for log in check_logs:
        if log.status_code and str(log.status_code) not in status_distribution:
            status_distribution[str(log.status_code)] = status_distribution.get(str(log.status_code), 0) + 1

    avg_response_time = round(sum(latencies) / len(latencies), 1) if latencies else None

    # Top Volatile Sites Metric
    site_metrics_list: List[schemas.SiteMetric] = []
    for s_entity in sites:
        s_changes = [c for c in changes if c.site_id == s_entity.id]
        s_snaps = [sn for sn in snapshots if sn.site_id == s_entity.id]
        s_logs = [l for l in check_logs if l.site_id == s_entity.id]

        s_total_changes = len(s_changes)
        s_text_changes = sum(1 for c in s_changes if c.change_type == "text")
        s_visual_changes = sum(1 for c in s_changes if c.change_type == "visual")
        s_failed_logs = sum(1 for l in s_logs if l.status == "check_failed")
        s_failed_snaps = sum(1 for sn in s_snaps if sn.status_code >= 400)
        s_failed = max(s_failed_logs, s_failed_snaps)
        s_checks = max(len(s_logs), len(s_snaps) + s_failed_logs)

        last_change = s_changes[-1].created_at if s_changes else None
        s_rate = round((s_total_changes / s_checks) * 100.0, 1) if s_checks > 0 else 0.0

        site_metrics_list.append(
            schemas.SiteMetric(
                site_id=s_entity.id,
                name=s_entity.name,
                url=s_entity.url,
                total_checks=s_checks,
                total_changes=s_total_changes,
                text_changes=s_text_changes,
                visual_changes=s_visual_changes,
                failed_checks=s_failed,
                change_rate_percent=s_rate,
                last_change_at=last_change,
            )
        )

    site_metrics_list.sort(key=lambda item: (item.total_changes, item.total_checks), reverse=True)

    # 5. Timeline Generation (Calendar day by day)
    timeline: List[schemas.DailyMetricPoint] = []
    curr = start_date
    while curr <= end_date:
        date_str = curr.strftime("%Y-%m-%d")

        # Filter items on this date
        day_snaps = [
            s for s in snapshots
            if normalize_to_utc(s.created_at).date() == curr
        ]
        day_logs = [
            l for l in check_logs
            if normalize_to_utc(l.created_at).date() == curr
        ]
        day_changes = [
            c for c in changes
            if normalize_to_utc(c.created_at).date() == curr
        ]

        day_text = sum(1 for c in day_changes if c.change_type == "text")
        day_visual = sum(1 for c in day_changes if c.change_type == "visual")
        day_failed_logs = sum(1 for l in day_logs if l.status == "check_failed")
        day_failed_snaps = sum(1 for s in day_snaps if s.status_code >= 400)
        day_failed = max(day_failed_logs, day_failed_snaps)
        day_checks = max(len(day_logs), len(day_snaps) + day_failed_logs)

        timeline.append(
            schemas.DailyMetricPoint(
                date=date_str,
                checks_count=day_checks,
                total_changes=len(day_changes),
                text_changes=day_text,
                visual_changes=day_visual,
                failed_checks=day_failed,
            )
        )
        curr += timedelta(days=1)

    return schemas.AnalyticsSummaryResponse(
        site_id=site_id,
        site_name=site_name,
        days=days,
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        total_checks=total_checks,
        total_changes=total_changes,
        text_changes=text_changes,
        visual_changes=visual_changes,
        failed_checks=failed_checks,
        change_rate_percent=change_rate,
        avg_response_time_ms=avg_response_time,
        status_distribution=status_distribution,
        top_sites=site_metrics_list,
        timeline=timeline,
    )


def get_change_heatmap(
    db: Session,
    site_id: Optional[int] = None,
    days: Optional[int] = 30,
    user_id: Optional[int] = None,
) -> schemas.HeatmapResponse:
    """Compute hourly and calendar matrix heatmap datasets for detected changes."""
    site_name: Optional[str] = None
    if site_id is not None:
        q = db.query(models.MonitoredSite).filter(models.MonitoredSite.id == site_id)
        if user_id is not None:
            q = q.filter(models.MonitoredSite.user_id == user_id)
        site = q.first()
        if not site:
            raise HTTPException(status_code=404, detail=f"Monitored site with ID {site_id} not found.")
        site_name = site.name

    if site_id is not None:
        allowed_site_ids = [site_id]
        sites = [site]
    elif user_id is not None:
        sites = db.query(models.MonitoredSite).filter(models.MonitoredSite.user_id == user_id).all()
        allowed_site_ids = [s.id for s in sites]
    else:
        sites = db.query(models.MonitoredSite).all()
        allowed_site_ids = [s.id for s in sites]

    if not allowed_site_ids:
        earliest_change = None
    else:
        earliest_change = (
            db.query(func.min(models.DetectedChange.created_at))
            .filter(models.DetectedChange.site_id.in_(allowed_site_ids))
            .scalar()
        )

    now, cutoff, start_date, end_date = resolve_date_bounds(days, earliest_change)

    # 1. Query Changes
    if not allowed_site_ids:
        changes = []
    else:
        change_q = db.query(models.DetectedChange).filter(models.DetectedChange.site_id.in_(allowed_site_ids))
        changes = change_q.order_by(models.DetectedChange.created_at.asc()).all()

    if cutoff is not None:
        norm_cutoff = normalize_to_utc(cutoff)
        changes = [c for c in changes if normalize_to_utc(c.created_at) >= norm_cutoff]

    # 3. Build 7x24 Hourly Matrix Map
    # Key: (day_of_week: 0..6, hour: 0..23)
    hourly_map: Dict[Tuple[int, int], Dict[str, object]] = {
        (dow, hr): {"count": 0, "site_ids": set()}
        for dow in range(7)
        for hr in range(24)
    }

    day_totals = {dow: 0 for dow in range(7)}
    hour_totals = {hr: 0 for hr in range(24)}

    for change in changes:
        c_dt = normalize_to_utc(change.created_at)
        if c_dt:
            dow = c_dt.weekday()  # 0=Monday..6=Sunday
            hr = c_dt.hour
            hourly_map[(dow, hr)]["count"] += 1
            hourly_map[(dow, hr)]["site_ids"].add(change.site_id)
            day_totals[dow] += 1
            hour_totals[hr] += 1

    hourly_matrix: List[schemas.HeatmapCell] = [
        schemas.HeatmapCell(
            day_of_week=dow,
            hour=hr,
            count=hourly_map[(dow, hr)]["count"],
            site_ids=sorted(list(hourly_map[(dow, hr)]["site_ids"])),
        )
        for dow in range(7)
        for hr in range(24)
    ]

    # Peak Day & Peak Hour
    peak_dow = max(day_totals, key=day_totals.get) if any(day_totals.values()) else None
    peak_day_name = DAY_NAMES[peak_dow] if peak_dow is not None else None
    peak_hr = max(hour_totals, key=hour_totals.get) if any(hour_totals.values()) else None

    # 4. Daily Calendar Heatmap Matrix
    daily_matrix: List[schemas.DailyHeatmapCell] = []
    curr = start_date
    while curr <= end_date:
        date_str = curr.strftime("%Y-%m-%d")
        dow = curr.weekday()

        day_changes = [
            c for c in changes
            if normalize_to_utc(c.created_at).date() == curr
        ]

        c_count = len(day_changes)
        text_count = sum(1 for c in day_changes if c.change_type == "text")
        visual_count = sum(1 for c in day_changes if c.change_type == "visual")

        if c_count == 0:
            intensity = 0
        elif c_count <= 2:
            intensity = 1
        elif c_count <= 5:
            intensity = 2
        else:
            intensity = 3

        daily_matrix.append(
            schemas.DailyHeatmapCell(
                date=date_str,
                day_of_week=dow,
                count=c_count,
                text_changes=text_count,
                visual_changes=visual_count,
                intensity=intensity,
            )
        )
        curr += timedelta(days=1)

    # 5. Site Breakdown
    sites_activity: List[schemas.SiteMetric] = []
    for s_entity in sites:
        s_changes = [c for c in changes if c.site_id == s_entity.id]
        s_text = sum(1 for c in s_changes if c.change_type == "text")
        s_visual = sum(1 for c in s_changes if c.change_type == "visual")
        last_change = s_changes[-1].created_at if s_changes else None

        sites_activity.append(
            schemas.SiteMetric(
                site_id=s_entity.id,
                name=s_entity.name,
                url=s_entity.url,
                total_checks=0,  # Not required for heatmap site ranking
                total_changes=len(s_changes),
                text_changes=s_text,
                visual_changes=s_visual,
                failed_checks=0,
                change_rate_percent=0.0,
                last_change_at=last_change,
            )
        )

    sites_activity.sort(key=lambda s: s.total_changes, reverse=True)

    return schemas.HeatmapResponse(
        site_id=site_id,
        site_name=site_name,
        days=days,
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        total_changes=len(changes),
        hourly_matrix=hourly_matrix,
        daily_matrix=daily_matrix,
        peak_day=peak_day_name,
        peak_hour=peak_hr,
        sites_activity=sites_activity,
    )
