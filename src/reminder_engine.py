from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from src.models import CLOSED_STATUSES


def generate_reminders(
    applications: list[dict[str, Any]],
    today: date | None = None,
) -> list[dict[str, Any]]:
    current_date = today or date.today()
    reminders: list[dict[str, Any]] = []

    for application in applications:
        status = application.get("status", "")
        if status in CLOSED_STATUSES:
            continue

        application_date = _parse_date(application.get("application_date"))
        follow_up_date = _parse_date(application.get("follow_up_date"))

        if follow_up_date and follow_up_date <= current_date:
            reminders.append(
                _build_reminder(
                    application,
                    due_date=follow_up_date,
                    priority="High",
                    message="Follow-up date is due.",
                    reason="follow_up_date",
                )
            )
            continue

        if status == "Interview Scheduled":
            reminders.append(
                _build_reminder(
                    application,
                    due_date=current_date,
                    priority="High",
                    message="Prepare interview notes and confirm logistics.",
                    reason="interview_preparation",
                )
            )
            continue

        if status == "Assessment":
            due_date = follow_up_date or current_date + timedelta(days=2)
            reminders.append(
                _build_reminder(
                    application,
                    due_date=due_date,
                    priority="High",
                    message="Work on assessment and check the deadline.",
                    reason="assessment_deadline",
                )
            )
            continue

        if application_date and status in {"Applied", "Confirmation Received", "No Response"}:
            days_open = (current_date - application_date).days
            if days_open >= 14:
                reminders.append(
                    _build_reminder(
                        application,
                        due_date=current_date,
                        priority="Medium",
                        message="Application has been open for 14+ days. Consider follow-up or mark as no response.",
                        reason="stale_application",
                    )
                )
            elif days_open >= 7:
                reminders.append(
                    _build_reminder(
                        application,
                        due_date=current_date,
                        priority="Medium",
                        message="No update after 7+ days. Consider a polite follow-up.",
                        reason="weekly_follow_up",
                    )
                )

        if status == "Saved":
            reminders.append(
                _build_reminder(
                    application,
                    due_date=current_date,
                    priority="Low",
                    message="Saved role is not applied yet. Decide whether to apply.",
                    reason="saved_role",
                )
            )

    priority_order = {"High": 0, "Medium": 1, "Low": 2}
    return sorted(reminders, key=lambda item: (item["due_date"], priority_order[item["priority"]]))


def _build_reminder(
    application: dict[str, Any],
    due_date: date,
    priority: str,
    message: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "application_id": application.get("id"),
        "company": application.get("company", ""),
        "role": application.get("role", ""),
        "due_date": due_date.isoformat(),
        "priority": priority,
        "message": message,
        "reason": reason,
    }


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None
