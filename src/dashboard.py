from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from src.models import CLOSED_STATUSES, WAITING_PIPELINE_STATUSES


def filter_dashboard_applications(
    applications: list[dict[str, Any]],
    *,
    include_closed: bool = False,
) -> list[dict[str, Any]]:
    if include_closed:
        return list(applications)

    return [
        application
        for application in applications
        if str(application.get("status") or "").strip() not in CLOSED_STATUSES
    ]


def build_daily_dashboard_sections(
    applications: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> dict[str, list[dict[str, Any]]]:
    current_date = today or date.today()

    today_actions = [
        application for application in applications if _is_today_action_required(application, current_date)
    ]
    due_soon = [application for application in applications if _is_follow_up_due_soon(application, current_date)]
    waiting_pending = [
        application
        for application in applications
        if str(application.get("status") or "").strip() in WAITING_PIPELINE_STATUSES
    ]
    recent_rejections = [
        application for application in applications if str(application.get("status") or "").strip() == "Rejected"
    ]

    return {
        "today_actions": _sort_by_due_date(today_actions),
        "due_soon": _sort_by_due_date(due_soon),
        "waiting_pending": _sort_by_application_date(waiting_pending),
        "recent_rejections": _sort_recent(recent_rejections),
    }


def build_summary(applications: list[dict[str, Any]]) -> dict[str, int]:
    today = date.today()
    week_start = today - timedelta(days=7)

    return {
        "total": len(applications),
        "applied_this_week": sum(1 for item in applications if _is_applied_this_week(item, week_start)),
        "waiting": sum(1 for item in applications if item.get("status") in {"Applied", "Waiting"}),
        "interviews": sum(1 for item in applications if item.get("status") == "Interview / Assessment"),
        "assessments": sum(1 for item in applications if item.get("status") == "Interview / Assessment"),
        "rejections": sum(1 for item in applications if item.get("status") == "Rejected"),
    }


def _is_today_action_required(application: dict[str, Any], today: date) -> bool:
    status = str(application.get("status") or "").strip()
    if status in CLOSED_STATUSES:
        return False
    if status == "Action Needed":
        return True
    follow_up_date = _parse_date(application.get("follow_up_date"))
    return follow_up_date is not None and follow_up_date <= today


def _is_follow_up_due_soon(application: dict[str, Any], today: date) -> bool:
    status = str(application.get("status") or "").strip()
    if status in CLOSED_STATUSES or status == "Action Needed":
        return False
    follow_up_date = _parse_date(application.get("follow_up_date"))
    return follow_up_date is not None and today < follow_up_date <= today + timedelta(days=7)


def _sort_by_due_date(applications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        applications,
        key=lambda item: (_parse_date(item.get("follow_up_date")) or date.max, _updated_key(item)),
    )


def _sort_by_application_date(applications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        applications,
        key=lambda item: (_parse_date(item.get("application_date")) or date.min, _updated_key(item)),
        reverse=True,
    )


def _sort_recent(applications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(applications, key=_updated_key, reverse=True)


def _updated_key(application: dict[str, Any]) -> str:
    return str(application.get("updated_at") or application.get("application_date") or "")


def _is_applied_this_week(item: dict[str, Any], week_start: date) -> bool:
    application_date = _parse_date(item.get("application_date"))
    return application_date is not None and application_date >= week_start


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None
