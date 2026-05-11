from src.email_insights import (
    build_confidence_threshold_rows,
    build_context_rows,
    build_email_analysis_summary,
    build_match_candidate_rows,
    build_match_signal_rows,
    build_workflow_steps,
    confidence_band,
    confidence_gate,
    detected_context_count,
)


def test_confidence_band_labels() -> None:
    assert confidence_band(0.9)["label"] == "High"
    assert confidence_band(0.7)["label"] == "Medium"
    assert confidence_band(0.4)["label"] == "Low"


def test_confidence_gate_enforces_thresholds() -> None:
    assert confidence_gate(0.9)["gate"] == "Ready"
    assert confidence_gate(0.7)["gate"] == "Review required"
    assert confidence_gate(0.4)["gate"] == "Blocked"


def test_builds_confidence_threshold_rows() -> None:
    rows = build_confidence_threshold_rows()

    assert rows[0]["Threshold"] == ">= 85%"
    assert rows[1]["Threshold"] == "60% - 84%"
    assert rows[2]["Workflow rule"] == "Block status update; save task only"


def test_builds_analysis_summary_with_match() -> None:
    classification = {
        "category": "Interview Invitation",
        "confidence": 0.93,
        "suggested_status": "Interview Scheduled",
    }
    details = {
        "company": "Bosch",
        "role": "QA Intern",
        "interview_date": "2026-05-15",
    }
    match = {
        "company": "Bosch",
        "role": "QA Intern",
        "confidence": 0.88,
    }

    summary = build_email_analysis_summary(classification, details, match)

    assert summary["confidence_label"] == "High"
    assert summary["detected_context"] == "3/9"
    assert summary["match_label"] == "High match"
    assert "Best existing match is Bosch / QA Intern" in summary["decision"]


def test_builds_analysis_summary_with_candidate_review() -> None:
    classification = {
        "category": "Application Confirmation",
        "confidence": 0.7,
        "suggested_status": "Confirmation Received",
    }
    details = {"company": "SAP"}

    summary = build_email_analysis_summary(classification, details, match=None, candidate_count=3)

    assert summary["match_label"] == "Review candidates"
    assert "3 possible existing application match(es) need review" in summary["decision"]


def test_context_rows_track_detected_fields() -> None:
    details = {"company": "SAP", "role": "QA Engineer", "deadline": "2026-05-13"}

    rows = build_context_rows(details)

    assert detected_context_count(details) == 3
    assert {"Field": "Company", "Value": "SAP", "Use": "Application identity", "Detected": "yes"} in rows
    assert {"Field": "Contact", "Value": "-", "Use": "Reply context", "Detected": "no"} in rows


def test_match_signal_rows_and_workflow_steps() -> None:
    match = {"signals": {"company": 6, "role": 7, "domain": 4, "status": 2}}
    classification = {"category": "Assessment / Coding Test", "suggested_status": "Assessment"}
    recommendation = {
        "next_action": "Complete the assessment by 2026-05-13.",
        "follow_up_date": "2026-05-13",
    }

    signals = build_match_signal_rows(match)
    steps = build_workflow_steps(classification, recommendation, has_match=True)

    assert {"Signal": "Company", "Score": "6"} in signals
    assert steps[1]["Action"] == "Confirm the matched application"
    assert steps[-1]["Action"] == "Set follow-up date to 2026-05-13"


def test_workflow_steps_include_decision_context() -> None:
    classification = {"category": "Rejection", "suggested_status": "Rejected"}
    recommendation = {
        "next_action": "Capture rejection reason.",
        "follow_up_date": "",
    }
    workflow_decision = {
        "record_action": "Save rejection reason and add a traceable activity event.",
        "status_action": "Applied -> Rejected",
    }

    steps = build_workflow_steps(
        classification,
        recommendation,
        has_match=True,
        workflow_decision=workflow_decision,
    )

    assert steps[1]["Action"] == "Save rejection reason and add a traceable activity event."
    assert steps[-1]["Action"] == "Applied -> Rejected"


def test_builds_match_candidate_rows() -> None:
    matches = [
        {
            "application_id": 1,
            "company": "SAP",
            "role": "QA Engineer",
            "confidence": 0.89,
            "score": 16,
            "reasons": ["company name appears in email", "role title appears in email"],
        },
        {
            "application_id": 2,
            "company": "SAP",
            "role": "Data Analyst",
            "confidence": 0.61,
            "score": 11,
            "reasons": ["company name appears in email"],
        },
    ]

    rows = build_match_candidate_rows(matches, selected_match=matches[0])

    assert rows[0]["Recommendation"] == "Auto-selected"
    assert rows[0]["Band"] == "High"
    assert rows[1]["Recommendation"] == "Alternative"
    assert rows[1]["Confidence"] == "61%"
