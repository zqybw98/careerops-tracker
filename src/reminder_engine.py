from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.config_loader import ReminderRule, get_reminder_config
from src.models import CLOSED_STATUSES

REMINDER_CONFIG = get_reminder_config()
REMINDER_RULES = REMINDER_CONFIG["rules"]
PRIORITY_ORDER = REMINDER_CONFIG["priority_order"]


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

        follow_up_date = _parse_date(application.get("follow_up_date"))

        if status == "Action Needed":
            rule = REMINDER_RULES["action_needed"]
            reminders.append(
                _build_reminder(
                    application,
                    due_date=follow_up_date or current_date,
                    rule=rule,
                )
            )
            continue

        if follow_up_date:
            if follow_up_date <= current_date:
                rule = REMINDER_RULES["follow_up_due"]
                reminders.append(
                    _build_reminder(
                        application,
                        due_date=follow_up_date,
                        rule=rule,
                    )
                )
            continue

    return sorted(reminders, key=lambda item: (item["due_date"], PRIORITY_ORDER[item["priority"]]))


def _build_reminder(
    application: dict[str, Any],
    due_date: date,
    rule: ReminderRule,
) -> dict[str, Any]:
    return {
        "application_id": application.get("id"),
        "company": application.get("company", ""),
        "role": application.get("role", ""),
        "due_date": due_date.isoformat(),
        "priority": rule["priority"],
        "message": rule["message"],
        "reason": rule["reason"],
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
