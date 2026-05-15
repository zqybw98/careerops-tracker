from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any

from src.config_loader import get_email_parser_config
from src.models import CLOSED_STATUSES

RESPONDED_STATUSES = {
    "Confirmation Received",
    "Interview Scheduled",
    "Assessment",
    "Offer",
    "Rejected",
    "Follow-up Needed",
}

INTERVIEW_CONVERSION_STATUSES = {
    "Interview Scheduled",
    "Assessment",
    "Offer",
}

FUNNEL_STAGES = (
    (
        "Submitted",
        {
            "Applied",
            "Confirmation Received",
            "Interview Scheduled",
            "Assessment",
            "Offer",
            "Rejected",
            "No Response",
            "Follow-up Needed",
        },
    ),
    ("First response", RESPONDED_STATUSES),
    ("Interview", {"Interview Scheduled", "Assessment", "Offer"}),
    ("Assessment", {"Assessment", "Offer"}),
    ("Offer", {"Offer"}),
)

UNSPECIFIED_REJECTION_REASON = "Unspecified / not recorded"
CUSTOM_REJECTION_REASON = "Other / custom reason"

SOURCE_PATTERNS = (
    ("LinkedIn", ("linkedin",)),
    ("StepStone", ("stepstone",)),
    ("Indeed", ("indeed",)),
    ("Xing", ("xing",)),
    ("Bundesagentur fuer Arbeit", ("arbeitsagentur", "jobboerse.arbeitsagentur")),
    ("Stellenwerk", ("stellenwerk",)),
    ("Absolventa", ("absolventa",)),
    ("Meinestadt", ("meinestadt",)),
    ("Honeypot", ("honeypot",)),
    ("Glassdoor", ("glassdoor",)),
    ("Join", ("join.com",)),
    (
        "Company Career Page / ATS",
        (
            "workday",
            "greenhouse",
            "lever",
            "successfactors",
            "smartrecruiters",
            "personio",
            "ashby",
            "bamboohr",
        ),
    ),
)

ROLE_TYPE_PATTERNS = (
    ("QA / Testing", ("qa", "quality", "test", "tester", "testing", "softwaretester", "test automation")),
    ("Technical Operations", ("operations", "technical operations", "support", "service desk", "it support")),
    ("Data / AI", ("data", "ai", "machine learning", "analytics", "business intelligence")),
    ("Software Engineering", ("software", "developer", "entwickler", "entwicklung", "backend", "frontend", "engineer")),
    ("Robotics / Mechatronics", ("robotics", "mechatronics", "mechanical", "automation engineer")),
)


def build_pipeline_health(
    applications: list[dict[str, Any]],
    today: date | None = None,
) -> dict[str, int | float]:
    reference_date = today or date.today()
    total = len(applications)
    responded = sum(1 for item in applications if _status(item) in RESPONDED_STATUSES)
    converted = sum(1 for item in applications if _status(item) in INTERVIEW_CONVERSION_STATUSES)

    active_waiting_days = [
        days
        for item in applications
        if _is_open(item)
        for days in [_days_since_application(item, reference_date)]
        if days is not None
    ]
    stale_open = sum(1 for days in active_waiting_days if days >= 14)

    return {
        "response_rate": _safe_rate(responded, total),
        "interview_conversion_rate": _safe_rate(converted, total),
        "average_active_waiting_days": round(sum(active_waiting_days) / len(active_waiting_days), 1)
        if active_waiting_days
        else 0.0,
        "stale_open_applications": stale_open,
    }


def build_applications_per_month(applications: list[dict[str, Any]]) -> list[dict[str, int | str]]:
    monthly_counts: dict[tuple[int, int], int] = defaultdict(int)

    for item in applications:
        application_date = _parse_date(item.get("application_date"))
        if application_date is None:
            continue
        monthly_counts[(application_date.year, application_date.month)] += 1

    return [
        {
            "month": date(year, month, 1).strftime("%b %Y"),
            "applications": count,
        }
        for (year, month), count in sorted(monthly_counts.items())
    ]


