from datetime import date

from src.contacts import build_contact_records, infer_contact_channel, infer_contact_type


def test_groups_same_recruiter_across_multiple_applications() -> None:
    applications = [
        {
            "id": 1,
            "company": "SAP",
            "role": "QA Engineer",
            "status": "Applied",
            "contact": "Lisa Talent <lisa@sap.com>",
            "follow_up_date": "2026-05-14",
            "updated_at": "2026-05-12T10:00:00+00:00",
        },
        {
            "id": 2,
            "company": "SAP",
            "role": "Data Analyst",
            "status": "Rejected",
            "contact": "Lisa Talent <lisa@sap.com>",
            "updated_at": "2026-05-11T10:00:00+00:00",
        },
    ]

    contacts = build_contact_records(applications, today=date(2026, 5, 14))

    assert len(contacts) == 1
    assert contacts[0]["contact"] == "Lisa Talent <lisa@sap.com>"
    assert contacts[0]["applications"] == 2
    assert contacts[0]["open_applications"] == 1
    assert contacts[0]["follow_up_status"] == "Due"
    assert contacts[0]["next_follow_up_date"] == "2026-05-14"


def test_infers_contact_type_and_channel_from_context() -> None:
    referral_application = {
        "contact": "Max Mustermann",
        "notes": "Referral from alumni network",
        "source_link": "",
    }
    hiring_manager_application = {
        "contact": "Anna Team Lead",
        "notes": "Hiring manager asked for availability",
        "source_link": "",
    }
    linkedin_application = {
        "contact": "Recruiter",
        "notes": "",
        "source_link": "https://www.linkedin.com/jobs/view/1",
    }

    assert infer_contact_type(referral_application) == "Referral"
    assert infer_contact_channel(referral_application) == "Referral"
    assert infer_contact_type(hiring_manager_application) == "Hiring Manager"
    assert infer_contact_channel(linkedin_application) == "LinkedIn"


def test_creates_source_contact_when_no_named_contact_exists() -> None:
    applications = [
        {
            "id": 1,
            "company": "Bosch",
            "role": "Automation Testing Intern",
            "status": "Applied",
            "source_link": "https://jobs.bosch.com/testing",
            "contact": "",
            "updated_at": "2026-05-10T10:00:00+00:00",
        }
    ]

    contacts = build_contact_records(applications)

    assert contacts[0]["contact"] == "Bosch careers"
    assert contacts[0]["contact_type"] == "Company / ATS"
    assert contacts[0]["channel"] == "Career Page / ATS"


def test_last_contact_uses_relevant_activity_events() -> None:
    applications = [
        {
            "id": 1,
            "company": "DILAX",
            "role": "Software Testing",
            "status": "Applied",
            "contact": "talent@dilax.com",
            "updated_at": "2026-05-10T10:00:00+00:00",
        }
    ]
    events = [
        {
            "application_id": 1,
            "event_type": "status_changed",
            "created_at": "2026-05-12T08:00:00+00:00",
        },
        {
            "application_id": 1,
            "event_type": "notes_changed",
            "created_at": "2026-05-13T08:00:00+00:00",
        },
    ]

    contacts = build_contact_records(applications, events=events)

    assert contacts[0]["last_contact_at"] == "2026-05-12T08:00:00+00:00"
