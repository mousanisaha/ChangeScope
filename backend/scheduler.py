"""Background scheduling manager for ChangeScope.

Integrates APScheduler (BackgroundScheduler) for automated recurring website checks,
concurrency control, overlapping check prevention, and failure resilience.
"""

from datetime import datetime, timezone
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Set

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session

from backend import models

logger = logging.getLogger("changescope.scheduler")

# Internal singleton scheduler state
_scheduler: Optional[BackgroundScheduler] = None
_session_factory: Optional[Callable[[], Session]] = None
_running_site_checks: Set[int] = set()
_site_check_lock = threading.Lock()
_scheduler_lock = threading.Lock()


def utc_now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def get_session_factory() -> Callable[[], Session]:
    """Retrieve session factory callable, defaulting to database.SessionLocal."""
    global _session_factory
    if _session_factory is not None:
        return _session_factory
    from backend.database import SessionLocal
    return SessionLocal


def set_session_factory(factory: Optional[Callable[[], Session]]) -> None:
    """Set custom session factory for testing or database isolation."""
    global _session_factory
    _session_factory = factory


def get_scheduler_settings(db: Session) -> models.SchedulerSetting:
    """Retrieve global scheduler settings from SQLite, creating row if missing."""
    setting = db.query(models.SchedulerSetting).filter(models.SchedulerSetting.id == 1).first()
    if not setting:
        setting = models.SchedulerSetting(id=1, auto_checks_enabled=True, max_concurrent_jobs=5)
        db.add(setting)
        try:
            db.commit()
            db.refresh(setting)
        except Exception:
            db.rollback()
            setting = db.query(models.SchedulerSetting).filter(models.SchedulerSetting.id == 1).first()
    return setting


def update_scheduler_settings(
    db: Session,
    auto_checks_enabled: Optional[bool] = None,
    max_concurrent_jobs: Optional[int] = None,
) -> models.SchedulerSetting:
    """Update global scheduler configuration settings and synchronize active jobs."""
    setting = get_scheduler_settings(db)
    state_changed = False

    if auto_checks_enabled is not None and setting.auto_checks_enabled != auto_checks_enabled:
        setting.auto_checks_enabled = auto_checks_enabled
        state_changed = True

    if max_concurrent_jobs is not None:
        setting.max_concurrent_jobs = max_concurrent_jobs

    setting.updated_at = utc_now()
    db.commit()
    db.refresh(setting)

    if state_changed:
        sync_all_monitor_jobs(db)

    return setting


def acquire_site_check_lock(site_id: int) -> bool:
    """Attempt to acquire execution lock for a monitor. Returns True if acquired, False if already running."""
    with _site_check_lock:
        if site_id in _running_site_checks:
            return False
        _running_site_checks.add(site_id)
        return True


def release_site_check_lock(site_id: int) -> None:
    """Release execution lock for a monitor."""
    with _site_check_lock:
        _running_site_checks.discard(site_id)


def is_check_running(site_id: int) -> bool:
    """Return whether a check is currently active for the given monitor ID."""
    with _site_check_lock:
        return site_id in _running_site_checks


def init_scheduler() -> None:
    """Initialize the background task scheduler."""
    logger.info("ChangeScope background scheduler initialized in standby mode.")


def start_scheduler(session_factory: Optional[Callable[[], Session]] = None) -> bool:
    """Start the background APScheduler instance safely and synchronize all active jobs."""
    global _scheduler
    with _scheduler_lock:
        if session_factory is not None:
            set_session_factory(session_factory)

        if _scheduler is not None and _scheduler.running:
            logger.info("Scheduler already active; skipping duplicate startup.")
            return True

        executors = {
            "default": ThreadPoolExecutor(max_workers=5),
        }
        job_defaults = {
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 300,
        }

        _scheduler = BackgroundScheduler(
            executors=executors,
            job_defaults=job_defaults,
            timezone="UTC",
        )

        try:
            _scheduler.start()
            logger.info("APScheduler BackgroundScheduler started successfully.")
        except Exception as exc:
            logger.error(f"Failed to start APScheduler: {exc}", exc_info=True)
            return False

        # Synchronize active monitor jobs from database
        try:
            sync_all_monitor_jobs()
        except Exception as exc:
            logger.warning(f"Initial monitor job synchronization encountered an error: {exc}")

        return True


