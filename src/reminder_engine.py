from __future__ import annotations

from datetime import date, datetime, timedelta
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

        application_date = _parse_date(application.get("application_date"))
        follow_up_date = _parse_date(application.get("follow_up_date"))

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

        if status == "Interview Scheduled":
            rule = REMINDER_RULES["interview_preparation"]
            reminders.append(
                _build_reminder(
                    application,
                    due_date=current_date,
                    rule=rule,
                )
            )
            continue

        if status == "Assessment":
            rule = REMINDER_RULES["assessment_deadline"]
            due_date = follow_up_date or current_date + timedelta(days=rule.get("default_due_days", 2))
            reminders.append(
                _build_reminder(
                    application,
                    due_date=due_date,
                    rule=rule,
                )
            )
            continue

        stale_rule = REMINDER_RULES["stale_application"]
        weekly_rule = REMINDER_RULES["weekly_follow_up"]
        follow_up_statuses = set(stale_rule["statuses"])
        if application_date and status in follow_up_statuses:
            days_open = (current_date - application_date).days
            if days_open >= stale_rule["minimum_days_open"]:
                reminders.append(
                    _build_reminder(
                        application,
                        due_date=current_date,
                        rule=stale_rule,
                    )
                )
            elif days_open >= weekly_rule["minimum_days_open"]:
                reminders.append(
                    _build_reminder(
                        application,
                        due_date=current_date,
                        rule=weekly_rule,
                    )
                )

        if status == "Saved":
            rule = REMINDER_RULES["saved_role"]
            reminders.append(
                _build_reminder(
                    application,
                    due_date=current_date,
                    rule=rule,
                )
            )

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
