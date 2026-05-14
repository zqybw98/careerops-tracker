from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from src.config_loader import get_reminder_config
from src.models import APPLICATION_COLUMNS, CLOSED_STATUSES

BulkAction = Literal["archive", "mark_no_response", "set_follow_up"]

ARCHIVED_NEXT_ACTION = "Archived from active pipeline."
NO_RESPONSE_NEXT_ACTION = "Marked as no response after review."


def filter_applications(
    applications: list[dict[str, Any]],
    *,
    statuses: list[str] | set[str] | tuple[str, ...] | None = None,
    company_query: str = "",
    source_query: str = "",
    start_date: date | None = None,
    end_date: date | None = None,
    stale_only: bool = False,
    today: date | None = None,
) -> list[dict[str, Any]]:
    status_filter = set(statuses or [])
    normalized_company_query = _normalize_search_text(company_query)
    normalized_source_query = _normalize_search_text(source_query)
    current_date = today or date.today()

    filtered: list[dict[str, Any]] = []
    for application in applications:
        if status_filter and str(application.get("status", "")) not in status_filter:
            continue
        if normalized_company_query and not _matches_query(
            application,
            normalized_company_query,
            ["company", "role"],
        ):
            continue
        if normalized_source_query and not _matches_query(
            application,
            normalized_source_query,
            ["source_link", "contact", "notes"],
        ):
            continue
        if not _matches_date_range(application, start_date=start_date, end_date=end_date):
            continue
        if stale_only and not is_stale_application(application, today=current_date):
            continue
        filtered.append(application)

    return filtered


def is_stale_application(application: dict[str, Any], *, today: date | None = None) -> bool:
    current_date = today or date.today()
    status = str(application.get("status", ""))
    if status in CLOSED_STATUSES or status == "No Response":
        return False

    follow_up_date = parse_date(application.get("follow_up_date"))
    if follow_up_date and follow_up_date <= current_date:
        return True

    application_date = parse_date(application.get("application_date"))
    if not application_date:
        return False

    stale_rule = get_reminder_config()["rules"]["stale_application"]
    stale_statuses = set(stale_rule.get("statuses", []))
    minimum_days_open = int(stale_rule.get("minimum_days_open", 14))
    return status in stale_statuses and (current_date - application_date).days >= minimum_days_open


def build_bulk_update_payload(
    application: dict[str, Any],
    action: BulkAction,
    *,
    follow_up_date: date | None = None,
) -> dict[str, Any]:
    payload = {column: application.get(column, "") for column in APPLICATION_COLUMNS}

    if action == "archive":
        payload["status"] = "No Response"
        payload["next_action"] = ARCHIVED_NEXT_ACTION
        payload["follow_up_date"] = ""
        return payload

    if action == "mark_no_response":
        payload["status"] = "No Response"
        payload["next_action"] = NO_RESPONSE_NEXT_ACTION
        payload["follow_up_date"] = ""
        return payload

    if action == "set_follow_up":
        if follow_up_date is None:
            raise ValueError("follow_up_date is required for set_follow_up.")
        payload["follow_up_date"] = follow_up_date.isoformat()
        if not str(payload.get("next_action", "")).strip():
            payload["next_action"] = f"Follow up on {follow_up_date.isoformat()}."
        return payload

    raise ValueError(f"Unsupported bulk action: {action}")


def parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _matches_date_range(
    application: dict[str, Any],
    *,
    start_date: date | None,
    end_date: date | None,
) -> bool:
    application_date = parse_date(application.get("application_date"))
    if start_date and (not application_date or application_date < start_date):
        return False
    return not (end_date and (not application_date or application_date > end_date))


def _matches_query(application: dict[str, Any], normalized_query: str, fields: list[str]) -> bool:
    haystack = " ".join(str(application.get(field, "")) for field in fields)
    return normalized_query in _normalize_search_text(haystack)


def _normalize_search_text(value: object) -> str:
    return " ".join(str(value or "").casefold().split())
