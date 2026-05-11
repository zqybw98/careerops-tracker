from __future__ import annotations

import base64
import html
import importlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_GMAIL_QUERY = (
    "newer_than:60d "
    "(application OR bewerbung OR interview OR rejection OR absage OR recruiter OR assessment OR coding "
    "OR 申请 OR 面试 OR 拒信 OR 测评)"
)


class GmailSyncError(RuntimeError):
    """Base exception for optional Gmail sync failures."""


class GmailDependencyError(GmailSyncError):
    """Raised when optional Google API dependencies are not installed."""


class GmailConfigurationError(GmailSyncError):
    """Raised when local Gmail OAuth credentials are missing or invalid."""


@dataclass(frozen=True)
class GmailEmail:
    gmail_id: str
    thread_id: str
    subject: str
    sender: str
    date: str
    snippet: str
    body: str


def fetch_recruiting_emails(
    credentials_path: str = "credentials.json",
    token_path: str = "token.json",
    query: str = DEFAULT_GMAIL_QUERY,
    max_results: int = 10,
) -> list[dict[str, str]]:
    service = _build_gmail_service(credentials_path=credentials_path, token_path=token_path)
    response = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    message_refs = response.get("messages", [])

    emails: list[dict[str, str]] = []
    for message_ref in message_refs:
        message = service.users().messages().get(userId="me", id=message_ref["id"], format="full").execute()
        emails.append(parse_gmail_message(message))
    return emails


def parse_gmail_message(message: dict[str, Any]) -> dict[str, str]:
    payload = message.get("payload", {})
    headers = _extract_headers(payload)
    email = GmailEmail(
        gmail_id=str(message.get("id", "")),
        thread_id=str(message.get("threadId", "")),
        subject=headers.get("subject", ""),
        sender=headers.get("from", ""),
        date=headers.get("date", ""),
        snippet=str(message.get("snippet", "")),
        body=_extract_body(payload) or str(message.get("snippet", "")),
    )
    return asdict(email)


def _build_gmail_service(credentials_path: str, token_path: str) -> Any:
    google_modules = _load_google_modules()
    credentials_file = Path(credentials_path)
    token_file = Path(token_path)

    if not credentials_file.exists():
        raise GmailConfigurationError(
            f"Missing {credentials_file}. Create a Google OAuth desktop credential and save it locally."
        )

    credentials = None
    if token_file.exists():
        credentials = google_modules["Credentials"].from_authorized_user_file(str(token_file), SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(google_modules["Request"]())
        else:
            flow = google_modules["InstalledAppFlow"].from_client_secrets_file(str(credentials_file), SCOPES)
            credentials = flow.run_local_server(port=0)
        token_file.write_text(credentials.to_json(), encoding="utf-8")

    return google_modules["build"]("gmail", "v1", credentials=credentials)


def _load_google_modules() -> dict[str, Any]:
    try:
        credentials_module = importlib.import_module("google.oauth2.credentials")
        requests_module = importlib.import_module("google.auth.transport.requests")
        flow_module = importlib.import_module("google_auth_oauthlib.flow")
        discovery_module = importlib.import_module("googleapiclient.discovery")
    except ImportError as error:
        raise GmailDependencyError(
            "Optional Gmail dependencies are not installed. Run: pip install -r requirements-gmail.txt"
        ) from error

    return {
        "Credentials": credentials_module.Credentials,
        "Request": requests_module.Request,
        "InstalledAppFlow": flow_module.InstalledAppFlow,
        "build": discovery_module.build,
    }


def _extract_headers(payload: dict[str, Any]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for header in payload.get("headers", []):
        name = str(header.get("name", "")).lower()
        if name in {"subject", "from", "date"}:
            headers[name] = str(header.get("value", ""))
    return headers


def _extract_body(payload: dict[str, Any]) -> str:
    plain_text = _find_part_body(payload, "text/plain")
    if plain_text:
        return _normalize_body(plain_text)

    html_text = _find_part_body(payload, "text/html")
    if html_text:
        return _normalize_body(_strip_html(html_text))

    return ""


def _find_part_body(payload: dict[str, Any], mime_type: str) -> str:
    if payload.get("mimeType") == mime_type:
        data = payload.get("body", {}).get("data", "")
        return _decode_base64url(data)

    for part in payload.get("parts", []):
        body = _find_part_body(part, mime_type)
        if body:
            return body
    return ""


def _decode_base64url(data: object) -> str:
    encoded = str(data or "")
    if not encoded:
        return ""
    padding = "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(f"{encoded}{padding}").decode("utf-8", errors="ignore")


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(without_tags)


def _normalize_body(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
