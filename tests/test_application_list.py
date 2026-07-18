from __future__ import annotations

from datetime import date
from typing import Any

from src.application_list import (
    build_create_application_payload,
    build_edit_application_payload,
    build_list_rows,
    count_quick_filters,
    filter_application_list,
    sort_application_list,
)


def _application(**overrides: Any) -> dict[str, Any]:
    application = {
        "id": 1,
        "company": "SAP",
        "role": "Quality Engineer",
        "location": "Berlin, Germany",
        "application_date": "2026-07-01",
        "status": "Applied",
        "source_link": "https://jobs.sap.com",
        "contact": "",
        "notes": "",
        "rejection_reason": "",
        "next_action": "Wait",
        "follow_up_date": "",
        "created_at": "2026-07-01T10:00:00+00:00",
        "updated_at": "2026-07-01T10:00:00+00:00",
    }
    application.update(overrides)
    return application


def test_search_matches_company_and_role() -> None:
    applications = [
        _application(company="SAP", role="Quality Engineer"),
        _application(id=2, company="Bosch", role="Automation Tester"),
    ]

    assert [item["company"] for item in filter_application_list(applications, search_query="sap")] == ["SAP"]
    assert [item["company"] for item in filter_application_list(applications, search_query="automation")] == ["Bosch"]


def test_status_and_location_filters_are_combined() -> None:
    applications = [
        _application(company="SAP", status="Waiting", location="Berlin, Germany"),
        _application(id=2, company="Bosch", status="Waiting", location="Stuttgart, Germany"),
        _application(id=3, company="Tesla", status="Rejected", location="Berlin, Germany"),
    ]

    filtered = filter_application_list(
        applications,
        statuses=["Waiting"],
        location="Berlin, Germany",
    )

    assert [item["company"] for item in filtered] == ["SAP"]


def test_quick_filters_use_the_existing_status_model() -> None:
    applications = [
        _application(company="Applied", status="Applied"),
        _application(id=2, company="Waiting", status="Waiting"),
        _application(id=3, company="Action", status="Action Needed"),
        _application(id=4, company="Interview", status="Interview / Assessment"),
        _application(id=5, company="Rejected", status="Rejected"),
    ]

    assert [item["company"] for item in filter_application_list(applications, quick_filter="active")] == [
        "Applied",
        "Waiting",
        "Action",
        "Interview",
    ]
    assert [item["company"] for item in filter_application_list(applications, quick_filter="interview")] == [
        "Interview"
    ]
    assert [item["company"] for item in filter_application_list(applications, quick_filter="waiting")] == ["Waiting"]
    assert [item["company"] for item in filter_application_list(applications, quick_filter="rejected")] == ["Rejected"]
    assert count_quick_filters(applications) == {
        "all": 5,
        "active": 4,
        "interview": 1,
        "waiting": 1,
        "rejected": 1,
    }


def test_default_sort_puts_latest_application_first() -> None:
    applications = [
        _application(id=1, company="Older", application_date="2026-06-01"),
        _application(id=2, company="Newest", application_date="2026-07-10"),
        _application(id=3, company="Same day newer id", application_date="2026-07-10"),
    ]

    assert [item["company"] for item in sort_application_list(applications)] == [
        "Same day newer id",
        "Newest",
        "Older",
    ]


def test_list_rows_hide_internal_and_long_detail_fields() -> None:
    rows = build_list_rows([_application()], include_source=False)

    assert rows == [
        {
            "Company": "SAP",
            "Role": "Quality Engineer",
            "Location": "Berlin, Germany",
            "Status": "Applied",
            "Applied": "2026-07-01",
            "Follow-up": "",
        }
    ]
    assert "id" not in rows[0]
    assert "Notes" not in rows[0]
    assert "Next Action" not in rows[0]


def test_create_payload_contains_only_application_fields() -> None:
    payload = build_create_application_payload(
        company=" SAP ",
        role=" Quality Engineer ",
        location="Berlin, Germany",
        status="Applied",
        application_date=date(2026, 7, 18),
        source_link="https://jobs.sap.com",
        contact="recruiter@sap.com",
        follow_up_date=date(2026, 7, 25),
        next_action="Wait",
        notes="Tailored CV used.",
        rejection_reason="",
    )

    assert payload == {
        "company": "SAP",
        "role": "Quality Engineer",
        "location": "Berlin, Germany",
        "application_date": "2026-07-18",
        "status": "Applied",
        "source_link": "https://jobs.sap.com",
        "contact": "recruiter@sap.com",
        "notes": "Tailored CV used.",
        "rejection_reason": "",
        "next_action": "Wait",
        "follow_up_date": "2026-07-25",
    }
    assert "id" not in payload


def test_edit_payload_preserves_identity_and_excludes_internal_id() -> None:
    existing = _application(id=42, company="SAP", role="Quality Engineer")

    payload = build_edit_application_payload(
        existing,
        status="Waiting",
        location="Walldorf, Germany",
        application_date=date(2026, 7, 1),
        follow_up_date=None,
        next_action="Wait for review",
        notes="Confirmation received.",
        source_link="https://jobs.sap.com/123",
        contact="talent@sap.com",
        rejection_reason="",
    )

    assert payload["company"] == "SAP"
    assert payload["role"] == "Quality Engineer"
    assert payload["status"] == "Waiting"
    assert payload["follow_up_date"] == ""
    assert payload["next_action"] == "Wait for review"
    assert "id" not in payload
