from src.email_parser import extract_application_details, match_application_from_email


def test_extracts_application_details_from_email_text() -> None:
    details = extract_application_details(
        subject="Application for Junior QA Engineer at HUMANOO",
        body=(
            "From: Lisa Recruiting <lisa@humanoo.com>\n"
            "Thank you for your application for Junior QA Engineer at HUMANOO.\n"
            "Please check https://jobs.example.com/humanoo/qa for next steps."
        ),
    )

    assert details["company"] == "HUMANOO"
    assert details["role"] == "Junior QA Engineer"
    assert details["contact"] == "Lisa Recruiting <lisa@humanoo.com>"
    assert details["source_link"] == "https://jobs.example.com/humanoo/qa"


def test_extracts_company_from_sender_domain() -> None:
    details = extract_application_details(
        subject="Application confirmation",
        body="From: Recruiting <jobs@sap.com>\nWe have received your application.",
    )

    assert details["company"] == "SAP"


def test_extracts_interview_context_fields_from_email_text() -> None:
    details = extract_application_details(
        subject="Interview invitation for QA Automation Intern",
        body=(
            "From: Talent Team <talent@bosch.com>\n"
            "Company: Bosch\n"
            "Role: QA Automation Intern\n"
            "Location: Berlin\n"
            "We would like to invite you to an interview on 15 May 2026.\n"
            "Please confirm your availability by 2026-05-13."
        ),
    )

    assert details["company"] == "Bosch"
    assert details["role"] == "QA Automation Intern"
    assert details["location"] == "Berlin"
    assert details["interview_date"] == "2026-05-15"
    assert details["deadline"] == "2026-05-13"
    assert details["suggested_follow_up_date"] == "2026-05-13"


def test_extracts_rejection_reason_from_email_text() -> None:
    details = extract_application_details(
        subject="Update regarding your application",
        body=(
            "From: Recruiting <jobs@example.com>\n"
            "Unfortunately, the position has been filled and we will not proceed with your application."
        ),
    )

    assert details["rejection_reason"] == "Position closed or filled."


def test_matches_existing_application_from_email_context() -> None:
    applications = [
        {
            "id": 10,
            "company": "SAP",
            "role": "Werkstudent Quality AI Engineering",
            "application_date": "2026-04-30",
        },
        {
            "id": 11,
            "company": "DILAX",
            "role": "Student Assistant Software Testing",
            "application_date": "2026-04-29",
        },
    ]

    match = match_application_from_email(
        applications,
        subject="Update for Student Assistant Software Testing",
        body="Thank you for applying at DILAX. We would like to schedule an interview.",
    )

    assert match is not None
    assert match["application_id"] == 11
    assert match["score"] >= 5
