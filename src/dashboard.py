from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


def build_summary(applications: list[dict[str, Any]]) -> dict[str, int]:
    today = date.today()
    week_start = today - timedelta(days=7)

    return {
        "total": len(applications),
        "applied_this_week": sum(
            1
            for item in applications
            if _parse_date(item.get("application_date"))
            and _parse_date(item.get("application_date")) >= week_start
        ),
        "waiting": sum(
            1
            for item in applications
            if item.get("status") in {"Applied", "Confirmation Received", "No Response"}
        ),
        "interviews": sum(1 for item in applications if item.get("status") == "Interview Scheduled"),
        "assessments": sum(1 for item in applications if item.get("status") == "Assessment"),
        "rejections": sum(1 for item in applications if item.get("status") == "Rejected"),
    }


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None

