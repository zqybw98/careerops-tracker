from pathlib import Path

from src.database import (
    create_application,
    deduplicate_applications,
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
    )

    applications = get_applications(db_path)
    sap = next(item for item in applications if item["company"] == "SAP")

    assert result == {"created": 1, "updated": 1, "skipped": 0}
    assert len(applications) == 2
    assert sap["status"] == "Rejected"
    assert "Submitted through career portal" in sap["notes"]
    assert "Rejected after screening" in sap["notes"]


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
