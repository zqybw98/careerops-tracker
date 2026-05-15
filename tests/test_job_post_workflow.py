from datetime import date

from src.services.job_post_workflow import build_job_post_application_draft


def test_builds_saved_application_payload_from_job_post() -> None:
    draft = build_job_post_application_draft(
        source_url="https://careers.sap.com/job/quality-ai-working-student",
        job_text="""
        Company: SAP
        Role: Werkstudent Quality & AI Engineering
        Location: Berlin
        Apply by 2026-06-01
        """,
        today=date(2026, 5, 15),
    )

    payload = draft["payload"]

    assert draft["can_create"] is True
    assert payload["company"] == "SAP"
    assert payload["role"] == "Werkstudent Quality & AI Engineering"
    assert payload["application_date"] == "2026-05-15"
    assert payload["status"] == "Saved"
    assert payload["source_link"] == "https://careers.sap.com/job/quality-ai-working-student"
    assert payload["follow_up_date"] == "2026-06-01"
    assert "Draft created from job post intake" in payload["notes"]
    assert "Review JD" in payload["next_action"]


def test_requires_company_and_role_before_creation() -> None:
    draft = build_job_post_application_draft(
        job_text="Benefits and responsibilities only.",
        today=date(2026, 5, 15),
    )

    assert draft["can_create"] is False
    assert draft["analysis"]["missing_fields"] == ["company", "role"]
