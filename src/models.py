from __future__ import annotations

from dataclasses import dataclass


STATUS_OPTIONS = [
    "Saved",
    "Applied",
    "Confirmation Received",
    "Interview Scheduled",
    "Assessment",
    "Offer",
    "Rejected",
    "No Response",
    "Follow-up Needed",
]

CLOSED_STATUSES = {"Rejected", "Offer"}

APPLICATION_COLUMNS = [
    "company",
    "role",
    "location",
    "application_date",
    "status",
    "source_link",
    "contact",
    "notes",
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