def stop_scheduler() -> bool:
    """Safely shut down the background task scheduler and clean up threads."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None:
            try:
                if _scheduler.running:
                    _scheduler.shutdown(wait=False)
                    logger.info("APScheduler BackgroundScheduler shut down successfully.")
            except Exception as exc:
                logger.warning(f"Exception during scheduler shutdown: {exc}")
            finally:
                _scheduler = None
        return False


def is_scheduler_running() -> bool:
    """Return whether the background scheduler is currently active."""
    return _scheduler is not None and _scheduler.running


def get_scheduler_instance() -> Optional[BackgroundScheduler]:
    """Retrieve the raw APScheduler instance (useful for unit tests and introspection)."""
    return _scheduler


def schedule_site_job(site_id: int, check_interval_minutes: int, run_immediately: bool = False) -> None:
    """Register or replace an automated periodic check job for a specific monitor."""
    if _scheduler is None or not _scheduler.running:
        return

    job_id = f"site_check_{site_id}"
    interval = max(1, check_interval_minutes)
    trigger = IntervalTrigger(minutes=interval, timezone="UTC")

    job_kwargs: Dict[str, Any] = {
        "func": run_scheduled_site_check,
        "trigger": trigger,
        "id": job_id,
        "args": [site_id, "scheduler"],
        "replace_existing": True,
        "max_instances": 1,
        "coalesce": True,
        "misfire_grace_time": 300,
    }
    if run_immediately:
        job_kwargs["next_run_time"] = utc_now()

    _scheduler.add_job(**job_kwargs)
    logger.info(f"Registered scheduled job {job_id} with interval of {interval}m.")


def remove_site_job(site_id: int) -> None:
    """Remove a scheduled monitoring job from APScheduler if registered."""
    if _scheduler is None:
        return
    job_id = f"site_check_{site_id}"
    try:
        _scheduler.remove_job(job_id)
        logger.info(f"Removed scheduled job {job_id}.")
    except (JobLookupError, KeyError):
        pass


def sync_site_job(site: models.MonitoredSite, auto_checks_enabled: Optional[bool] = None) -> None:
    """Sync an individual monitor's scheduled job based on its active state and global setting."""
    if _scheduler is None or not _scheduler.running:
        return

    if auto_checks_enabled is None:
        db = get_session_factory()()
        try:
            setting = get_scheduler_settings(db)
            auto_checks_enabled = setting.auto_checks_enabled
        finally:
            db.close()

    if auto_checks_enabled and site.is_active:
        schedule_site_job(site.id, site.check_interval_minutes)
    else:
        remove_site_job(site.id)


def sync_all_monitor_jobs(db: Optional[Session] = None) -> None:
    """Synchronize all monitor jobs in the scheduler with current database configuration."""
    if _scheduler is None or not _scheduler.running:
        return

    own_session = False
    if db is None:
        db = get_session_factory()()
        own_session = True

    try:
        setting = get_scheduler_settings(db)

        if not setting.auto_checks_enabled:
            # When auto-checks are globally disabled, remove all site check jobs
            for job in list(_scheduler.get_jobs()):
                if job.id.startswith("site_check_"):
                    try:
                        job.remove()
                    except Exception:
                        pass
            logger.info("Global auto-checks disabled; all monitor scheduler jobs unscheduled.")
            return

        # When auto-checks are enabled, schedule active monitors and remove inactive ones
        sites = db.query(models.MonitoredSite).all()
        active_site_ids: Set[int] = set()

        for site in sites:
            if site.is_active:
                active_site_ids.add(site.id)
                schedule_site_job(site.id, site.check_interval_minutes)
            else:
                remove_site_job(site.id)

        # Remove orphan jobs for sites no longer in database
        for job in list(_scheduler.get_jobs()):
            if job.id.startswith("site_check_"):
                try:
                    site_id = int(job.id.replace("site_check_", ""))
                    if site_id not in active_site_ids:
                        job.remove()
                except Exception:
                    pass

        logger.info(f"Synchronized {len(active_site_ids)} active monitor jobs with scheduler.")
    finally:
        if own_session:
            db.close()


def run_scheduled_site_check(site_id: int, trigger_source: str = "scheduler") -> Optional[Dict[str, Any]]:
    """Execute a scheduled monitoring cycle for a target website safely.

    Prevents overlapping checks, verifies monitor status and global preferences,
    and isolates exceptions so scheduler execution never halts.
    """
    if not acquire_site_check_lock(site_id):
        logger.info(f"Skipping scheduled check for monitor #{site_id}: check already in progress.")
        return None

    db = get_session_factory()()
    try:
        setting = get_scheduler_settings(db)
        if not setting.auto_checks_enabled and trigger_source == "scheduler":
            logger.info(f"Skipping scheduled check for monitor #{site_id}: auto-checks disabled globally.")
            return None

        site = db.query(models.MonitoredSite).filter(models.MonitoredSite.id == site_id).first()
        if not site:
            logger.warning(f"Monitor #{site_id} no longer exists. Removing scheduler job.")
            remove_site_job(site_id)
            return None

        # Verify user account state if monitor is user-owned
        if site.user_id:
            user = db.query(models.User).filter(models.User.id == site.user_id).first()
            if user:
                if not user.is_active and trigger_source == "scheduler":
                    logger.info(f"Skipping monitor #{site_id}: user #{site.user_id} account is inactive.")
                    return None
                if not user.auto_checks_enabled and trigger_source == "scheduler":
                    logger.info(f"Skipping monitor #{site_id}: user #{site.user_id} disabled auto-checks.")
                    return None

        if not site.is_active and trigger_source == "scheduler":
            logger.info(f"Monitor #{site_id} ({site.name}) is paused. Removing scheduler job.")
            remove_site_job(site_id)
            return None

        logger.info(f"Executing scheduled check for monitor #{site_id} ({site.name}) [source={trigger_source}].")

        from backend.monitoring import perform_site_check
        result = perform_site_check(site, db)
        logger.info(f"Scheduled check complete for monitor #{site_id} ({site.name}): status={result.get('status')}")
        return result
    except Exception as exc:
        logger.error(f"Unhandled error during scheduled check for monitor #{site_id}: {exc}", exc_info=True)
        return None
    finally:
        db.close()
        release_site_check_lock(site_id)