def build_response_rate_by_source(applications: list[dict[str, Any]]) -> list[dict[str, int | float | str]]:
    totals: dict[str, int] = defaultdict(int)
    responses: dict[str, int] = defaultdict(int)

    for item in applications:
        source = infer_source(item)
        totals[source] += 1
        if _status(item) in RESPONDED_STATUSES:
            responses[source] += 1

    return [
        {
            "source": source,
            "applications": total,
            "responses": responses[source],
            "response_rate": _safe_rate(responses[source], total),
        }
        for source, total in sorted(totals.items(), key=lambda value: (-value[1], value[0]))
    ]


def build_interview_conversion_by_role_type(applications: list[dict[str, Any]]) -> list[dict[str, int | float | str]]:
    totals: dict[str, int] = defaultdict(int)
    conversions: dict[str, int] = defaultdict(int)

    for item in applications:
        role_type = infer_role_type(item.get("role", ""))
        totals[role_type] += 1
        if _status(item) in INTERVIEW_CONVERSION_STATUSES:
            conversions[role_type] += 1

    return [
        {
            "role_type": role_type,
            "applications": total,
            "interview_or_assessment": conversions[role_type],
            "conversion_rate": _safe_rate(conversions[role_type], total),
        }
        for role_type, total in sorted(totals.items(), key=lambda value: (-value[1], value[0]))
    ]


def build_average_waiting_days_by_company(
    applications: list[dict[str, Any]],
    today: date | None = None,
    limit: int = 10,
) -> list[dict[str, float | int | str]]:
    reference_date = today or date.today()
    grouped_days: dict[str, list[int]] = defaultdict(list)

    for item in applications:
        if not _is_open(item):
            continue
        waiting_days = _days_since_application(item, reference_date)
        if waiting_days is None:
            continue
        grouped_days[str(item.get("company") or "Unknown").strip() or "Unknown"].append(waiting_days)

    rows: list[dict[str, float | int | str]] = []
    for company, company_days in grouped_days.items():
        rows.append(
            {
                "company": company,
                "open_applications": len(company_days),
                "average_waiting_days": round(sum(company_days) / len(company_days), 1),
            }
        )
    return sorted(rows, key=_waiting_days_sort_key)[:limit]


def build_stale_pipeline_breakdown(
    applications: list[dict[str, Any]],
    today: date | None = None,
) -> list[dict[str, int | str]]:
    reference_date = today or date.today()
    counts: dict[tuple[str, str], int] = defaultdict(int)

    for item in applications:
        if not _is_open(item):
            continue
        days = _days_since_application(item, reference_date)
        bucket = _stale_bucket(days)
        counts[(bucket, _status(item))] += 1

    bucket_order = {
        "Fresh (0-6 days)": 0,
        "Needs follow-up (7-13 days)": 1,
        "Stale (14+ days)": 2,
        "No application date": 3,
    }
    return [
        {
            "bucket": bucket,
            "status": status,
            "applications": count,
        }
        for (bucket, status), count in sorted(
            counts.items(),
            key=lambda value: (bucket_order[value[0][0]], value[0][1]),
        )
    ]


def build_saved_vs_applied_summary(applications: list[dict[str, Any]]) -> list[dict[str, int | str]]:
    saved = sum(1 for item in applications if _status(item) == "Saved")
    submitted = len(applications) - saved
    return [
        {"stage": "Saved only", "applications": saved},
        {"stage": "Submitted / active", "applications": submitted},
    ]


def build_time_to_first_response_by_source(
    applications: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, float | int | str]]:
    response_dates = _first_response_dates_by_application(applications, events)
    grouped_days: dict[str, list[int]] = defaultdict(list)

    for application in applications:
        application_id = _application_id(application)
        application_date = _parse_date(application.get("application_date"))
        if application_id is None:
            continue
        response_date = response_dates.get(application_id)
        if application_date is None or response_date is None:
            continue
        grouped_days[infer_source(application)].append(max((response_date - application_date).days, 0))

    rows: list[dict[str, float | int | str]] = [
        {
            "source": source,
            "responses": len(days),
            "average_days_to_first_response": round(sum(days) / len(days), 1),
        }
        for source, days in grouped_days.items()
    ]
    return sorted(rows, key=lambda row: (-int(row["responses"]), float(row["average_days_to_first_response"])))


