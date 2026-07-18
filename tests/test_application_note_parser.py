from datetime import date

import pytest
import src.application_note_parser as application_note_parser
from src.application_note_parser import parse_application_note


def test_parses_structured_application_note_from_chat_summary() -> None:
    result = parse_application_note(
        """
        Datum: 17.05.2026
        Company: EY / Ernst & Young
        Position: SAP Innovation Engineer (w/m/d)
        Location: Berlin
        Status: Applied / Bewerbung abgeschickt
        CV used: EY SAP Innovation Engineer 2-page German CV
        Cover letter: EY SAP Innovation Engineer German Anschreiben
        Next step: Wait for confirmation email; follow up after 5-7 working days.
        """
    )

    fields = result["fields"]

    assert fields["application_date"] == "2026-05-17"
    assert fields["company"] == "EY / Ernst & Young"
    assert fields["role"] == "SAP Innovation Engineer (w/m/d)"
    assert fields["location"] == "Berlin"
    assert fields["status"] == "Applied"
    assert fields["next_action"] == "Wait for confirmation email; follow up after 5-7 working days."
    assert "CV used: EY SAP Innovation Engineer 2-page German CV" in result["notes"]
    assert "Cover letter: EY SAP Innovation Engineer German Anschreiben" in result["notes"]
    assert result["missing_fields"] == []


def test_parses_german_and_chinese_labels() -> None:
    result = parse_application_note(
        """
        Bewerbungsdatum: 2026-05-18
        Unternehmen: SAP
        Stelle: Werkstudent Quality Engineering
        Standort: Walldorf
        状态: 申请已提交
        下一步: 等待确认邮件
        """
    )

    fields = result["fields"]

    assert fields["application_date"] == "2026-05-18"
    assert fields["company"] == "SAP"
    assert fields["role"] == "Werkstudent Quality Engineering"
    assert fields["location"] == "Walldorf"
    assert fields["status"] == "Applied"
    assert fields["next_action"] == "等待确认邮件"


def test_parses_chatgpt_json_application_import() -> None:
    result = parse_application_note(
        """
        ChatGPT suggested tracker record:

        ```json
        {
          "application_date": "17.05.2026",
          "company": "EY",
          "role": "SAP Innovation Engineer (w/m/d)",
          "location": "Berlin, Germany",
          "status": "Bewerbung abgeschickt",
          "source_link": "https://example.com/jobs/123",
          "cv_version": "EY SAP Innovation Engineer 2-page German CV",
          "next_action": "Wait for confirmation email; follow up after 5-7 working days.",
          "follow_up_date": "24.05.2026",
          "notes": "Application submitted from ChatGPT job summary."
        }
        ```
        """
    )

    fields = result["fields"]

    assert fields["application_date"] == "2026-05-17"
    assert fields["company"] == "EY"
    assert fields["role"] == "SAP Innovation Engineer (w/m/d)"
    assert fields["location"] == "Berlin, Germany"
    assert fields["status"] == "Applied"
    assert fields["source_link"] == "https://example.com/jobs/123"
    assert fields["next_action"] == "Wait for confirmation email; follow up after 5-7 working days."
    assert fields["follow_up_date"] == "2026-05-24"
    assert "CV used: EY SAP Innovation Engineer 2-page German CV" in result["notes"]
    assert "Notes: Application submitted from ChatGPT job summary." in result["notes"]
    assert result["notes"].count("Notes: Application submitted from ChatGPT job summary.") == 1
    assert result["missing_fields"] == []


def test_parses_raw_json_and_ignores_unknown_or_internal_fields() -> None:
    result = parse_application_note(
        """
        {
          "id": 999,
          "company": "Muller & Sohne GmbH",
          "role": "C++ QA Engineer (m/f/d)",
          "location": "Berlin",
          "status": "Submitted",
          "source_url": "https://example.com/jobs/qa?lang=de&source=career",
          "contact": "",
          "notes": "",
          "unexpected_command": "must not be imported"
        }
        """
    )

    assert result["fields"] == {
        "company": "Muller & Sohne GmbH",
        "role": "C++ QA Engineer (m/f/d)",
        "location": "Berlin",
        "status": "Applied",
        "source_link": "https://example.com/jobs/qa?lang=de&source=career",
    }
    assert "id" not in result["fields"]
    assert "unexpected_command" not in result["fields"]


@pytest.mark.parametrize(
    ("json_text", "missing_field"),
    [
        ('{"role": "QA Engineer"}', "company"),
        ('{"company": "Example GmbH"}', "role"),
    ],
)
def test_reports_missing_required_json_fields(json_text: str, missing_field: str) -> None:
    result = parse_application_note(json_text)

    assert missing_field in result["missing_fields"]


def test_invalid_dates_are_ignored_without_crashing() -> None:
    result = parse_application_note(
        """
        {
          "company": "Example GmbH",
          "role": "QA Engineer",
          "application_date": "2026-02-30",
          "follow_up_date": "not a date"
        }
        """
    )

    assert "application_date" not in result["fields"]
    assert "follow_up_date" not in result["fields"]


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        ("Absage", "Rejected"),
        ("Interview invitation", "Interview / Assessment"),
        ("Application confirmation", "Waiting"),
    ],
)
def test_normalizes_imported_statuses(raw_status: str, expected: str) -> None:
    result = parse_application_note(f'{{"company": "Example GmbH", "role": "QA Engineer", "status": "{raw_status}"}}')

    assert result["fields"]["status"] == expected


def test_malformed_json_safely_falls_back_to_labeled_text() -> None:
    result = parse_application_note(
        """
        ```json
        {"company": "broken"
        ```
        Company: Example GmbH
        Role: QA Engineer
        Source: https://example.com/jobs/123
        """
    )

    assert result["fields"]["company"] == "Example GmbH"
    assert result["fields"]["role"] == "QA Engineer"
    assert result["fields"]["source_link"] == "https://example.com/jobs/123"


def test_build_payload_applies_rejected_rules_and_allowlists_fields() -> None:
    builder = getattr(application_note_parser, "build_application_payload", None)
    assert callable(builder), "application import payload builder should be independently testable"
    parsed = parse_application_note(
        """
        {
          "id": 42,
          "company": "Example GmbH",
          "role": "QA Engineer",
          "status": "Rejected",
          "next_action": "Follow up tomorrow",
          "follow_up_date": "2026-07-20",
          "rejection_reason": "Position closed",
          "admin": true
        }
        """
    )

    payload = builder(parsed, default_application_date=date(2026, 7, 18))

    assert payload["status"] == "Rejected"
    assert payload["next_action"] == "No action"
    assert payload["follow_up_date"] == ""
    assert payload["rejection_reason"] == "Position closed"
    assert payload["application_date"] == "2026-07-18"
    assert "id" not in payload
    assert "admin" not in payload


def test_build_payload_keeps_optional_fields_empty() -> None:
    builder = getattr(application_note_parser, "build_application_payload", None)
    assert callable(builder), "application import payload builder should be independently testable"
    parsed = parse_application_note('{"company": "Example GmbH", "role": "QA Engineer"}')

    payload = builder(parsed, default_application_date=date(2026, 7, 18))

    assert payload["application_date"] == "2026-07-18"
    assert payload["contact"] == ""
    assert payload["source_link"] == ""
    assert payload["notes"] == ""
