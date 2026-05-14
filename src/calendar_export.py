from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from src.models import CLOSED_STATUSES


@dataclass(frozen=True)
class CalendarItem:
    application_id: int
    event_type: str
    event_date: date
    company: str
    role: str
    location: str
    summary: str
    description: str


def build_calendar_items(applications: list[dict[str, Any]]) -> list[CalendarItem]:
    items: list[CalendarItem] = []

    for application in applications:
        event_date = _parse_date(application.get("follow_up_date"))
        if event_date is None:
            continue

        status = _text(application.get("status")) or "Applied"
        if status in CLOSED_STATUSES and status != "Offer":
            continue

        event_type = _calendar_event_type(status)
        items.append(
            CalendarItem(
                application_id=_application_id(application),
                event_type=event_type,
                event_date=event_date,
                company=_text(application.get("company")) or "Unknown company",
                role=_text(application.get("role")) or "Unknown role",
                location=_text(application.get("location")),
                summary=_event_summary(application, event_type),
                description=_event_description(application, event_type),
            )
        )

    return sorted(items, key=lambda item: (item.event_date, item.company, item.role, item.event_type))


def build_ics_calendar(
    items: list[CalendarItem],
    *,
    calendar_name: str = "CareerOps Tracker",
    generated_at: datetime | None = None,
) -> str:
    timestamp = (generated_at or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CareerOps Tracker//Job Search Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape_ics_text(calendar_name)}",
    ]

    for item in items:
        lines.extend(_ics_event_lines(item, timestamp))

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def build_calendar_text_block(items: list[CalendarItem]) -> str:
    if not items:
        return ""

    lines = []
    for item in items:
        location = f" | {item.location}" if item.location else ""
        lines.append(
            f"{item.event_date.isoformat()} | {item.event_type} | "
            f"{item.company} - {item.role}{location}\n"
            f"Action: {item.summary}\n"
            f"Notes: {item.description}"
        )
    return "\n\n".join(lines)


def calendar_items_to_rows(items: list[CalendarItem]) -> list[dict[str, str | int]]:
    return [
        {
            "application_id": item.application_id,
            "event_date": item.event_date.isoformat(),
            "event_type": item.event_type,
            "company": item.company,
            "role": item.role,
            "location": item.location,
            "summary": item.summary,
        }
        for item in items
    ]


def _ics_event_lines(item: CalendarItem, timestamp: str) -> list[str]:
    start = item.event_date.strftime("%Y%m%d")
    end = (item.event_date + timedelta(days=1)).strftime("%Y%m%d")
    uid = f"careerops-{item.application_id}-{_slug(item.event_type)}-{start}@careerops-tracker"

    return [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{timestamp}",
        f"DTSTART;VALUE=DATE:{start}",
        f"DTEND;VALUE=DATE:{end}",
        f"SUMMARY:{_escape_ics_text(item.summary)}",
        f"DESCRIPTION:{_escape_ics_text(item.description)}",
        f"CATEGORIES:{_escape_ics_text(item.event_type)}",
        f"LOCATION:{_escape_ics_text(item.location)}",
        "END:VEVENT",
    ]


def _calendar_event_type(status: str) -> str:
    if status == "Interview Scheduled":
        return "Interview"
    if status == "Assessment":
        return "Assessment"
    if status == "Offer":
        return "Offer follow-up"
    return "Follow-up"


def _event_summary(application: dict[str, Any], event_type: str) -> str:
    company = _text(application.get("company")) or "Unknown company"
    role = _text(application.get("role")) or "Unknown role"
    if event_type == "Interview":
        return f"Interview: {company} - {role}"
    if event_type == "Assessment":
        return f"Assessment deadline: {company} - {role}"
    if event_type == "Offer follow-up":
        return f"Offer follow-up: {company} - {role}"
    return f"Follow up: {company} - {role}"


def _event_description(application: dict[str, Any], event_type: str) -> str:
    status = _text(application.get("status")) or "Applied"
    next_action = _text(application.get("next_action"))
    source_link = _text(application.get("source_link"))
    contact = _text(application.get("contact"))

    default_action = {
        "Interview": "Prepare interview notes and confirm logistics.",
        "Assessment": "Complete the assessment and check submission requirements.",
        "Offer follow-up": "Review offer details and prepare next response.",
        "Follow-up": "Send or prepare a polite follow-up.",
    }[event_type]

    parts = [
        f"Status: {status}",
        f"Recommended action: {next_action or default_action}",
    ]
    if contact:
        parts.append(f"Contact: {contact}")
    if source_link:
        parts.append(f"Source: {source_link}")
    return "\n".join(parts)


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _application_id(application: dict[str, Any]) -> int:
    try:
        return int(application["id"])
    except (KeyError, TypeError, ValueError):
        return 0


def _escape_ics_text(value: object) -> str:
    text = str(value or "")
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _slug(value: str) -> str:
    return "-".join(part for part in value.casefold().split() if part)


def _text(value: object) -> str:
    return str(value or "").strip()
