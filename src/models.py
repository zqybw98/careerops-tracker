from __future__ import annotations

from dataclasses import dataclass

STATUS_OPTIONS = [
    "Applied",
    "Waiting",
    "Action Needed",
    "Interview / Assessment",
    "Rejected",
]

CLOSED_STATUSES = {"Rejected"}
WAITING_PIPELINE_STATUSES = {"Applied", "Waiting", "Interview / Assessment"}

LEGACY_STATUS_MAP = {
    "Saved": "Applied",
    "Confirmation Received": "Waiting",
    "Follow-up Needed": "Action Needed",
    "Assessment": "Interview / Assessment",
    "Interview Scheduled": "Interview / Assessment",
    "No Response": "Waiting",
    "Offer": "Action Needed",
    "Applied": "Applied",
    "Rejected": "Rejected",
}

STATUS_KEYWORD_MAP = {
    "Rejected": (
        "rejected",
        "rejection",
        "absage",
        "abgelehnt",
        "leider",
        "unfortunately",
        "not selected",
        "not moving forward",
        "progress with other candidates",
        "nicht weiter",
        "nicht berücksichtigt",
        "nicht beruecksichtigt",
    ),
    "Applied": (
        "applied",
        "submitted",
        "beworben",
        "application sent",
        "bewerbung abgeschickt",
        "erfolgreich abgeschickt",
        "eingereicht",
    ),
    "Waiting": (
        "confirmation",
        "confirmed",
        "eingangsbestätigung",
        "received your application",
        "application received",
        "no response",
        "keine rückmeldung",
        "keine rueckmeldung",
        "process is delayed",
        "delayed",
        "verzögert",
        "verzoegert",
    ),
    "Interview / Assessment": (
        "interview",
        "gespräch",
        "gespraech",
        "termin",
        "meeting",
        "vorstellungsgespräch",
        "vorstellungsgespraech",
        "assessment",
        "coding test",
        "challenge",
        "test",
        "aufgabe",
    ),
    "Action Needed": (
        "follow up",
        "follow-up",
        "nachfassen",
        "reminder",
        "offer",
        "angebot",
        "reply",
        "respond",
    ),
}

DEFAULT_NEXT_ACTION_BY_STATUS = {
    "Applied": "Wait",
    "Waiting": "Wait",
    "Action Needed": "Review and act today.",
    "Interview / Assessment": "Prepare for the interview or assessment.",
    "Rejected": "No action",
}

APPLICATION_COLUMNS = [
    "company",
    "role",
    "location",
    "application_date",
    "status",
    "source_link",
    "contact",
    "notes",
    "rejection_reason",
    "next_action",
    "follow_up_date",
]


@dataclass(frozen=True)
class EmailClassification:
    category: str
    confidence: float
    suggested_status: str
    suggested_next_action: str
    suggested_follow_up_days: int | None
    matched_keywords: list[str]


def normalize_status(value: object) -> str:
    status = str(value or "").strip()
    if not status:
        return "Applied"
    if status in STATUS_OPTIONS:
        return status
    if status in LEGACY_STATUS_MAP:
        return LEGACY_STATUS_MAP[status]

    normalized = _normalized_status_text(status)
    for legacy_status, mapped_status in LEGACY_STATUS_MAP.items():
        if normalized == _normalized_status_text(legacy_status):
            return mapped_status
    for mapped_status, keywords in STATUS_KEYWORD_MAP.items():
        if any(_normalized_status_text(keyword) in normalized for keyword in keywords):
            return mapped_status
    return "Applied"


def _normalized_status_text(value: object) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").replace("-", " ").split())


def apply_status_business_rules(payload: dict[str, str]) -> dict[str, str]:
    cleaned = dict(payload)
    status = normalize_status(cleaned.get("status", ""))
    cleaned["status"] = status

    if status == "Rejected":
        cleaned["next_action"] = "No action"
        cleaned["follow_up_date"] = ""
        return cleaned

    if not str(cleaned.get("next_action", "") or "").strip():
        cleaned["next_action"] = DEFAULT_NEXT_ACTION_BY_STATUS.get(status, "")

    return cleaned
