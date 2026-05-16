from datetime import date

from src.reminder_actions import build_pending_action_payload
from src.reminder_engine import generate_reminders


def test_snooze_pending_action_sets_future_follow_up() -> None:
    application = {
        "id": 1,
        "company": "SAP",
        "role": "QA Engineer",
        "application_date": "2026-04-20",
        "status": "Applied",
        "next_action": "Follow up with recruiter.",
        "follow_up_date": "",
    }
    reminder = {
        "application_id": 1,
        "message": "No update after 7+ days. Consider a polite follow-up.",
    }

    payload = build_pending_action_payload(application, reminder, "snooze_3", today=date(2026, 5, 7))

    assert payload["follow_up_date"] == "2026-05-10"
    assert payload["next_action"] == "Follow up with recruiter."
    assert generate_reminders([{**application, **payload}], today=date(2026, 5, 7)) == []


def test_mark_done_records_completion_and_schedules_next_review() -> None:
    application = {
        "id": 1,
        "company": "Bosch",
        "role": "Automation Intern",
        "application_date": "2026-04-20",
        "status": "Applied",
        "next_action": "",
        "follow_up_date": "",
    }
    reminder = {
        "application_id": 1,
        "message": "No update after 7+ days. Consider a polite follow-up.",
    }

    payload = build_pending_action_payload(application, reminder, "mark_done", today=date(2026, 5, 7))

    assert payload["follow_up_date"] == "2026-05-14"
    assert payload["next_action"] == (
        "Completed on 2026-05-07. Review again on 2026-05-14 if there is no update. "
        "Last action: No update after 7+ days. Consider a polite follow-up."
    )
    assert generate_reminders([{**application, **payload}], today=date(2026, 5, 7)) == []
