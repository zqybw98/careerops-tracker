from pathlib import Path

from src.database import create_application, get_application_events, get_applications, init_db
from src.services.email_workflow import (
    apply_email_workflow_update,
    apply_gmail_preview,
    build_email_create_recommendation,
    build_email_workflow_for_application,
    build_initial_email_create_notes,
    classify_email_for_workflow,
)


def test_classifies_email_and_builds_workflow_context() -> None:
    applications = [
        {
            "id": 1,
            "company": "Bosch",
            "role": "QA Automation Intern",
            "location": "Berlin",
            "status": "Applied",
        }
    ]

    workflow = classify_email_for_workflow(
        subject="Interview invitation for QA Automation Intern",
        body="Bosch would like to invite you to an interview in Berlin next week.",
        applications=applications,
    )
    context = build_email_workflow_for_application(
        workflow["classification"],
        workflow["details"],
        applications[0],
        workflow["match"],
        workflow["match_candidates"],
    )

    assert workflow["classification"]["suggested_status"] == "Interview Scheduled"
    assert context["workflow_decision"]["operation"] == "Prepare interview"
    assert "Operation summary:" in context["operation_summary"]["audit_note"]


def test_builds_initial_email_create_notes() -> None:
    classification = {
        "category": "Application Confirmation",
        "confidence": 0.85,
        "suggested_status": "Confirmation Received",
        "suggested_follow_up_days": 7,
    }
    details = {"company": "SAP", "role": "QA Engineer"}
    recommendation = build_email_create_recommendation(classification, details)

    notes = build_initial_email_create_notes(classification, details, recommendation)

    assert "Email classified as Application Confirmation" in notes
    assert "Smart next action generated:" in notes


def test_apply_email_workflow_update_records_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    application_id = create_application(
        {
            "company": "SAP",
            "role": "QA Engineer",
            "application_date": "2026-05-13",
            "status": "Applied",
        },
        db_path=db_path,
    )
    selected = get_applications(db_path)[0]
    classification = {
        "category": "Rejection",
        "confidence": 0.91,
        "suggested_status": "Rejected",
        "suggested_follow_up_days": None,
    }
    details = {
        "company": "SAP",
        "role": "QA Engineer",
        "rejection_reason": "The position has been filled.",
    }
    recommendation = build_email_create_recommendation(classification, details)
    workflow = build_email_workflow_for_application(
        classification,
        details,
        selected,
        match={"application_id": application_id, "company": "SAP", "role": "QA Engineer", "confidence": 0.9},
        match_candidates=[],
    )

    apply_email_workflow_update(
        application_id,
        selected,
        classification,
        details,
        recommendation,
        apply_status=True,
        operation_summary=workflow["operation_summary"],
        db_path=db_path,
    )

    updated = get_applications(db_path)[0]
    events = get_application_events(application_id, db_path)

    assert updated["status"] == "Rejected"
    assert "Operation summary:" in updated["notes"]
    assert updated["rejection_reason"] == "The position has been filled."
    assert any(event["source"] == "email_assistant" for event in events)


def test_apply_gmail_preview_preserves_rejection_default(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    application_id = create_application(
        {
            "company": "Flix",
            "role": "DevOps Engineer",
            "application_date": "2026-05-13",
            "status": "Applied",
        },
        db_path=db_path,
    )
    applications = get_applications(db_path)
    preview = {
        "matched_application_id": application_id,
        "classification": {
            "category": "Rejection",
            "confidence": 0.9,
            "suggested_status": "Rejected",
            "suggested_follow_up_days": None,
        },
        "details": {"company": "Flix", "role": "DevOps Engineer"},
        "subject": "Application update",
        "sender": "jobs@example.com",
    }

    action = apply_gmail_preview(preview, applications, db_path=db_path)
    updated = get_applications(db_path)[0]

    assert action == "updated"
    assert updated["status"] == "Rejected"
    assert updated["rejection_reason"] == "Rejected based on Gmail recruiting email."
