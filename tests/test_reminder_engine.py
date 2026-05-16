from datetime import date

from src.reminder_engine import generate_reminders


def test_generates_follow_up_after_seven_days() -> None:
    applications = [
        {
            "id": 1,
            "company": "Example GmbH",
            "role": "QA Intern",
            "application_date": "2026-04-30",
            "status": "Applied",
            "follow_up_date": "",
        }
    ]

    reminders = generate_reminders(applications, today=date(2026, 5, 7))

    assert len(reminders) == 1
    assert reminders[0]["reason"] == "weekly_follow_up"
    assert reminders[0]["priority"] == "Medium"


def test_closed_statuses_do_not_generate_reminders() -> None:
    applications = [
        {
            "id": 1,
            "company": "Example GmbH",
            "role": "QA Intern",
            "application_date": "2026-04-01",
            "status": "Rejected",
            "follow_up_date": "",
        }
    ]

    reminders = generate_reminders(applications, today=date(2026, 5, 7))

    assert reminders == []


def test_due_follow_up_date_has_high_priority() -> None:
    applications = [
        {
            "id": 1,
            "company": "Example GmbH",
            "role": "QA Intern",
            "application_date": "2026-05-01",
            "status": "Confirmation Received",
            "follow_up_date": "2026-05-07",
        }
    ]

    reminders = generate_reminders(applications, today=date(2026, 5, 7))

    assert len(reminders) == 1
    assert reminders[0]["reason"] == "follow_up_date"
    assert reminders[0]["priority"] == "High"


def test_future_follow_up_date_is_not_pending_yet() -> None:
    applications = [
        {
            "id": 1,
            "company": "Example GmbH",
            "role": "QA Intern",
            "application_date": "2026-04-01",
            "status": "Applied",
            "follow_up_date": "2026-05-10",
        }
    ]

    reminders = generate_reminders(applications, today=date(2026, 5, 7))

    assert reminders == []
