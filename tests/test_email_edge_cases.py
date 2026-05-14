from src.email_classifier import classify_email
from src.email_parser import (
    extract_application_details,
    match_application_from_email,
    rank_application_matches_from_email,
)


def test_disambiguates_same_company_similar_roles_by_role_keywords() -> None:
    applications = [
        {
            "id": 1,
            "company": "SAP",
            "role": "Werkstudent Quality AI Engineering",
            "status": "Applied",
            "source_link": "https://jobs.sap.com/quality-ai",
        },
        {
            "id": 2,
            "company": "SAP",
            "role": "Werkstudent Quality Assurance Testing",
            "status": "Applied",
            "source_link": "https://jobs.sap.com/quality-testing",
        },
        {
            "id": 3,
            "company": "SAP",
            "role": "Data Analyst Intern",
            "status": "Applied",
            "source_link": "https://jobs.sap.com/data",
        },
    ]

    matches = rank_application_matches_from_email(
        applications,
        subject="Next steps for your Werkstudent Quality AI Engineering application",
        body="From: SAP Careers <careers@sap.com>\nWe would like to discuss this Quality AI Engineering role.",
    )

    assert [match["application_id"] for match in matches[:2]] == [1, 2]
    assert matches[0]["score"] > matches[1]["score"]


def test_forwarded_email_uses_original_recruiter_sender_not_personal_mail_wrapper() -> None:
    details = extract_application_details(
        subject="Fwd: Invitation for Werkstudent Quality AI Engineering",
        body=(
            "From: Yibo Zhang <me@gmail.com>\n"
            "To: careerops@example.com\n\n"
            "---------- Forwarded message ---------\n"
            "From: SAP Careers <careers@sap.com>\n"
            "Subject: Invitation for Werkstudent Quality AI Engineering\n"
            "We would like to invite you to an interview on 20 May 2026. "
            "Please confirm your availability by 2026-05-16."
        ),
    )

    assert details["company"] == "SAP"
    assert details["contact"] == "SAP Careers <careers@sap.com>"
    assert details["interview_date"] == "2026-05-20"
    assert details["deadline"] == "2026-05-16"


def test_multiple_dates_keep_interview_and_deadline_context_separate() -> None:
    details = extract_application_details(
        subject="Technical interview for QA Automation Intern",
        body=(
            "From: Bosch Talent <talent@bosch.de>\n"
            "The job was posted on 2026-04-30 and the internship starts on 2026-06-01. "
            "Your technical interview is scheduled for 22 May 2026. "
            "Please submit your availability by 2026-05-16."
        ),
    )

    assert details["interview_date"] == "2026-05-22"
    assert details["deadline"] == "2026-05-16"
    assert details["suggested_follow_up_date"] == "2026-05-16"


def test_rejection_reason_detects_language_visa_and_location_mismatches() -> None:
    language_details = extract_application_details(
        subject="Application update",
        body="Unfortunately, we cannot proceed because this role requires stronger German skills.",
    )
    visa_details = extract_application_details(
        subject="Application update",
        body="Unfortunately, we are not able to offer visa sponsorship for this position.",
    )
    location_details = extract_application_details(
        subject="Application update",
        body="Unfortunately, this is a location mismatch because you are not based in Munich.",
    )

    assert language_details["rejection_reason"] == "Language requirement mismatch."
    assert visa_details["rejection_reason"] == "Visa or work authorization mismatch."
    assert location_details["rejection_reason"] == "Location requirement mismatch."


def test_unclear_recruiter_message_can_match_from_domain_hint() -> None:
    applications = [
        {
            "id": 10,
            "company": "acemate",
            "role": "Software Developer Intern",
            "status": "Applied",
            "source_link": "https://acemate.ai/careers/software-developer-intern",
            "contact": "jobs@acemate.ai",
        }
    ]

    match = match_application_from_email(
        applications,
        subject="Quick question",
        body="From: Recruiting <talent@acemate.ai>\nCould you share your availability for next week?",
    )
    classification = classify_email(
        subject="Quick question",
        body="From: Recruiting <talent@acemate.ai>\nCould you share your availability for next week?",
    )

    assert match is not None
    assert match["application_id"] == 10
    assert "sender or source domain matches company identity" in match["reasons"]
    assert classification["category"] == "Recruiter Reply"


def test_long_mixed_english_german_email_still_classifies_and_matches() -> None:
    applications = [
        {
            "id": 20,
            "company": "MHP",
            "role": "Werkstudent Data Analytics",
            "status": "Applied",
            "source_link": "https://mhp.com/jobs/data-analytics",
            "contact": "recruiting@mhp.com",
        }
    ]
    body = (
        "From: MHP Recruiting <recruiting@mhp.com>\n"
        + "Thank you again for your interest. " * 40
        + "Wir haben Ihre Bewerbung fuer die Position Werkstudent Data Analytics geprueft. "
        + "Leider koennen wir Sie nicht in die engere Auswahl aufnehmen. "
        + "Unfortunately, we have decided not to continue with your application."
    )

    classification = classify_email("Update zu Ihrer Bewerbung", body)
    details = extract_application_details("Update zu Ihrer Bewerbung", body)
    match = match_application_from_email(applications, "Update zu Ihrer Bewerbung", body)

    assert classification["category"] == "Rejection"
    assert details["company"] == "MHP"
    assert details["rejection_reason"]
    assert match is not None
    assert match["application_id"] == 20
