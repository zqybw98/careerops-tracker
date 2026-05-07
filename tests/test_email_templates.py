from datetime import date

from src.email_templates import generate_email_template, suggest_template_type


def test_suggests_template_type_from_status() -> None:
    assert suggest_template_type({"status": "Interview Scheduled"}) == "Interview Thank-you Email"
    assert suggest_template_type({"status": "Rejected"}) == "Rejection Acknowledgement Email"
    assert suggest_template_type({"status": "No Response"}) == "Recruiter Outreach Email"
    assert suggest_template_type({"status": "Applied"}) == "Follow-up Email"


def test_generates_follow_up_email() -> None:
    result = generate_email_template(
        {
            "company": "SAP",
            "role": "QA Engineer",
            "contact": "Lisa Recruiting <lisa@sap.com>",
            "application_date": "2026-04-30",
        },
        "Follow-up Email",
        sender_name="Yibo Zhang",
        today=date(2026, 5, 7),
    )

    assert result["subject"] == "Follow-up on QA Engineer application"
    assert "Dear Lisa Recruiting" in result["body"]
    assert "QA Engineer position at SAP" in result["body"]
    assert "submitted on 2026-04-30" in result["body"]
    assert "Yibo Zhang" in result["body"]


def test_generates_interview_thank_you_email() -> None:
    result = generate_email_template(
        {"company": "DILAX", "role": "Student Assistant Software Testing"},
        "Interview Thank-you Email",
        recipient_name="Hiring Team",
    )

    assert "Thank you for the interview" in result["subject"]
    assert "Student Assistant Software Testing position at DILAX" in result["body"]


def test_generates_rejection_acknowledgement_email() -> None:
    result = generate_email_template(
        {"company": "Bosch", "role": "Automation Testing Intern"},
        "Rejection Acknowledgement Email",
    )

    assert "Thank you for the update" in result["subject"]
    assert "future opportunities" in result["body"]
