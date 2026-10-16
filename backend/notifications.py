"""Notification service and alert management for ChangeScope.

Handles creation, deduplication, retrieval, reading status, and preferences
for website monitoring alerts (text changes, visual changes, check failures),
with strict multi-tenant user isolation.
"""

from typing import List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models, schemas


def get_notification_preferences(db: Session, user_id: Optional[int] = None) -> models.NotificationPreference:
    """Retrieve notification preferences for a user, initializing defaults if needed."""
    if user_id is not None:
        prefs = db.query(models.NotificationPreference).filter(models.NotificationPreference.user_id == user_id).first()
        if not prefs:
            prefs = models.NotificationPreference(
                user_id=user_id,
                notify_text_change=True,
                notify_visual_change=True,
                notify_check_failed=True,
                updated_at=models.utc_now(),
            )
            db.add(prefs)
            try:
                db.commit()
                db.refresh(prefs)
            except Exception:
                db.rollback()
                prefs = db.query(models.NotificationPreference).filter(models.NotificationPreference.user_id == user_id).first()
        return prefs

    # Fallback to system-level preference (id=1)
    prefs = db.query(models.NotificationPreference).filter(models.NotificationPreference.id == 1).first()
    if not prefs:
        prefs = models.NotificationPreference(
            id=1,
            notify_text_change=True,
            notify_visual_change=True,
            notify_check_failed=True,
            updated_at=models.utc_now(),
        )
        db.add(prefs)
        try:
            db.commit()
            db.refresh(prefs)
        except Exception:
            db.rollback()
            prefs = db.query(models.NotificationPreference).filter(models.NotificationPreference.id == 1).first()
    return prefs


def update_notification_preferences(
    db: Session,
    update_data: schemas.NotificationPreferenceUpdate,
    user_id: Optional[int] = None,
) -> models.NotificationPreference:
    """Update user notification preferences."""
    prefs = get_notification_preferences(db, user_id=user_id)

    if update_data.notify_text_change is not None:
        prefs.notify_text_change = update_data.notify_text_change
    if update_data.notify_visual_change is not None:
        prefs.notify_visual_change = update_data.notify_visual_change
    if update_data.notify_check_failed is not None:
        prefs.notify_check_failed = update_data.notify_check_failed

    prefs.updated_at = models.utc_now()
    db.commit()
    db.refresh(prefs)
    return prefs


def create_notification(
    db: Session,
    site_id: Optional[int],
    event_type: str,  # "text_change", "visual_change", "check_failed"
    title: str,
    message: str,
    link_type: Optional[str] = None,
    link_id: Optional[int] = None,
    dedup_key: Optional[str] = None,
    user_id: Optional[int] = None,
) -> Optional[models.Notification]:
    """Create a persistent notification with preference checking and deduplication."""
    # Resolve user_id from site if not provided explicitly
    if user_id is None and site_id is not None:
        site = db.query(models.MonitoredSite).filter(models.MonitoredSite.id == site_id).first()
        if site:
            user_id = site.user_id

    # 1. Check user preferences
    prefs = get_notification_preferences(db, user_id=user_id)
    if event_type == "text_change" and not prefs.notify_text_change:
        return None
    if event_type == "visual_change" and not prefs.notify_visual_change:
        return None
    if event_type == "check_failed" and not prefs.notify_check_failed:
        return None

    # 2. Strict Deduplication via dedup_key
    if dedup_key:
        existing = db.query(models.Notification).filter(models.Notification.dedup_key == dedup_key).first()
        if existing:
            return existing

    # 3. Intelligent check failure deduplication:
    # If the monitor already has an active (unread) failure notification with the same error, avoid spamming
    if event_type == "check_failed" and site_id:
        last_failure = (
            db.query(models.Notification)
            .filter(
                models.Notification.site_id == site_id,
                models.Notification.event_type == "check_failed",
                models.Notification.is_read.is_(False),
            )
            .order_by(models.Notification.created_at.desc(), models.Notification.id.desc())
            .first()
        )
        if last_failure and last_failure.message == message:
            return last_failure

    # 4. Create and persist notification
    notification = models.Notification(
        user_id=user_id,
        site_id=site_id,
        event_type=event_type,
        title=title,
        message=message,
        link_type=link_type,
        link_id=link_id,
        dedup_key=dedup_key,
        is_read=False,
        created_at=models.utc_now(),
    )
    db.add(notification)
    try:
        db.commit()
        db.refresh(notification)
    except Exception:
        db.rollback()
        # If another thread concurrently inserted the exact same dedup_key
        if dedup_key:
            return db.query(models.Notification).filter(models.Notification.dedup_key == dedup_key).first()
        raise

    return notification


