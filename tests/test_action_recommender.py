from datetime import date

from src.action_recommender import build_next_action_recommendation


def test_interview_action_uses_extracted_interview_date() -> None:
    recommendation = build_next_action_recommendation(
        {
            "category": "Interview Invitation",
            "suggested_status": "Interview Scheduled",
            "suggested_follow_up_days": 1,
        },
        {
            "company": "Bosch",
            "role": "QA Automation Intern",
            "interview_date": "2026-05-15",
        },
        today=date(2026, 5, 11),
    )

    assert recommendation["priority"] == "High"
    assert recommendation["follow_up_date"] == "2026-05-15"
    assert "prepare interview notes" in recommendation["next_action"]
    assert recommendation["template_type"] == "Interview Thank-you Email"


def test_assessment_action_prefers_deadline() -> None:
    recommendation = build_next_action_recommendation(
        {
            "category": "Assessment / Coding Test",
            "suggested_status": "Assessment",
            "suggested_follow_up_days": 2,
        },
        {
            "company": "SAP",
            "role": "QA Engineer",
            "deadline": "2026-05-13",
        },
        today=date(2026, 5, 11),
    )

    assert recommendation["priority"] == "High"
    assert recommendation["follow_up_date"] == "2026-05-13"
    assert recommendation["next_action"] == "Complete the assessment for SAP / QA Engineer by 2026-05-13."


def test_rejection_action_captures_reason_without_follow_up() -> None:
    recommendation = build_next_action_recommendation(
        {
            "category": "Rejection",
            "suggested_status": "Rejected",
            "suggested_follow_up_days": None,
        },
        {
            "company": "Flix",
            "role": "DevOps Engineer",
            "rejection_reason": "Other candidates were selected.",
        },
        today=date(2026, 5, 11),
    )

    assert recommendation["priority"] == "Medium"
    assert recommendation["follow_up_date"] == ""
    assert "Other candidates were selected." in recommendation["next_action"]
    assert recommendation["template_type"] == "Rejection Acknowledgement Email"


def test_confirmation_action_schedules_follow_up_from_relative_rule() -> None:
    recommendation = build_next_action_recommendation(
        {
            "category": "Application Confirmation",
            "suggested_status": "Confirmation Received",
            "suggested_follow_up_days": 7,
        },
        {"company": "Nexus", "role": "Softwaretester"},
        today=date(2026, 5, 11),
    )

    assert recommendation["priority"] == "Medium"
    assert recommendation["follow_up_date"] == "2026-05-18"
    assert "follow up if there is no update" in recommendation["next_action"]
