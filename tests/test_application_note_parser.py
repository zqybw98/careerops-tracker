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
