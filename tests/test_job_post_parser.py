from src.job_post_parser import analyze_job_post


def test_extracts_structured_english_job_post() -> None:
    analysis = analyze_job_post(
        source_url="https://careers.siemens.com/jobs/qa-automation-working-student",
        job_text="""
        Company: Siemens
        Job title: Working Student QA Automation
        Location: Berlin
        Application deadline: 2026-05-30
        Contact: recruiter@siemens.com
        """,
    )

    details = analysis["details"]

    assert details["company"] == "Siemens"
    assert details["role"] == "Working Student QA Automation"
    assert details["location"] == "Berlin"
    assert details["source_link"] == "https://careers.siemens.com/jobs/qa-automation-working-student"
    assert details["contact"] == "recruiter@siemens.com"
    assert details["deadline"] == "2026-05-30"
    assert analysis["status"] == "Saved"
    assert analysis["follow_up_date"] == "2026-05-30"
    assert "apply before 2026-05-30" in analysis["next_action"]


def test_extracts_german_job_post_with_deadline() -> None:
    analysis = analyze_job_post(
        job_text="""
        Unternehmen: SAP
        Stelle: Werkstudent Quality Engineering
        Standort: Walldorf
        Bewerbungsfrist: 31.05.2026
        """,
    )

    details = analysis["details"]

    assert details["company"] == "SAP"
    assert details["role"] == "Werkstudent Quality Engineering"
    assert details["location"] == "Walldorf"
    assert details["deadline"] == "2026-05-31"


def test_uses_job_url_domain_when_company_label_is_missing() -> None:
    analysis = analyze_job_post(
        source_url="https://jobs.bosch.com/job/software-test-automation-intern",
        job_text="""
        Software Test Automation Intern
        Location: Stuttgart
        Support automated regression testing for embedded software.
        """,
    )

    details = analysis["details"]

    assert details["company"] == "Bosch"
    assert details["role"] == "Software Test Automation Intern"
    assert details["location"] == "Stuttgart"
    assert analysis["missing_fields"] == []
