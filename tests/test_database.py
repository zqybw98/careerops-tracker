import sqlite3
from pathlib import Path

import pytest
import src.database as database
from src.database import (
    MIGRATIONS_DIR,
    create_application,
    create_company_research_note,
    create_email_feedback,
    deduplicate_applications,
    get_application_events,
    get_applications,
    get_company_research_notes,
    get_email_feedback,
    init_db,
    preview_application_sync,
    sync_applications,
    update_application,
)


def _expected_migrations() -> list[tuple[int, str]]:
    return [(int(path.stem.split("_", 1)[0]), path.stem) for path in sorted(MIGRATIONS_DIR.glob("*.sql"))]


def _company_research_indexes(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA index_list(company_research_notes)").fetchall()}


def test_public_create_and_update_still_commit_events(tmp_path: Path) -> None:
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
        source="compatibility_test",
    )

    applications = get_applications(db_path)
    assert len(applications) == 1
    assert applications[0]["id"] == application_id
    assert applications[0]["company"] == "Example GmbH"
    events = get_application_events(application_id, db_path)
    assert events[0]["event_type"] == "application_created"
    assert events[0]["source"] == "compatibility_test"

    update_application(
        application_id,
        {
            **applications[0],
            "status": "Interview / Assessment",
            "next_action": "Prepare interview notes",
        },
        db_path=db_path,
        source="compatibility_test",
    )

    updated = get_applications(db_path)[0]
    assert updated["status"] == "Interview / Assessment"
    assert updated["next_action"] == "Prepare interview notes"
    update_events = get_application_events(application_id, db_path)
    assert any(event["event_type"] == "status_changed" for event in update_events)
    assert any(event["event_type"] == "next_action_changed" for event in update_events)
    assert all(event["source"] == "compatibility_test" for event in update_events)


def test_transaction_helpers_do_not_commit_caller_transaction(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    existing_id = create_application(
        {
            "company": "Existing GmbH",
            "role": "QA Engineer",
            "application_date": "2026-07-25",
            "status": "Applied",
        },
        db_path=db_path,
        source="seed",
    )

    with database.get_connection(db_path) as connection:
        connection.execute("BEGIN")
        created_id = database._create_application_in_transaction(
            connection,
            {
                "company": "Rolled Back GmbH",
                "role": "Test Engineer",
                "application_date": "2026-07-25",
                "status": "Applied",
            },
            source="capture_test",
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM applications WHERE id = ?",
                (created_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                """
                SELECT COUNT(*)
                FROM application_events
                WHERE application_id = ?
                  AND source = 'capture_test'
                """,
                (created_id,),
            ).fetchone()[0]
            == 1
        )
        connection.rollback()

    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM applications WHERE company = 'Rolled Back GmbH'").fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM application_events WHERE source = 'capture_test'").fetchone()[0]
            == 0
        )

    existing = get_applications(db_path)[0]
    with database.get_connection(db_path) as connection:
        connection.execute("BEGIN")
        database._update_application_in_transaction(
            connection,
            existing_id,
            {
                **existing,
                "status": "Waiting",
                "next_action": "Wait",
            },
            source="capture_test",
        )
        assert (
            connection.execute(
                "SELECT status FROM applications WHERE id = ?",
                (existing_id,),
            ).fetchone()[0]
            == "Waiting"
        )
        assert (
            connection.execute(
                """
                SELECT COUNT(*)
                FROM application_events
                WHERE application_id = ?
                  AND source = 'capture_test'
                """,
                (existing_id,),
            ).fetchone()[0]
            >= 1
        )
        connection.rollback()

    persisted = get_applications(db_path)[0]
    persisted_events = get_application_events(existing_id, db_path)
    assert persisted["status"] == "Applied"
    assert not any(event["source"] == "capture_test" for event in persisted_events)


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
            "next_action": "Capture lessons learned",
            "follow_up_date": "2026-05-14",
        },
        db_path=db_path,
    )

    updated = get_applications(db_path)[0]
    events = get_application_events(application_id, db_path)

    assert updated["rejection_reason"] == "Position closed after application review."
    assert updated["next_action"] == "No action"
    assert updated["follow_up_date"] == ""
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
    assert versions == [version for version, _ in _expected_migrations()]


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

    assert {
        "applications",
        "application_events",
        "capture_requests",
        "company_research_notes",
        "email_feedback",
        "schema_version",
    } <= tables
    assert "rejection_reason" in application_columns
    assert versions == _expected_migrations()


