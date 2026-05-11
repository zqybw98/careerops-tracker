from datetime import date

from src.action_recommender import build_next_action_recommendation, build_workflow_decision


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


def test_workflow_decision_closes_rejected_application() -> None:
    classification = {
        "category": "Rejection",
        "confidence": 0.91,
        "suggested_status": "Rejected",
    }
    recommendation = build_next_action_recommendation(
        classification,
        {"company": "SAP", "role": "QA Engineer", "rejection_reason": "Other candidates were selected."},
        today=date(2026, 5, 11),
    )

    decision = build_workflow_decision(
        classification,
        {"company": "SAP", "role": "QA Engineer"},
        recommendation,
        application={"id": 1, "company": "SAP", "role": "QA Engineer", "status": "Applied"},
        auto_match={"application_id": 1},
    )

    assert decision["operation"] == "Close application"
    assert decision["review_level"] == "Low"
    assert decision["status_action"] == "Applied -> Rejected"
    assert decision["primary_action_label"] == "Apply rejection update"


def test_workflow_decision_requires_confirmation_for_candidate_match() -> None:
    classification = {
        "category": "Application Confirmation",
        "confidence": 0.74,
        "suggested_status": "Confirmation Received",
        "suggested_follow_up_days": 7,
    }
    recommendation = build_next_action_recommendation(
        classification,
        {"company": "SAP", "role": "QA Engineer"},
        today=date(2026, 5, 11),
    )

    decision = build_workflow_decision(
        classification,
        {"company": "SAP", "role": "QA Engineer"},
        recommendation,
        application={"id": 1, "company": "SAP", "role": "QA Engineer", "status": "Applied"},
        auto_match=None,
        match_candidates=[{"application_id": 1}],
    )

    assert decision["operation"] == "Confirm match"
    assert decision["review_level"] == "Medium"
    assert decision["status_action"] == "Applied -> Confirmation Received"


def test_workflow_decision_uses_manual_review_for_low_confidence_email() -> None:
    classification = {
        "category": "Other",
        "confidence": 0.2,
        "suggested_status": "Applied",
    }
    recommendation = build_next_action_recommendation(
        classification,
        {"company": "SAP", "role": "QA Engineer"},
        today=date(2026, 5, 11),
    )

    decision = build_workflow_decision(
        classification,
        {"company": "SAP", "role": "QA Engineer"},
        recommendation,
        application={"id": 1, "company": "SAP", "role": "QA Engineer", "status": "Applied"},
    )

    assert decision["operation"] == "Manual review"
    assert decision["review_level"] == "High"
    assert decision["status_action"] == "Keep Applied"


def test_workflow_decision_can_create_application_from_email_context() -> None:
    classification = {
        "category": "Interview Invitation",
        "confidence": 0.86,
        "suggested_status": "Interview Scheduled",
    }
    details = {"company": "Bosch", "role": "QA Intern"}
    recommendation = build_next_action_recommendation(classification, details, today=date(2026, 5, 11))

    decision = build_workflow_decision(classification, details, recommendation)

    assert decision["operation"] == "Create application"
    assert decision["status_action"] == "Create as Interview Scheduled"
