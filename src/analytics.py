from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

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

SOURCE_PATTERNS = (
    ("LinkedIn", ("linkedin",)),
    ("StepStone", ("stepstone",)),
    ("Indeed", ("indeed",)),
    ("Xing", ("xing",)),
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


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None
