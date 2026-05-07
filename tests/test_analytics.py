from datetime import date

from src.analytics import (
    build_applications_per_week,
    build_average_waiting_days_by_company,
    build_interview_conversion_by_role_type,
    build_pipeline_health,
    build_response_rate_by_source,
    build_saved_vs_applied_summary,
    build_stale_pipeline_breakdown,
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


def test_weekly_volume_saved_conversion_and_source_inference() -> None:
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

    weekly_rows = build_applications_per_week(applications)
    saved_rows = build_saved_vs_applied_summary(applications)

    assert infer_source(applications[0]) == "StepStone"
    assert infer_source(applications[1]) == "Company Career Page / ATS"
    assert infer_source(applications[2]) == "Manual / Unknown"
    assert weekly_rows == [
        {"week": "2026-W18", "applications": 2},
        {"week": "2026-W19", "applications": 1},
    ]
    assert saved_rows == [
        {"stage": "Saved only", "applications": 1},
        {"stage": "Submitted / active", "applications": 2},
    ]
