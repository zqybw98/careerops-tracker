import sqlite3
from pathlib import Path

from src.database import (
    create_application,
    create_email_feedback,
    deduplicate_applications,
    get_application_events,
    get_applications,
    get_email_feedback,
    init_db,
    preview_application_sync,
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
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_version ORDER BY version")]

    assert "rejection_reason" in columns
    assert versions == [1, 2, 3, 4]


def test_init_db_records_versioned_migrations(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"

    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }
        application_columns = {row[1] for row in connection.execute("PRAGMA table_info(applications)").fetchall()}
        versions = connection.execute(
            """
            SELECT version, name
            FROM schema_version
            ORDER BY version
            """
        ).fetchall()

    assert {"applications", "application_events", "email_feedback", "schema_version"} <= tables
    assert "rejection_reason" in application_columns
    assert versions == [
        (1, "001_init"),
        (2, "002_add_rejection_reason"),
        (3, "003_add_email_feedback"),
        (4, "004_add_lookup_indexes"),
    ]


def test_init_db_creates_lookup_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"

    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        event_indexes = {row[1] for row in connection.execute("PRAGMA index_list(application_events)").fetchall()}
        feedback_indexes = {row[1] for row in connection.execute("PRAGMA index_list(email_feedback)").fetchall()}

    assert "idx_application_events_application_id" in event_indexes
    assert "idx_email_feedback_signature" in feedback_indexes


def test_init_db_baselines_existing_schema_without_rerunning_migrations(tmp_path: Path) -> None:
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
                rejection_reason TEXT,
                next_action TEXT,
                follow_up_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE application_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        versions = connection.execute(
            """
            SELECT version, name
            FROM schema_version
            ORDER BY version
            """
        ).fetchall()
        rejection_columns = [
            row[1]
            for row in connection.execute("PRAGMA table_info(applications)").fetchall()
            if row[1] == "rejection_reason"
        ]
        feedback_table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'email_feedback'
            """
        ).fetchone()

    assert versions == [
        (1, "001_init"),
        (2, "002_add_rejection_reason"),
        (3, "003_add_email_feedback"),
        (4, "004_add_lookup_indexes"),
    ]
    assert rejection_columns == ["rejection_reason"]
    assert feedback_table is not None


def test_create_and_read_email_feedback(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    application_id = create_application(
        {
            "company": "SAP",
            "role": "QA Engineer",
            "application_date": "2026-05-14",
            "status": "Applied",
        },
        db_path=db_path,
    )

    feedback_id = create_email_feedback(
        {
            "email_signature": "sap qa engineer interview",
            "subject": "Interview update",
            "predicted_category": "Application Confirmation",
            "predicted_status": "Confirmation Received",
            "corrected_category": "Interview Invitation",
            "corrected_status": "Interview Scheduled",
            "corrected_application_id": application_id,
            "corrected_company": "SAP",
            "corrected_role": "QA Engineer",
        },
        db_path=db_path,
    )

    feedback_rows = get_email_feedback(db_path)

    assert feedback_rows[0]["id"] == feedback_id
    assert feedback_rows[0]["corrected_category"] == "Interview Invitation"
    assert feedback_rows[0]["corrected_application_id"] == application_id


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


def test_preview_application_sync_groups_created_updated_and_unchanged(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    create_application(
        {
            "company": "SAP",
            "role": "QA Engineer",
            "application_date": "2026-04-30",
            "status": "Applied",
        },
        db_path=db_path,
    )
    create_application(
        {
            "company": "HUMANOO",
            "role": "Junior QA Engineer",
            "application_date": "2026-04-29",
            "status": "Applied",
        },
        db_path=db_path,
    )

    preview = preview_application_sync(
        [
            {
                "company": "SAP",
                "role": "QA Engineer",
                "application_date": "2026-04-30",
                "status": "Rejected",
                "rejection_reason": "No interview",
            },
            {
                "company": "HUMANOO",
                "role": "Junior QA Engineer",
                "application_date": "2026-04-29",
                "status": "Applied",
            },
            {
                "company": "DILAX",
                "role": "Student Assistant Software Testing",
                "application_date": "2026-04-29",
                "status": "Applied",
            },
        ],
        db_path=db_path,
    )

    assert preview.created == 1
    assert preview.updated == 1
    assert preview.unchanged == 1
    assert preview.skipped == 0

    updated_row = next(row for row in preview.rows if row.action == "Updated")
    assert updated_row.company == "SAP"
    assert {change.field for change in updated_row.field_changes} >= {"status", "rejection_reason"}
    assert all(application["company"] != "DILAX" for application in get_applications(db_path))


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
