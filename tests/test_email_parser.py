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


def test_extracts_german_role_from_bewerbung_subject() -> None:
    details = extract_application_details(
        subject="Ihre Bewerbung als Werkstudent Konstruktion & Betriebsmittelmanagement (m/w/d)",
        body=(
            "Von: MELAG Recruiting <notification@melag.com>\n"
            "Standort: Berlin\n"
            "Nach sorgfältiger Prüfung Ihrer Unterlagen müssen wir Ihnen leider mitteilen, "
            "dass wir Sie bei der Besetzung der ausgeschriebenen Stelle nicht berücksichtigen können."
        ),
    )

    assert details["company"] == "Melag"
    assert details["role"] == "Werkstudent Konstruktion & Betriebsmittelmanagement (m/w/d)"
    assert details["location"] == "Berlin"
    assert "nicht berücksichtigen" in details["rejection_reason"]


def test_extracts_chinese_application_context_fields() -> None:
    details = extract_application_details(
        subject="面试邀请：软件测试实习生",
        body=(
            "发件人：招聘团队 <jobs@example.cn>\n"
            "公司：示例科技\n"
            "职位：软件测试实习生\n"
            "工作地点：上海\n"
            "我们邀请您参加视频面试，面试时间为2026年5月15日。请于2026年5月13日前确认。"
        ),
    )

    assert details["company"] == "示例科技"
    assert details["role"] == "软件测试实习生"
    assert details["location"] == "上海"
    assert details["contact"] == "招聘团队 <jobs@example.cn>"
    assert details["interview_date"] == "2026-05-15"
    assert details["deadline"] == "2026-05-13"


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


def test_matches_existing_application_with_domain_and_partial_role_context() -> None:
    applications = [
        {
            "id": 20,
            "company": "SAP",
            "role": "Werkstudent Quality AI Engineering",
            "application_date": "2026-04-30",
            "status": "Applied",
            "source_link": "https://jobs.sap.com/job/quality-ai",
        },
        {
            "id": 21,
            "company": "SAP",
            "role": "Data Analyst Intern",
            "application_date": "2026-05-01",
            "status": "Applied",
            "source_link": "https://jobs.sap.com/job/data",
        },
    ]

    match = match_application_from_email(
        applications,
        subject="Next steps for your Quality AI Engineering application",
        body="From: SAP Careers <careers@sap.com>\nWe would like to continue with your application.",
    )

    assert match is not None
    assert match["application_id"] == 20
    assert "sender or source domain matches company identity" in match["reasons"]


def test_does_not_auto_match_ambiguous_company_only_email() -> None:
    applications = [
        {"id": 30, "company": "SAP", "role": "QA Engineer", "status": "Applied"},
        {"id": 31, "company": "SAP", "role": "Data Analyst", "status": "Applied"},
    ]

    match = match_application_from_email(
        applications,
        subject="Application update",
        body="From: SAP Careers <careers@sap.com>\nThank you for your application at SAP.",
    )

    assert match is None


def test_prefers_active_application_when_email_intent_is_not_closed() -> None:
    applications = [
        {
            "id": 40,
            "company": "Bosch",
            "role": "QA Automation Intern",
            "status": "Rejected",
        },
        {
            "id": 41,
            "company": "Bosch",
            "role": "QA Automation Intern",
            "status": "Applied",
        },
    ]

    match = match_application_from_email(
        applications,
        subject="Interview invitation for QA Automation Intern",
        body="From: Talent Team <talent@bosch.com>\nWe would like to invite you to an interview.",
    )

    assert match is not None
    assert match["application_id"] == 41
    assert "interview email fits an active application" in match["reasons"]
