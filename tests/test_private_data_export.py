import csv
import json
import sqlite3
from pathlib import Path

import pytest
from src.database import create_application, create_email_feedback, init_db
from src.private_data_export import ExportPolicyError, export_private_data


def _seed_database(db_path: Path) -> None:
    init_db(db_path)
    application_id = create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer",
            "location": "Berlin",
            "application_date": "2026-07-15",
            "status": "Waiting",
            "source_link": "https://example.com/jobs/qa",
            "contact": "Recruiting <jobs@example.com>",
            "notes": "Application confirmation received.",
            "next_action": "Wait",
        },
        db_path=db_path,
    )
    create_email_feedback(
        {
            "email_signature": "example qa confirmation",
            "subject": "Application received",
            "predicted_category": "Application Confirmation",
            "predicted_status": "Waiting",
            "corrected_category": "Application Confirmation",
            "corrected_status": "Waiting",
            "corrected_application_id": application_id,
            "corrected_company": "Example GmbH",
            "corrected_role": "QA Engineer",
        },
        db_path=db_path,
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_export_writes_only_approved_files_and_manifest(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    destination = tmp_path / "private-data"
    _seed_database(db_path)

    before = db_path.read_bytes()
    result = export_private_data(db_path, destination)

    assert db_path.read_bytes() == before
    assert {path.relative_to(destination).as_posix() for path in result.files} == {
        "exports/application_events.csv",
        "exports/applications.csv",
        "exports/company_research_notes.csv",
        "exports/contacts.csv",
        "exports/email_feedback.csv",
        "snapshot/careerops.sql",
        "sync_manifest.json",
    }
    assert not any(path.suffix == ".db" for path in destination.rglob("*"))

    application_rows = _read_csv(destination / "exports" / "applications.csv")
    assert application_rows[0]["company"] == "Example GmbH"
    assert "email_body" not in application_rows[0]
    assert "token" not in application_rows[0]
    assert "attachment_path" not in application_rows[0]

    manifest = json.loads((destination / "sync_manifest.json").read_text(encoding="utf-8"))
    assert "exported_at" not in manifest
    assert "source_path" not in manifest
    assert manifest["row_counts"]["applications"] == 1
    assert manifest["row_counts"]["company_research_notes"] == 0
    assert manifest["fingerprint"] == result.fingerprint


def test_export_is_byte_identical_when_data_does_not_change(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    first = tmp_path / "first"
    second = tmp_path / "second"
    _seed_database(db_path)

    first_result = export_private_data(db_path, first)
    second_result = export_private_data(db_path, second)

    first_files = {path.relative_to(first).as_posix(): path.read_bytes() for path in first_result.files}
    second_files = {path.relative_to(second).as_posix(): path.read_bytes() for path in second_result.files}
    assert first_files == second_files
    assert first_result.fingerprint == second_result.fingerprint


def test_export_sorts_rows_by_primary_key(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    destination = tmp_path / "private-data"
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        now = "2026-07-15T10:00:00+00:00"
        connection.execute(
            """
            INSERT INTO applications (
                id, company, role, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (20, "Second GmbH", "Second Role", "Applied", now, now),
        )
        connection.execute(
            """
            INSERT INTO applications (
                id, company, role, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (10, "First GmbH", "First Role", "Applied", now, now),
        )

    export_private_data(db_path, destination)

    rows = _read_csv(destination / "exports" / "applications.csv")
    assert [row["id"] for row in rows] == ["10", "20"]


def test_export_includes_optional_company_research_table_when_present(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    destination = tmp_path / "private-data"
    _seed_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS company_research_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                decision TEXT,
                relevant_roles TEXT,
                skipped_roles TEXT,
                summary TEXT,
                notes TEXT,
                source_link TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO company_research_notes (
                company, checked_at, decision, relevant_roles, skipped_roles,
                summary, notes, source_link, created_at, updated_at
            ) VALUES (
                'Example GmbH', '2026-07-15', 'Monitor', 'QA Engineer',
                'Senior Sales', 'One suitable role', 'Checked careers page',
                'https://example.com/careers', '2026-07-15T10:00:00+00:00',
                '2026-07-15T10:00:00+00:00'
            );
            """
        )

    export_private_data(db_path, destination)

    rows = _read_csv(destination / "exports" / "company_research_notes.csv")
    assert rows[0]["company"] == "Example GmbH"
    sql_dump = (destination / "snapshot" / "careerops.sql").read_text(encoding="utf-8")
    assert "company_research_notes" in sql_dump
    assert "Checked careers page" in sql_dump


def test_export_rejects_unapproved_columns_before_writing(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    destination = tmp_path / "private-data"
    _seed_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("ALTER TABLE applications ADD COLUMN secret_token TEXT")
        connection.execute("UPDATE applications SET secret_token = 'do-not-export'")

    with pytest.raises(ExportPolicyError, match="unapproved columns"):
        export_private_data(db_path, destination)

    assert not destination.exists()


def test_export_sql_contains_only_approved_business_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    destination = tmp_path / "private-data"
    _seed_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE local_secrets (token TEXT)")
        connection.execute("INSERT INTO local_secrets VALUES ('never-export-this')")

    export_private_data(db_path, destination)

    sql_dump = (destination / "snapshot" / "careerops.sql").read_text(encoding="utf-8")
    assert "applications" in sql_dump
    assert "local_secrets" not in sql_dump
    assert "never-export-this" not in sql_dump


def test_export_excludes_internal_capture_requests_data(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    destination = tmp_path / "private-data"
    _seed_database(db_path)
    synthetic_request_id = "6fbe432a-f4a7-4d93-94bd-9cd5885aa523"
    synthetic_hash = "synthetic-payload-hash-do-not-export"
    token_like_value = "synthetic-capture-token-do-not-export"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO capture_requests (
                client_request_id,
                payload_sha256,
                application_id,
                result,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                synthetic_request_id,
                synthetic_hash,
                1,
                token_like_value,
                "2026-07-25T10:00:00+00:00",
            ),
        )

    result = export_private_data(db_path, destination)

    relative_files = {path.relative_to(destination).as_posix() for path in result.files}
    assert not any("capture_requests" in path for path in relative_files)
    exported_text = "\n".join(path.read_text(encoding="utf-8") for path in result.files)
    assert "client_request_id" not in exported_text
    assert synthetic_request_id not in exported_text
    assert synthetic_hash not in exported_text
    assert token_like_value not in exported_text

    manifest = json.loads((destination / "sync_manifest.json").read_text(encoding="utf-8"))
    assert "capture_requests" not in manifest["tables"]
    assert manifest["row_counts"]["applications"] == 1
