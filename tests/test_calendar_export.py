from datetime import UTC, datetime

from src.calendar_export import (
    build_calendar_items,
    build_calendar_text_block,
    build_ics_calendar,
    calendar_items_to_rows,
)


def test_builds_calendar_items_for_interview_assessment_and_follow_up() -> None:
    applications = [
        {
            "id": 1,
            "company": "SAP",
            "role": "QA Engineer",
            "location": "Berlin",
            "status": "Interview Scheduled",
            "follow_up_date": "2026-05-20",
            "next_action": "Confirm logistics",
        },
        {
            "id": 2,
            "company": "Bosch",
            "role": "Automation Intern",
            "status": "Assessment",
            "follow_up_date": "2026-05-18",
        },
        {
            "id": 3,
            "company": "DILAX",
            "role": "Testing Assistant",
            "status": "Applied",
            "follow_up_date": "2026-05-21",
        },
        {
            "id": 4,
            "company": "Closed GmbH",
            "role": "QA",
            "status": "Rejected",
            "follow_up_date": "2026-05-22",
        },
    ]

    items = build_calendar_items(applications)

    assert [item.event_type for item in items] == ["Assessment", "Interview", "Follow-up"]
    assert [item.company for item in items] == ["Bosch", "SAP", "DILAX"]


def test_builds_valid_all_day_ics_calendar() -> None:
    items = build_calendar_items(
        [
            {
                "id": 1,
                "company": "SAP, Germany",
                "role": "QA Engineer",
                "location": "Berlin",
                "status": "Interview Scheduled",
                "follow_up_date": "2026-05-20",
                "next_action": "Prepare notes; confirm logistics",
                "contact": "Lisa <lisa@sap.com>",
            }
        ]
    )

    ics = build_ics_calendar(
        items,
        generated_at=datetime(2026, 5, 14, 8, 30, tzinfo=UTC),
    )

    assert "BEGIN:VCALENDAR" in ics
    assert "BEGIN:VEVENT" in ics
    assert "DTSTAMP:20260514T083000Z" in ics
    assert "DTSTART;VALUE=DATE:20260520" in ics
    assert "DTEND;VALUE=DATE:20260521" in ics
    assert "SUMMARY:Interview: SAP\\, Germany - QA Engineer" in ics
    assert "Prepare notes\\; confirm logistics" in ics


def test_calendar_text_block_and_rows_are_human_readable() -> None:
    items = build_calendar_items(
        [
            {
                "id": 5,
                "company": "MHP",
                "role": "Data Analyst",
                "location": "Ludwigsburg",
                "status": "Applied",
                "follow_up_date": "2026-05-25",
            }
        ]
    )

    text_block = build_calendar_text_block(items)
    rows = calendar_items_to_rows(items)

    assert "2026-05-25 | Follow-up | MHP - Data Analyst | Ludwigsburg" in text_block
    assert rows == [
        {
            "application_id": 5,
            "event_date": "2026-05-25",
            "event_type": "Follow-up",
            "company": "MHP",
            "role": "Data Analyst",
            "location": "Ludwigsburg",
            "summary": "Follow up: MHP - Data Analyst",
        }
    ]
