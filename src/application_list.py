from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, Literal

from src.models import APPLICATION_COLUMNS, apply_status_business_rules, normalize_status

QuickFilter = Literal["all", "active", "interview", "waiting", "rejected"]


def filter_application_list(
    applications: Sequence[dict[str, Any]],
    *,
    search_query: str = "",
    statuses: Sequence[str] | None = None,
    location: str = "",
    quick_filter: QuickFilter = "all",
) -> list[dict[str, Any]]:
    query = search_query.casefold().strip()
    selected_statuses = {normalize_status(status) for status in statuses or []}
    selected_location = location.casefold().strip()
    filtered: list[dict[str, Any]] = []

    for application in applications:
        status = normalize_status(application.get("status"))
        if query and query not in _company_role_text(application):
            continue
        if selected_statuses and status not in selected_statuses:
            continue
        if selected_location and str(application.get("location", "") or "").casefold().strip() != selected_location:
            continue
        if not _matches_quick_filter(status, quick_filter):
            continue
        filtered.append(application)

    return filtered


def sort_application_list(applications: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        applications,
        key=lambda application: (
            str(application.get("application_date", "") or ""),
            int(application.get("id") or 0),
        ),
        reverse=True,
    )


def count_quick_filters(applications: Sequence[dict[str, Any]]) -> dict[str, int]:
    statuses = [normalize_status(application.get("status")) for application in applications]
    return {
        "all": len(applications),
        "active": sum(status != "Rejected" for status in statuses),
        "interview": statuses.count("Interview / Assessment"),
        "waiting": statuses.count("Waiting"),
        "rejected": statuses.count("Rejected"),
    }


def build_list_rows(
    applications: Sequence[dict[str, Any]],
    *,
    include_source: bool = False,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for application in applications:
        row = {
            "Company": _text(application.get("company")),
            "Role": _text(application.get("role")),
            "Location": _text(application.get("location")),
            "Status": normalize_status(application.get("status")),
            "Applied": _text(application.get("application_date")),
            "Follow-up": _text(application.get("follow_up_date")),
        }
        if include_source:
            row["Source"] = _text(application.get("source_link"))
        rows.append(row)
    return rows


def build_create_application_payload(
    *,
    company: str,
    role: str,
    location: str,
    status: str,
    application_date: date,
    source_link: str = "",
    contact: str = "",
    follow_up_date: date | None = None,
    next_action: str = "",
    notes: str = "",
    rejection_reason: str = "",
) -> dict[str, str]:
    payload = {
        "company": company.strip(),
        "role": role.strip(),
        "location": location.strip(),
        "application_date": application_date.isoformat(),
        "status": status,
        "source_link": source_link.strip(),
        "contact": contact.strip(),
        "notes": notes.strip(),
        "rejection_reason": rejection_reason.strip(),
        "next_action": next_action.strip(),
        "follow_up_date": follow_up_date.isoformat() if follow_up_date else "",
    }
    return apply_status_business_rules(payload)


def build_edit_application_payload(
    existing: dict[str, Any],
    *,
    status: str,
    location: str,
    application_date: date,
    follow_up_date: date | None,
    next_action: str,
    notes: str,
    source_link: str,
    contact: str,
    rejection_reason: str,
) -> dict[str, str]:
    payload = {column: _text(existing.get(column)) for column in APPLICATION_COLUMNS}
    payload.update(
        {
            "location": location.strip(),
            "application_date": application_date.isoformat(),
            "status": status,
            "source_link": source_link.strip(),
            "contact": contact.strip(),
            "notes": notes.strip(),
            "rejection_reason": rejection_reason.strip(),
            "next_action": next_action.strip(),
            "follow_up_date": follow_up_date.isoformat() if follow_up_date else "",
        }
    )
    return apply_status_business_rules(payload)


def _company_role_text(application: dict[str, Any]) -> str:
    return " ".join(
        [
            _text(application.get("company")),
            _text(application.get("role")),
        ]
    ).casefold()


def _matches_quick_filter(status: str, quick_filter: QuickFilter) -> bool:
    if quick_filter == "all":
        return True
    if quick_filter == "active":
        return status != "Rejected"
    if quick_filter == "interview":
        return status == "Interview / Assessment"
    if quick_filter == "waiting":
        return status == "Waiting"
    return status == "Rejected"


def _text(value: object) -> str:
    return str(value or "").strip()
