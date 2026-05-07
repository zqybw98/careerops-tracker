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
