from datetime import date

from src.analytics import (
    build_applications_per_month,
    build_average_waiting_days_by_company,
    build_channel_role_type_matrix,
    build_follow_up_effectiveness,
    build_interview_conversion_by_role_type,
    build_interview_to_offer_funnel,
    build_pipeline_health,
    build_rejection_reason_breakdown,
    build_response_rate_by_source,
    build_saved_vs_applied_summary,
    build_stale_pipeline_breakdown,
    build_time_to_first_response_by_source,
    infer_rejection_reason,
    infer_role_type,
    infer_source,
)


def test_source_response_rate_counts_recruiting_outcomes_as_responses() -> None:
    applications = [
        {
            "company": "A",
            "role": "QA Intern",
            "application_date": "2026-05-01",
            "status": "Rejected",
            "source_link": "https://www.linkedin.com/jobs/view/1",
        },
        {
            "company": "B",
            "role": "QA Intern",
            "application_date": "2026-05-02",
            "status": "Applied",
            "source_link": "https://www.linkedin.com/jobs/view/2",
        },
        {
            "company": "C",
            "role": "Developer",
            "application_date": "2026-05-03",
            "status": "Interview Scheduled",
            "source_link": "https://jobs.lever.co/example",
        },
    ]

    rows = build_response_rate_by_source(applications)

    assert rows[0]["source"] == "LinkedIn"
    assert rows[0]["applications"] == 2
    assert rows[0]["responses"] == 1
    assert rows[0]["response_rate"] == 0.5
    assert rows[1]["source"] == "Company Career Page / ATS"
    assert rows[1]["response_rate"] == 1.0


def test_interview_conversion_by_role_type_groups_role_keywords() -> None:
    applications = [
        {"role": "Working Student QA Automation", "status": "Assessment"},
        {"role": "Software Tester", "status": "Applied"},
        {"role": "Junior Technical Operations Analyst", "status": "Interview Scheduled"},
        {"role": "Backend Developer", "status": "Rejected"},
    ]

    rows = build_interview_conversion_by_role_type(applications)
    by_role_type = {row["role_type"]: row for row in rows}

    assert infer_role_type("Softwaretester im Bereich Entwicklung") == "QA / Testing"
    assert by_role_type["QA / Testing"]["applications"] == 2
    assert by_role_type["QA / Testing"]["conversion_rate"] == 0.5
    assert by_role_type["Technical Operations"]["conversion_rate"] == 1.0
    assert by_role_type["Software Engineering"]["conversion_rate"] == 0.0


def test_waiting_and_stale_metrics_focus_on_open_applications() -> None:
    applications = [
        {
            "company": "SAP",
            "role": "QA",
            "application_date": "2026-04-20",
            "status": "Applied",
        },
        {
            "company": "SAP",
            "role": "QA 2",
            "application_date": "2026-05-01",
            "status": "Confirmation Received",
        },
        {
            "company": "Bosch",
            "role": "Testing",
            "application_date": "2026-05-03",
            "status": "Rejected",
        },
        {
            "company": "Zalando",
            "role": "Operations",
            "application_date": "2026-04-28",
            "status": "Interview Scheduled",
        },
    ]

    today = date(2026, 5, 7)
    health = build_pipeline_health(applications, today=today)
    waiting_rows = build_average_waiting_days_by_company(applications, today=today)
    stale_rows = build_stale_pipeline_breakdown(applications, today=today)

    assert health["response_rate"] == 0.75
    assert health["interview_conversion_rate"] == 0.25
    assert health["stale_open_applications"] == 1
    assert waiting_rows[0]["company"] == "SAP"
    assert waiting_rows[0]["average_waiting_days"] == 11.5
    assert {"bucket": "Stale (14+ days)", "status": "Applied", "applications": 1} in stale_rows
    assert {"bucket": "Needs follow-up (7-13 days)", "status": "Interview Scheduled", "applications": 1} in stale_rows


def test_monthly_volume_saved_conversion_and_source_inference() -> None:
    applications = [
        {
            "role": "QA",
            "application_date": "2026-05-01",
            "status": "Saved",
            "source_link": "",
            "notes": "Found through StepStone search",
        },
        {
            "role": "QA",
            "application_date": "2026-05-02",
            "status": "Applied",
            "source_link": "https://company.example/jobs",
            "notes": "",
        },
        {
            "role": "QA",
            "application_date": "2026-05-09",
            "status": "Applied",
            "source_link": "",
            "notes": "",
        },
    ]

    monthly_rows = build_applications_per_month(applications)
    saved_rows = build_saved_vs_applied_summary(applications)

    assert infer_source(applications[0]) == "StepStone"
    assert infer_source(applications[1]) == "Company Career Page / ATS"
    assert infer_source(applications[2]) == "Manual / Unknown"
    assert monthly_rows == [
        {"month": "May 2026", "applications": 3},
    ]
    assert saved_rows == [
        {"stage": "Saved only", "applications": 1},
        {"stage": "Submitted / active", "applications": 2},
    ]


def test_infers_germany_specific_job_sources() -> None:
    assert (
        infer_source({"source_link": "https://www.arbeitsagentur.de/jobsuche/jobdetail/123", "notes": ""})
        == "Bundesagentur fuer Arbeit"
    )
    assert infer_source({"source_link": "https://www.stellenwerk.de/berlin/job/456", "notes": ""}) == "Stellenwerk"
    assert infer_source({"source_link": "", "notes": "Saved from Absolventa search"}) == "Absolventa"