def build_rejection_reason_breakdown(applications: list[dict[str, Any]]) -> list[dict[str, int | str]]:
    counts: dict[str, int] = defaultdict(int)

    for application in applications:
        if _status(application) != "Rejected":
            continue
        reason = infer_rejection_reason(application.get("rejection_reason") or application.get("notes") or "")
        counts[reason] += 1

    return [
        {"rejection_reason": reason, "applications": count}
        for reason, count in sorted(counts.items(), key=lambda value: (-value[1], value[0]))
    ]


def build_follow_up_effectiveness(
    applications: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, float | int | str]]:
    follow_up_application_ids: set[int] = set()
    for event in events:
        application_id = _event_application_id(event)
        if (
            application_id is not None
            and event.get("event_type") == "follow_up_date_changed"
            and str(event.get("new_value") or "").strip()
        ):
            follow_up_application_ids.add(application_id)

    for application in applications:
        application_id = _application_id(application)
        if application_id is not None and str(application.get("follow_up_date") or "").strip():
            follow_up_application_ids.add(application_id)

    counts: dict[str, int] = defaultdict(int)
    applications_by_id = {
        application_id: application
        for application in applications
        for application_id in [_application_id(application)]
        if application_id is not None
    }
    for application_id in follow_up_application_ids:
        selected_application = applications_by_id.get(application_id)
        if selected_application is None:
            continue
        counts[_follow_up_outcome(selected_application)] += 1

    total = sum(counts.values())
    return [
        {
            "outcome": outcome,
            "applications": count,
            "share": _safe_rate(count, total),
        }
        for outcome, count in sorted(counts.items(), key=lambda value: (-value[1], value[0]))
    ]


def build_interview_to_offer_funnel(
    applications: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> list[dict[str, float | int | str]]:
    status_history = _status_history_by_application(events)
    stage_counts: dict[str, int] = {stage: 0 for stage, _ in FUNNEL_STAGES}

    for application in applications:
        application_id = _application_id(application)
        statuses = status_history.get(application_id, set()) if application_id is not None else set()
        statuses = statuses | {_status(application)}
        for stage, stage_statuses in FUNNEL_STAGES:
            if statuses & stage_statuses:
                stage_counts[stage] += 1

    submitted = stage_counts["Submitted"]
    return [
        {
            "stage": stage,
            "applications": stage_counts[stage],
            "conversion_rate": _safe_rate(stage_counts[stage], submitted),
        }
        for stage, _ in FUNNEL_STAGES
    ]


def build_channel_role_type_matrix(applications: list[dict[str, Any]]) -> list[dict[str, float | int | str]]:
    groups: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"applications": 0, "responses": 0, "interviews": 0}
    )

    for application in applications:
        key = (infer_source(application), infer_role_type(application.get("role", "")))
        groups[key]["applications"] += 1
        if _status(application) in RESPONDED_STATUSES:
            groups[key]["responses"] += 1
        if _status(application) in INTERVIEW_CONVERSION_STATUSES:
            groups[key]["interviews"] += 1

    rows: list[dict[str, float | int | str]] = []
    for (source, role_type), values in groups.items():
        applications_count = values["applications"]
        rows.append(
            {
                "source": source,
                "role_type": role_type,
                "applications": applications_count,
                "response_rate": _safe_rate(values["responses"], applications_count),
                "interview_rate": _safe_rate(values["interviews"], applications_count),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["applications"]), str(row["source"]), str(row["role_type"])))


