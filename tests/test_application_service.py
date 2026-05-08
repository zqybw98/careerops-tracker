import sqlite3
from pathlib import Path

from src.database import (
    create_application,
    deduplicate_applications,
    get_application_events,
    get_applications,
    init_db,
    sync_applications,
    update_application,
)


def test_create_and_update_application(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)

    application_id = create_application(
        {
            "company": "Example GmbH",
            "role": "QA Automation Intern",
            "location": "Berlin",
            "application_date": "2026-05-07",
            "status": "Applied",
        },
        db_path=db_path,
    )

    applications = get_applications(db_path)
    assert len(applications) == 1
    assert applications[0]["id"] == application_id
    assert applications[0]["company"] == "Example GmbH"
    events = get_application_events(application_id, db_path)
    assert events[0]["event_type"] == "application_created"
    assert events[0]["source"] == "manual"

    update_application(
        application_id,
        {
            **applications[0],
            "status": "Interview Scheduled",
            "next_action": "Prepare interview notes",
        },
        db_path=db_path,
    )

    updated = get_applications(db_path)[0]
    assert updated["status"] == "Interview Scheduled"
    assert updated["next_action"] == "Prepare interview notes"
    update_events = get_application_events(application_id, db_path)
    assert any(event["event_type"] == "status_changed" for event in update_events)
    assert any(event["event_type"] == "next_action_changed" for event in update_events)


def test_rejection_reason_is_tracked_in_activity_log(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)

    application_id = create_application(
        {
            "company": "Example GmbH",
            "role": "QA Automation Intern",
            "application_date": "2026-05-07",
            "status": "Applied",
        },
        db_path=db_path,
    )

    update_application(
        application_id,
        {
            "company": "Example GmbH",
            "role": "QA Automation Intern",
            "application_date": "2026-05-07",
            "status": "Rejected",
            "rejection_reason": "Position closed after application review.",
        },
        db_path=db_path,
    )

    updated = get_applications(db_path)[0]
    events = get_application_events(application_id, db_path)

    assert updated["rejection_reason"] == "Position closed after application review."
    assert any(event["event_type"] == "rejection_reason_changed" for event in events)


def test_init_db_migrates_rejection_reason_column(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                location TEXT,
                application_date TEXT,
                status TEXT NOT NULL DEFAULT 'Applied',
                source_link TEXT,
                contact TEXT,
                notes TEXT,
                next_action TEXT,
                follow_up_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(applications)").fetchall()}

    assert "rejection_reason" in columns


def test_sync_applications_updates_existing_records(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    create_application(
        {
            "company": "SAP",
            "role": "QA Engineer",
            "application_date": "2026-04-30",
            "status": "Applied",
            "notes": "Submitted through career portal",
        },
        db_path=db_path,
    )

    result = sync_applications(
        [
            {
                "company": "SAP",
                "role": "QA Engineer",
                "application_date": "2026-04-30",
                "status": "Rejected",
                "notes": "Rejected after screening",
            },
            {
                "company": "DILAX",
                "role": "Student Assistant Software Testing",
                "application_date": "2026-04-29",
                "status": "Applied",
            },
        ],
        db_path=db_path,
        source="csv_import",
    )

    applications = get_applications(db_path)
    sap = next(item for item in applications if item["company"] == "SAP")

    assert result == {"created": 1, "updated": 1, "skipped": 0}
    assert len(applications) == 2
    assert sap["status"] == "Rejected"
    assert "Submitted through career portal" in sap["notes"]
    assert "Rejected after screening" in sap["notes"]
    events = get_application_events(sap["id"], db_path)
    status_events = [event for event in events if event["event_type"] == "status_changed"]
    assert status_events[0]["old_value"] == "Applied"
    assert status_events[0]["new_value"] == "Rejected"
    assert status_events[0]["source"] == "csv_import"


def test_sync_applications_skips_unchanged_records(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    payload = {
        "company": "HUMANOO",
        "role": "Junior QA Engineer",
        "application_date": "2026-04-29",
        "status": "Applied",
    }
    create_application(payload, db_path=db_path)

    result = sync_applications([payload], db_path=db_path)

    assert result == {"created": 0, "updated": 0, "skipped": 1}
    assert len(get_applications(db_path)) == 1


def test_deduplicate_applications_keeps_one_record(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    duplicate = {
        "company": "MBition",
        "role": "Working Student Test Automation",
        "application_date": "2026-04-29",
        "status": "Applied",
    }
    create_application({**duplicate, "notes": "First import"}, db_path=db_path)
    create_application({**duplicate, "notes": "Updated CSV import"}, db_path=db_path)

    removed = deduplicate_applications(db_path=db_path)
    applications = get_applications(db_path)

    assert removed == 1
    assert len(applications) == 1
    assert "First import" in applications[0]["notes"]
    assert "Updated CSV import" in applications[0]["notes"]
