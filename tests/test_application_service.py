from pathlib import Path

from src.database import create_application, get_applications, init_db, update_application


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

