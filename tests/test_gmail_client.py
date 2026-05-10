import base64

from src.gmail_client import parse_gmail_message


def _encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def test_parse_gmail_message_extracts_headers_and_plain_text_body() -> None:
    message = {
        "id": "msg-1",
        "threadId": "thread-1",
        "snippet": "Fallback snippet",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Interview invitation"},
                {"name": "From", "value": "Recruiter <recruiter@example.com>"},
                {"name": "Date", "value": "Mon, 04 May 2026 10:00:00 +0200"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _encode("We would like to invite you to an interview.")},
        },
    }

    parsed = parse_gmail_message(message)

    assert parsed["gmail_id"] == "msg-1"
    assert parsed["thread_id"] == "thread-1"
    assert parsed["subject"] == "Interview invitation"
    assert parsed["sender"] == "Recruiter <recruiter@example.com>"
    assert parsed["date"] == "Mon, 04 May 2026 10:00:00 +0200"
    assert parsed["body"] == "We would like to invite you to an interview."


def test_parse_gmail_message_prefers_plain_text_over_html() -> None:
    message = {
        "id": "msg-2",
        "threadId": "thread-2",
        "snippet": "Snippet",
        "payload": {
            "headers": [{"name": "Subject", "value": "Application update"}],
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _encode("<p>HTML rejection</p>")},
                },
                {
                    "mimeType": "text/plain",
                    "body": {"data": _encode("Plain rejection")},
                },
            ],
        },
    }

    parsed = parse_gmail_message(message)

    assert parsed["body"] == "Plain rejection"


def test_parse_gmail_message_strips_html_when_plain_text_is_missing() -> None:
    message = {
        "id": "msg-3",
        "threadId": "thread-3",
        "snippet": "Snippet",
        "payload": {
            "headers": [{"name": "Subject", "value": "Rejected"}],
            "mimeType": "text/html",
            "body": {"data": _encode("<p>Unfortunately&nbsp;we cannot continue.</p>")},
        },
    }

    parsed = parse_gmail_message(message)

    assert parsed["body"] == "Unfortunately we cannot continue."