def get_scheduler_status(db: Session, user_id: Optional[int] = None) -> Dict[str, Any]:
    """Compile comprehensive runtime status, scheduled job queue, and recent outcomes, optionally scoped to a user."""
    setting = get_scheduler_settings(db)
    is_running = is_scheduler_running()

    user = None
    if user_id:
        user = db.query(models.User).filter(models.User.id == user_id).first()

    auto_checks_enabled = user.auto_checks_enabled if user else setting.auto_checks_enabled
    max_concurrent_jobs = setting.max_concurrent_jobs

    query = db.query(models.MonitoredSite)
    if user_id:
        query = query.filter(models.MonitoredSite.user_id == user_id)
    sites = query.order_by(models.MonitoredSite.name.asc()).all()
    user_site_ids = [s.id for s in sites]

    total_monitors = len(sites)
    active_monitors = sum(1 for s in sites if s.is_active)
    paused_monitors = total_monitors - active_monitors

    jobs_data: List[Dict[str, Any]] = []
    next_times: List[datetime] = []

    for s in sites:
        job = _scheduler.get_job(f"site_check_{s.id}") if _scheduler else None
        next_run: Optional[datetime] = None

        if job and job.next_run_time:
            next_run = job.next_run_time
            next_times.append(next_run)

        if not s.is_active:
            job_status = "paused"
        elif not auto_checks_enabled:
            job_status = "disabled_globally"
        elif job is not None:
            job_status = "scheduled"
        else:
            job_status = "standby"

        # Determine last status from latest check log
        last_log = (
            db.query(models.SiteCheckLog)
            .filter(models.SiteCheckLog.site_id == s.id)
            .order_by(models.SiteCheckLog.created_at.desc())
            .first()
        )

        jobs_data.append({
            "site_id": s.id,
            "site_name": s.name,
            "site_url": s.url,
            "is_active": s.is_active,
            "check_interval_minutes": s.check_interval_minutes,
            "next_run_time": next_run,
            "last_checked_at": s.last_checked_at,
            "last_status": last_log.status if last_log else None,
            "last_status_code": last_log.status_code if last_log else s.last_status_code,
            "job_status": job_status,
        })

    active_jobs_count = len(next_times) if user_id else len([j for j in (_scheduler.get_jobs() if _scheduler else []) if j.id.startswith("site_check_")])
    next_scheduled_check = min(next_times) if next_times else None

    # Fetch recent 15 check outcomes for monitored targets
    recent_logs_query = db.query(models.SiteCheckLog)
    if user_id:
        if user_site_ids:
            recent_logs_query = recent_logs_query.filter(models.SiteCheckLog.site_id.in_(user_site_ids))
        else:
            recent_logs_query = recent_logs_query.filter(models.SiteCheckLog.site_id == -1)

    recent_logs = (
        recent_logs_query
        .order_by(models.SiteCheckLog.created_at.desc())
        .limit(15)
        .all()
    )

    recent_outcomes: List[Dict[str, Any]] = []
    for log in recent_logs:
        site_name = log.site.name if log.site else f"Monitor #{log.site_id}"
        recent_outcomes.append({
            "id": log.id,
            "site_id": log.site_id,
            "site_name": site_name,
            "status": log.status,
            "status_code": log.status_code,
            "response_time_ms": log.response_time_ms,
            "error_message": log.error_message,
            "created_at": log.created_at,
        })

    return {
        "is_running": is_running,
        "auto_checks_enabled": auto_checks_enabled,
        "active_jobs_count": active_jobs_count,
        "total_monitors_count": total_monitors,
        "active_monitors_count": active_monitors,
        "paused_monitors_count": paused_monitors,
        "max_concurrent_jobs": max_concurrent_jobs,
        "next_scheduled_check": next_scheduled_check,
        "jobs": jobs_data,
        "recent_outcomes": recent_outcomes,
    }


def get_scheduled_jobs() -> Dict[str, Any]:
    """Compatibility helper returning summary of scheduled jobs."""
    jobs_count = len([j for j in (_scheduler.get_jobs() if _scheduler else []) if j.id.startswith("site_check_")])
    return {
        "status": "active" if is_scheduler_running() else "standby",
        "active_jobs_count": jobs_count,
        "jobs": [j.id for j in (_scheduler.get_jobs() if _scheduler else [])],
    }
