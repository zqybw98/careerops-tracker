from datetime import date

from src.reminder_engine import generate_reminders


def test_does_not_generate_stale_follow_up_without_due_date() -> None:
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

    assert reminders == []


def test_action_needed_generates_today_action() -> None:
    applications = [
        {
            "id": 1,
            "company": "Example GmbH",
            "role": "QA Intern",
            "application_date": "2026-04-30",
            "status": "Action Needed",
            "follow_up_date": "",
        }
    ]

    reminders = generate_reminders(applications, today=date(2026, 5, 7))

    assert len(reminders) == 1
    assert reminders[0]["reason"] == "action_needed"
    assert reminders[0]["priority"] == "High"


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
            "status": "Waiting",
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