def list_notifications(
    db: Session,
    unread_only: bool = False,
    site_id: Optional[int] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    user_id: Optional[int] = None,
) -> schemas.NotificationListResponse:
    """Retrieve filtered notifications ordered chronologically (newest first)."""
    query = db.query(models.Notification)

    if user_id is not None:
        query = query.filter(models.Notification.user_id == user_id)
    if unread_only:
        query = query.filter(models.Notification.is_read.is_(False))
    if site_id is not None:
        query = query.filter(models.Notification.site_id == site_id)
    if event_type:
        query = query.filter(models.Notification.event_type == event_type)

    total = query.count()
    records = (
        query.order_by(models.Notification.created_at.desc(), models.Notification.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    unread_query = db.query(models.Notification).filter(models.Notification.is_read.is_(False))
    if user_id is not None:
        unread_query = unread_query.filter(models.Notification.user_id == user_id)
    if site_id is not None:
        unread_query = unread_query.filter(models.Notification.site_id == site_id)
    unread_count = unread_query.count()

    items = []
    for notif in records:
        site_name = notif.site.name if notif.site else None
        site_url = notif.site.url if notif.site else None
        items.append(
            schemas.NotificationResponse(
                id=notif.id,
                site_id=notif.site_id,
                site_name=site_name,
                site_url=site_url,
                event_type=notif.event_type,
                title=notif.title,
                message=notif.message,
                link_type=notif.link_type,
                link_id=notif.link_id,
                dedup_key=notif.dedup_key,
                is_read=notif.is_read,
                created_at=notif.created_at,
            )
        )

    return schemas.NotificationListResponse(items=items, total=total, unread_count=unread_count)


def get_unread_count(db: Session, site_id: Optional[int] = None, user_id: Optional[int] = None) -> int:
    """Return count of unread notifications."""
    query = db.query(func.count(models.Notification.id)).filter(models.Notification.is_read.is_(False))
    if user_id is not None:
        query = query.filter(models.Notification.user_id == user_id)
    if site_id is not None:
        query = query.filter(models.Notification.site_id == site_id)
    return query.scalar() or 0


def mark_notification_as_read(db: Session, notification_id: int, user_id: Optional[int] = None) -> Optional[models.Notification]:
    """Mark a single notification as read, verifying user ownership if scoped."""
    query = db.query(models.Notification).filter(models.Notification.id == notification_id)
    if user_id is not None:
        query = query.filter(models.Notification.user_id == user_id)
    notif = query.first()
    if not notif:
        return None

    notif.is_read = True
    db.commit()
    db.refresh(notif)
    return notif


def mark_notification_as_unread(db: Session, notification_id: int, user_id: Optional[int] = None) -> Optional[models.Notification]:
    """Mark a single notification as unread, verifying user ownership if scoped."""
    query = db.query(models.Notification).filter(models.Notification.id == notification_id)
    if user_id is not None:
        query = query.filter(models.Notification.user_id == user_id)
    notif = query.first()
    if not notif:
        return None

    notif.is_read = False
    db.commit()
    db.refresh(notif)
    return notif


def mark_all_notifications_as_read(
    db: Session,
    site_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> schemas.MarkAllReadResponse:
    """Mark all unread notifications as read, optionally filtered by site and user."""
    query = db.query(models.Notification).filter(models.Notification.is_read.is_(False))
    if user_id is not None:
        query = query.filter(models.Notification.user_id == user_id)
    if site_id is not None:
        query = query.filter(models.Notification.site_id == site_id)

    unread_items = query.all()
    count = len(unread_items)
    for notif in unread_items:
        notif.is_read = True

    db.commit()
    unread_remaining = get_unread_count(db, user_id=user_id)
    return schemas.MarkAllReadResponse(marked_read=count, unread_count=unread_remaining)


def delete_notification(db: Session, notification_id: int, user_id: Optional[int] = None) -> bool:
    """Delete a single notification by ID, verifying user ownership if scoped."""
    query = db.query(models.Notification).filter(models.Notification.id == notification_id)
    if user_id is not None:
        query = query.filter(models.Notification.user_id == user_id)
    notif = query.first()
    if not notif:
        return False

    db.delete(notif)
    db.commit()
    return True
