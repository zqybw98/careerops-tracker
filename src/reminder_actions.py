from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Literal

from src.models import APPLICATION_COLUMNS

PendingAction = Literal["mark_done", "snooze_3", "snooze_7"]

SNOOZE_DAYS = {
    "snooze_3": 3,
    "snooze_7": 7,
}


def build_pending_action_payload(
    application: dict[str, Any],
    reminder: dict[str, Any],
    action: PendingAction,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    current_date = today or date.today()
    payload = {column: application.get(column, "") for column in APPLICATION_COLUMNS}
    reminder_message = str(reminder.get("message") or application.get("next_action") or "Review pending action")

    if action == "mark_done":
        next_review_date = current_date + timedelta(days=7)
        payload["next_action"] = (
            f"Completed on {current_date.isoformat()}. "
            f"Review again on {next_review_date.isoformat()} if there is no update. Last action: {reminder_message}"
        )
        payload["follow_up_date"] = next_review_date.isoformat()
        return payload

    if action in SNOOZE_DAYS:
        follow_up_date = current_date + timedelta(days=SNOOZE_DAYS[action])
        payload["follow_up_date"] = follow_up_date.isoformat()
        if not str(payload.get("next_action", "")).strip():
            payload["next_action"] = reminder_message
        return payload

    raise ValueError(f"Unsupported pending action: {action}")
