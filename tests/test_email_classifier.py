from src.email_classifier import classify_email


def test_classifies_rejection_email() -> None:
    result = classify_email(
        subject="Update on your application",
        body="Unfortunately, after careful consideration, we have decided not to proceed.",
    )

    assert result["category"] == "Rejection"
    assert result["suggested_status"] == "Rejected"
    assert result["confidence"] >= 0.5


def test_classifies_moving_forward_rejection_email() -> None:
    result = classify_email(
        subject="Yibo Zhang & Bending Spoons - Regarding your application",
        body=(
            "We have carefully reviewed your application and are sorry to inform you that "
            "we won't be moving forward with it this time. There are a lot of strong "
            "candidates and some of them are better suited for the job."
        ),
    )

    assert result["category"] == "Rejection"
    assert result["suggested_status"] == "Rejected"
    assert result["confidence"] >= 0.8


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


def test_classifies_german_rejection_email() -> None:
    result = classify_email(
        subject="Ihre Bewerbung als Werkstudent Konstruktion",
        body="Leider müssen wir Ihnen mitteilen, dass wir Ihre Bewerbung nicht weiter berücksichtigen können.",
    )

    assert result["category"] == "Rejection"
    assert result["suggested_status"] == "Rejected"


def test_classifies_common_german_recruiting_phrases() -> None:
    interview = classify_email(
        subject="Einladung zum Gespraech",
        body="Wir moechten Sie zu einem Kennenlerngespraech einladen.",
    )
    assessment = classify_email(
        subject="Fachtest fuer Ihre Bewerbung",
        body="Bitte bearbeiten Sie die Arbeitsprobe bis Ende der Woche.",
    )
    rejection = classify_email(
        subject="Rueckmeldung zu Ihrer Bewerbung",
        body="Wir bedauern, Ihnen leider keine positive Rueckmeldung geben zu koennen.",
    )

    assert interview["category"] == "Interview Invitation"
    assert assessment["category"] == "Assessment / Coding Test"
    assert rejection["category"] == "Rejection"


def test_classifies_chinese_interview_invitation() -> None:
    result = classify_email(
        subject="面试邀请：软件测试实习生",
        body="我们想邀请您参加视频面试，请告知方便时间。",
    )

    assert result["category"] == "Interview Invitation"
    assert result["suggested_status"] == "Interview Scheduled"


def test_classifies_chinese_application_confirmation() -> None:
    result = classify_email(
        subject="申请已收到",
        body="感谢您的申请，我们已收到您的申请材料。",
    )

    assert result["category"] == "Application Confirmation"
    assert result["suggested_status"] == "Confirmation Received"


def test_unknown_email_returns_other() -> None:
    result = classify_email(subject="Newsletter", body="Here are this week's articles.")

    assert result["category"] == "Other"
    assert result["confidence"] == 0.2
