from src.email_classifier import classify_email


def test_classifies_rejection_email() -> None:
    result = classify_email(
        subject="Update on your application",
        body="Unfortunately, after careful consideration, we have decided not to proceed.",
    )

    assert result["category"] == "Rejection"
    assert result["suggested_status"] == "Rejected"
    assert result["confidence"] >= 0.5


def test_classifies_interview_invitation() -> None:
    result = classify_email(
        subject="Interview invitation",
        body="We would like to schedule an interview and discuss next steps.",
    )

    assert result["category"] == "Interview Invitation"
    assert result["suggested_status"] == "Interview Scheduled"


def test_classifies_application_confirmation() -> None:
    result = classify_email(
        subject="Application confirmation",
        body="Thank you for your application. We have received your application.",
    )

    assert result["category"] == "Application Confirmation"
    assert result["suggested_status"] == "Confirmation Received"


def test_unknown_email_returns_other() -> None:
    result = classify_email(subject="Newsletter", body="Here are this week's articles.")

    assert result["category"] == "Other"
    assert result["confidence"] == 0.2
