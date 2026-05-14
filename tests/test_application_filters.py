from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from src.application_filters import (
    ARCHIVED_NEXT_ACTION,
    NO_RESPONSE_NEXT_ACTION,
    build_bulk_update_payload,
    filter_applications,
    is_stale_application,
)


def _application(**overrides: Any) -> dict[str, Any]:
    application = {
        "id": 1,
        "company": "SAP",
        "role": "QA Engineer",
        "location": "Berlin",
        "application_date": "2026-05-01",
        "status": "Applied",
        "source_link": "https://jobs.sap.com",
        "contact": "recruiter@sap.com",
        "notes": "",
        "rejection_reason": "",
        "next_action": "",
        "follow_up_date": "",
    }
    application.update(overrides)
    return application


def test_filters_by_company_role_source_and_status() -> None:
    applications = [
        _application(company="SAP", role="Quality Engineer", source_link="https://jobs.sap.com"),
        _application(id=2, company="Bosch", role="Automation Tester", contact="talent@bosch.com", status="Rejected"),
    ]

    filtered = filter_applications(
        applications,
        statuses=["Applied"],
        company_query="quality",
        source_query="sap.com",
    )

    assert [application["company"] for application in filtered] == ["SAP"]


def test_filters_by_application_date_range() -> None:
    applications = [
        _application(company="Early", application_date="2026-04-30"),
        _application(id=2, company="Inside", application_date="2026-05-02"),
        _application(id=3, company="Late", application_date="2026-05-10"),
    ]

    filtered = filter_applications(
        applications,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 5),
    )

    assert [application["company"] for application in filtered] == ["Inside"]


def test_stale_only_uses_due_follow_up_or_waiting_rules() -> None:
    applications = [
        _application(company="Due", application_date="2026-05-10", follow_up_date="2026-05-14"),
        _application(id=2, company="Old", application_date="2026-04-20"),
        _application(id=3, company="Closed", application_date="2026-04-20", status="No Response"),
        _application(id=4, company="Fresh", application_date="2026-05-10"),
    ]

    filtered = filter_applications(applications, stale_only=True, today=date(2026, 5, 14))

    assert [application["company"] for application in filtered] == ["Due", "Old"]
    assert is_stale_application(applications[2], today=date(2026, 5, 14)) is False


def test_bulk_archive_marks_record_inactive() -> None:
    payload = build_bulk_update_payload(_application(status="Applied", follow_up_date="2026-05-15"), "archive")

    assert payload["status"] == "No Response"
    assert payload["next_action"] == ARCHIVED_NEXT_ACTION
    assert payload["follow_up_date"] == ""


def test_bulk_mark_no_response_clears_follow_up() -> None:
    payload = build_bulk_update_payload(
        _application(status="Applied", follow_up_date="2026-05-15"),
        "mark_no_response",
    )

    assert payload["status"] == "No Response"
    assert payload["next_action"] == NO_RESPONSE_NEXT_ACTION
    assert payload["follow_up_date"] == ""


def test_bulk_set_follow_up_requires_date_and_preserves_existing_action() -> None:
    application = _application(next_action="Prepare message")

    payload = build_bulk_update_payload(application, "set_follow_up", follow_up_date=date(2026, 5, 21))

    assert payload["follow_up_date"] == "2026-05-21"
    assert payload["next_action"] == "Prepare message"


def test_bulk_set_follow_up_requires_target_date() -> None:
    with pytest.raises(ValueError, match="follow_up_date is required"):
        build_bulk_update_payload(_application(), "set_follow_up")