def test_init_db_creates_capture_requests_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"

    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {
            row[1]: {
                "type": row[2],
                "not_null": row[3],
                "primary_key": row[5],
            }
            for row in connection.execute("PRAGMA table_info(capture_requests)").fetchall()
        }
        version_count = connection.execute("SELECT COUNT(*) FROM schema_version WHERE version = 7").fetchone()[0]

    assert set(columns) == {
        "client_request_id",
        "payload_sha256",
        "application_id",
        "result",
        "created_at",
    }
    assert columns["client_request_id"]["type"] == "TEXT"
    assert columns["client_request_id"]["primary_key"] == 1
    assert all(columns[name]["not_null"] == 1 for name in columns if name != "client_request_id")
    assert version_count == 1


def test_init_db_applies_capture_migration_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"

    init_db(db_path)
    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        table_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'capture_requests'
            """
        ).fetchone()[0]
        version_count = connection.execute("SELECT COUNT(*) FROM schema_version WHERE version = 7").fetchone()[0]

    assert table_count == 1
    assert version_count == 1


def test_init_db_creates_company_research_table_and_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"

    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
              AND name = 'company_research_notes'
            """
        ).fetchone()
        indexes = _company_research_indexes(connection)
        version = connection.execute("SELECT COUNT(*) FROM schema_version WHERE version = 6").fetchone()[0]

    assert table is not None
    assert {
        "idx_company_research_checked_at",
        "idx_company_research_company",
    } <= indexes
    assert version == 1


def test_init_db_upgrades_schema_version_5_to_6(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM schema_version WHERE version = 6")
        connection.execute("DROP TABLE company_research_notes")

    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        indexes = _company_research_indexes(connection)
        version_count = connection.execute("SELECT COUNT(*) FROM schema_version WHERE version = 6").fetchone()[0]

    assert {
        "idx_company_research_checked_at",
        "idx_company_research_company",
    } <= indexes
    assert version_count == 1


@pytest.mark.parametrize(
    "missing_index",
    ["idx_company_research_company", "idx_company_research_checked_at"],
)
def test_init_db_repairs_incomplete_company_research_indexes(
    tmp_path: Path,
    missing_index: str,
) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM schema_version WHERE version = 6")
        connection.execute(f"DROP INDEX {missing_index}")

    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        indexes = _company_research_indexes(connection)
        version_count = connection.execute("SELECT COUNT(*) FROM schema_version WHERE version = 6").fetchone()[0]

    assert {
        "idx_company_research_checked_at",
        "idx_company_research_company",
    } <= indexes
    assert version_count == 1


def test_init_db_keeps_company_research_migration_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"

    init_db(db_path)
    init_db(db_path)

    with sqlite3.connect(db_path) as connection:
        indexes = _company_research_indexes(connection)
        version_count = connection.execute("SELECT COUNT(*) FROM schema_version WHERE version = 6").fetchone()[0]

    assert {
        "idx_company_research_checked_at",
        "idx_company_research_company",
    } <= indexes
    assert version_count == 1


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

    assert versions == _expected_migrations()
    assert rejection_columns == ["rejection_reason"]
    assert feedback_table is not None


def test_create_and_read_company_research_note_without_changing_applications(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    application_id = create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer",
            "application_date": "2026-07-18",
            "status": "Applied",
        },
        db_path=db_path,
    )

    note_id = create_company_research_note(
        {
            "company": "Siemens AG",
            "checked_at": "2026-07-18",
            "decision": "Review later",
            "relevant_roles": "QA Engineer; Technical Support",
            "skipped_roles": "Senior Architect",
            "summary": "No suitable junior opening today.",
            "notes": "Check the careers page again next month.",
            "source_link": "https://jobs.siemens.com/",
        },
        db_path=db_path,
    )

    research_notes = get_company_research_notes(
        company_query="siemens",
        db_path=db_path,
    )
    applications = get_applications(db_path)

    assert len(research_notes) == 1
    assert research_notes[0]["id"] == note_id
    assert research_notes[0]["company"] == "Siemens AG"
    assert research_notes[0]["checked_at"] == "2026-07-18"
    assert research_notes[0]["decision"] == "Review later"
    assert research_notes[0]["relevant_roles"] == "QA Engineer; Technical Support"
    assert research_notes[0]["source_link"] == "https://jobs.siemens.com/"
    assert len(applications) == 1
    assert applications[0]["id"] == application_id
    assert applications[0]["company"] == "Example GmbH"


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
            "predicted_status": "Waiting",
            "corrected_category": "Interview Invitation",
            "corrected_status": "Interview / Assessment",
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
