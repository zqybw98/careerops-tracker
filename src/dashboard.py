from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

DASHBOARD_CLOSED_STATUSES = {"Rejected", "No Response"}


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
        if str(application.get("status") or "").strip() not in DASHBOARD_CLOSED_STATUSES
    ]


def build_summary(applications: list[dict[str, Any]]) -> dict[str, int]:
    today = date.today()
    week_start = today - timedelta(days=7)

    return {
        "total": len(applications),
        "applied_this_week": sum(1 for item in applications if _is_applied_this_week(item, week_start)),
        "waiting": sum(
            1 for item in applications if item.get("status") in {"Applied", "Confirmation Received", "No Response"}
        ),
        "interviews": sum(1 for item in applications if item.get("status") == "Interview Scheduled"),
        "assessments": sum(1 for item in applications if item.get("status") == "Assessment"),
        "rejections": sum(1 for item in applications if item.get("status") == "Rejected"),
    }


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