def test_time_to_first_response_uses_status_history_by_source() -> None:
    applications = [
        {
            "id": 1,
            "role": "QA",
            "application_date": "2026-05-01",
            "status": "Interview Scheduled",
            "source_link": "https://www.linkedin.com/jobs/view/1",
        },
        {
            "id": 2,
            "role": "Developer",
            "application_date": "2026-05-02",
            "status": "Rejected",
            "source_link": "https://jobs.lever.co/example",
        },
    ]
    events = [
        {
            "application_id": 1,
            "event_type": "status_changed",
            "new_value": "Confirmation Received",
            "created_at": "2026-05-03T10:00:00+00:00",
        },
        {
            "application_id": 1,
            "event_type": "status_changed",
            "new_value": "Interview Scheduled",
            "created_at": "2026-05-04T10:00:00+00:00",
        },
        {
            "application_id": 2,
            "event_type": "status_changed",
            "new_value": "Rejected",
            "created_at": "2026-05-08T10:00:00+00:00",
        },
    ]

    rows = build_time_to_first_response_by_source(applications, events)
    by_source = {row["source"]: row for row in rows}

    assert by_source["LinkedIn"]["average_days_to_first_response"] == 2.0
    assert by_source["Company Career Page / ATS"]["average_days_to_first_response"] == 6.0


def test_rejection_reason_breakdown_groups_known_patterns() -> None:
    applications = [
        {
            "status": "Rejected",
            "rejection_reason": "The position closed before the final selection.",
        },
        {
            "status": "Rejected",
            "rejection_reason": "",
        },
        {
            "status": "Applied",
            "rejection_reason": "position closed",
        },
    ]

    rows = build_rejection_reason_breakdown(applications)

    assert infer_rejection_reason("position closed") == "Position closed or filled."
    assert {"rejection_reason": "Position closed or filled.", "applications": 1} in rows
    assert {"rejection_reason": "Unspecified / not recorded", "applications": 1} in rows


def test_rejection_reason_breakdown_groups_germany_specific_reasons() -> None:
    applications = [
        {
            "status": "Rejected",
            "rejection_reason": "Fuer diese Stelle sind C1 Deutschkenntnisse erforderlich.",
        },
        {
            "status": "Rejected",
            "rejection_reason": "Eine bestehende Arbeitserlaubnis ist erforderlich.",
        },
    ]

    rows = build_rejection_reason_breakdown(applications)

    assert {"rejection_reason": "Language requirement mismatch.", "applications": 1} in rows
    assert {"rejection_reason": "Visa or work authorization mismatch.", "applications": 1} in rows


def test_follow_up_effectiveness_groups_current_outcomes() -> None:
    applications = [
        {"id": 1, "status": "Assessment", "follow_up_date": ""},
        {"id": 2, "status": "No Response", "follow_up_date": "2026-05-14"},
        {"id": 3, "status": "Applied", "follow_up_date": ""},
    ]
    events = [
        {
            "application_id": 1,
            "event_type": "follow_up_date_changed",
            "new_value": "2026-05-14",
            "created_at": "2026-05-07T10:00:00+00:00",
        }
    ]

    rows = build_follow_up_effectiveness(applications, events)

    assert {"outcome": "Interview or assessment", "applications": 1, "share": 0.5} in rows
    assert {"outcome": "No response / archived", "applications": 1, "share": 0.5} in rows


def test_interview_to_offer_funnel_uses_historical_statuses() -> None:
    applications = [
        {"id": 1, "status": "Rejected"},
        {"id": 2, "status": "Offer"},
        {"id": 3, "status": "Saved"},
    ]
    events = [
        {"application_id": 1, "event_type": "status_changed", "new_value": "Interview Scheduled"},
        {"application_id": 1, "event_type": "status_changed", "new_value": "Assessment"},
    ]

    rows = build_interview_to_offer_funnel(applications, events)
    by_stage = {row["stage"]: row for row in rows}

    assert by_stage["Submitted"]["applications"] == 2
    assert by_stage["First response"]["applications"] == 2
    assert by_stage["Interview"]["applications"] == 2
    assert by_stage["Assessment"]["applications"] == 2
    assert by_stage["Offer"]["applications"] == 1


def test_channel_role_type_matrix_combines_source_and_role_type() -> None:
    applications = [
        {
            "role": "QA Automation Intern",
            "status": "Interview Scheduled",
            "source_link": "https://www.linkedin.com/jobs/view/1",
        },
        {
            "role": "QA Tester",
            "status": "Applied",
            "source_link": "https://www.linkedin.com/jobs/view/2",
        },
        {
            "role": "Backend Developer",
            "status": "Rejected",
            "source_link": "https://jobs.lever.co/example",
        },
    ]

    rows = build_channel_role_type_matrix(applications)
    by_key = {(row["source"], row["role_type"]): row for row in rows}

    assert by_key[("LinkedIn", "QA / Testing")]["applications"] == 2
    assert by_key[("LinkedIn", "QA / Testing")]["response_rate"] == 0.5
    assert by_key[("Company Career Page / ATS", "Software Engineering")]["response_rate"] == 1.0