def infer_source(application: dict[str, Any]) -> str:
    source_link = str(application.get("source_link") or "").lower()
    notes = str(application.get("notes") or "").lower()
    source_text = f"{source_link} {notes}"

    for label, patterns in SOURCE_PATTERNS:
        if any(pattern in source_text for pattern in patterns):
            return label

    if source_link:
        return "Company Career Page / ATS"
    return "Manual / Unknown"


def infer_role_type(role: object) -> str:
    role_text = str(role or "").lower()
    for label, patterns in ROLE_TYPE_PATTERNS:
        if any(pattern in role_text for pattern in patterns):
            return label
    return "Other"


def infer_rejection_reason(reason_text: object) -> str:
    normalized_reason = str(reason_text or "").casefold().strip()
    if not normalized_reason:
        return UNSPECIFIED_REJECTION_REASON

    for rule in get_email_parser_config()["rejection_reason_rules"]:
        if any(pattern.casefold() in normalized_reason for pattern in rule["patterns"]):
            return rule["reason"]
    return CUSTOM_REJECTION_REASON


def _waiting_days_sort_key(row: dict[str, float | int | str]) -> tuple[float, str]:
    return -float(row["average_waiting_days"]), str(row["company"])


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 2)


def _status(application: dict[str, Any]) -> str:
    return str(application.get("status") or "Applied")


def _is_open(application: dict[str, Any]) -> bool:
    return _status(application) not in CLOSED_STATUSES


def _days_since_application(application: dict[str, Any], today: date) -> int | None:
    application_date = _parse_date(application.get("application_date"))
    if application_date is None:
        return None
    return max((today - application_date).days, 0)


def _stale_bucket(days: int | None) -> str:
    if days is None:
        return "No application date"
    if days <= 6:
        return "Fresh (0-6 days)"
    if days <= 13:
        return "Needs follow-up (7-13 days)"
    return "Stale (14+ days)"


def _follow_up_outcome(application: dict[str, Any]) -> str:
    status = _status(application)
    if status == "Offer":
        return "Offer after follow-up"
    if status in {"Interview Scheduled", "Assessment"}:
        return "Interview or assessment"
    if status == "Rejected":
        return "Rejected after follow-up"
    if status == "No Response":
        return "No response / archived"
    if status in {"Confirmation Received", "Follow-up Needed"}:
        return "Response or active follow-up"
    return "Still waiting"


def _first_response_dates_by_application(
    applications: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> dict[int, date]:
    response_dates: dict[int, date] = {}
    for event in sorted(events, key=lambda item: str(item.get("created_at", ""))):
        application_id = _event_application_id(event)
        if application_id is None or application_id in response_dates:
            continue
        if event.get("event_type") == "status_changed" and str(event.get("new_value") or "") in RESPONDED_STATUSES:
            event_date = _parse_datetime_date(event.get("created_at"))
            if event_date is not None:
                response_dates[application_id] = event_date

    for application in applications:
        application_id = _application_id(application)
        if application_id is None or application_id in response_dates:
            continue
        if _status(application) in RESPONDED_STATUSES:
            fallback_date = _parse_datetime_date(application.get("updated_at")) or _parse_datetime_date(
                application.get("created_at")
            )
            if fallback_date is not None:
                response_dates[application_id] = fallback_date

    return response_dates


def _status_history_by_application(events: list[dict[str, Any]]) -> dict[int, set[str]]:
    history: dict[int, set[str]] = defaultdict(set)
    for event in events:
        application_id = _event_application_id(event)
        if application_id is None or event.get("event_type") != "status_changed":
            continue
        new_status = str(event.get("new_value") or "").strip()
        if new_status:
            history[application_id].add(new_status)
    return history


def _application_id(application: dict[str, Any]) -> int | None:
    try:
        return int(application["id"])
    except (KeyError, TypeError, ValueError):
        return None


def _event_application_id(event: dict[str, Any]) -> int | None:
    try:
        return int(event["application_id"])
    except (KeyError, TypeError, ValueError):
        return None


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_datetime_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return _parse_date(value)
