from src.email_insights import (
    build_context_rows,
    build_email_analysis_summary,
    build_match_signal_rows,
    build_workflow_steps,
    confidence_band,
    detected_context_count,
)


def test_confidence_band_labels() -> None:
    assert confidence_band(0.9)["label"] == "High"
    assert confidence_band(0.7)["label"] == "Medium"
    assert confidence_band(0.4)["label"] == "Low"


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
