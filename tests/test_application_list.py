from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any

import src.application_list as application_list
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


def test_company_suggestions_are_empty_without_applications() -> None:
    assert application_list.build_company_suggestions([]) == []


def test_company_suggestions_are_clean_deduplicated_and_stably_sorted() -> None:
    applications = [
        _application(company="  SAP  SE "),
        _application(id=2, company="sap se"),
        _application(id=3, company="Bosch"),
        _application(id=4, company=""),
        _application(id=5, company=None),
    ]

    assert application_list.build_company_suggestions(applications) == ["Bosch", "SAP SE"]


def test_company_suggestions_keep_a_custom_current_value_and_blank_option() -> None:
    applications = [_application(company="SAP")]

    assert application_list.build_company_suggestions(
        applications,
        preferred=" New  Company GmbH ",
        include_blank=True,
    ) == ["", "New Company GmbH", "SAP"]


def test_location_suggestions_merge_defaults_history_and_current_value() -> None:
    applications = [
        _application(location="  Berlin,  Germany "),
        _application(id=2, location="berlin, germany"),
        _application(id=3, location="Dresden, Germany"),
        _application(id=4, location=""),
        _application(id=5, location=None),
    ]

    options = application_list.build_location_suggestions(
        applications,
        preferred="Zurich, Switzerland",
        include_blank=True,
    )

    assert options[0] == ""
    assert "Berlin, Germany" in options
    assert "Dresden, Germany" in options
    assert "Remote, Germany" in options
    assert "Zurich, Switzerland" in options
    assert sum(option.casefold() == "berlin, germany" for option in options) == 1
    assert options[1:] == sorted(options[1:], key=str.casefold)


def test_suggestion_builders_do_not_modify_application_data() -> None:
    applications = [_application(company="SAP", location="Walldorf, Germany")]
    original = deepcopy(applications)

    application_list.build_company_suggestions(applications, preferred="Bosch")
    application_list.build_location_suggestions(applications, preferred="Berlin, Germany")

    assert applications == original


def test_custom_suggestion_values_enter_create_payload_unchanged() -> None:
    payload = build_create_application_payload(
        company="New Company GmbH",
        role="Support Engineer",
        location="Zurich, Switzerland",
        status="Applied",
        application_date=date(2026, 7, 18),
    )

    assert payload["company"] == "New Company GmbH"
    assert payload["location"] == "Zurich, Switzerland"
