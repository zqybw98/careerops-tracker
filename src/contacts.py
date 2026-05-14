from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from typing import Any
from urllib.parse import urlparse

from src.models import CLOSED_STATUSES

CONTACT_EVENT_TYPES = {
    "application_created",
    "contact_changed",
    "follow_up_date_changed",
    "next_action_changed",
    "source_link_changed",
    "status_changed",
}

CONTACT_TYPE_PRIORITY = {
    "Referral": 4,
    "Hiring Manager": 3,
    "Recruiter": 2,
    "Company / ATS": 1,
    "Other": 0,
}

CHANNEL_PRIORITY = {
    "Referral": 4,
    "LinkedIn": 3,
    "Email": 2,
    "Career Page / ATS": 1,
    "Manual / Unknown": 0,
}


def build_contact_records(
    applications: list[dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    reference_date = today or date.today()
    events_by_application = _events_by_application(events or [])
    groups: dict[str, dict[str, Any]] = {}

    for application in applications:
        seed = _contact_seed(application)
        if seed is None:
            continue

        record = groups.setdefault(
            seed["key"],
            {
                "contact_key": seed["key"],
                "contact": seed["display_name"],
                "name": seed["name"],
                "email": seed["email"],
                "contact_types": Counter(),
                "channels": Counter(),
                "companies": set(),
                "application_ids": [],
                "linked_applications": [],
                "open_applications": 0,
                "follow_up_dates": [],
                "follow_up_needed": False,
                "last_contact_at": "",
            },
        )

        contact_type = infer_contact_type(application)
        channel = infer_contact_channel(application)
        record["contact_types"][contact_type] += 1
        record["channels"][channel] += 1
        record["companies"].add(_text(application.get("company")) or "Unknown")
        record["application_ids"].append(int(application["id"]))
        record["linked_applications"].append(_application_label(application))
        if _is_open(application):
            record["open_applications"] += 1

        follow_up_date = _parse_date(application.get("follow_up_date"))
        if follow_up_date and _is_open(application):
            record["follow_up_dates"].append(follow_up_date)
            record["follow_up_needed"] = True
        if _text(application.get("status")) == "Follow-up Needed":
            record["follow_up_needed"] = True

        last_contact_at = _latest_contact_timestamp(application, events_by_application.get(int(application["id"]), []))
        if last_contact_at and (not record["last_contact_at"] or last_contact_at > record["last_contact_at"]):
            record["last_contact_at"] = last_contact_at

    finalized_records = [_finalize_contact_record(record, reference_date) for record in groups.values()]
    return sorted(finalized_records, key=_contact_sort_key)


def infer_contact_type(application: dict[str, Any]) -> str:
    text = _combined_contact_text(application)
    if any(keyword in text for keyword in ("referral", "referred", "empfehlung", "推荐", "内推")):
        return "Referral"
    if any(keyword in text for keyword in ("hiring manager", "team lead", "manager", "fachbereich", "hiring team")):
        return "Hiring Manager"
    if _text(application.get("source_link")) and not _text(application.get("contact")):
        return "Company / ATS"
    recruiting_keywords = ("recruiter", "recruiting", "talent", "hr", "human resources", "careers", "jobs")
    if any(keyword in text for keyword in recruiting_keywords):
        return "Recruiter"
    return "Other"


def infer_contact_channel(application: dict[str, Any]) -> str:
    text = _combined_contact_text(application)
    if infer_contact_type(application) == "Referral":
        return "Referral"
    if "linkedin" in text:
        return "LinkedIn"
    if _extract_email(_text(application.get("contact"))):
        return "Email"
    if _text(application.get("source_link")):
        return "Career Page / ATS"
    return "Manual / Unknown"


def _contact_seed(application: dict[str, Any]) -> dict[str, str] | None:
    contact = _text(application.get("contact"))
    email = _extract_email(contact)
    source_domain = _source_domain(application)

    if email:
        name = _extract_contact_name(contact, email)
        return {
            "key": f"email:{email.casefold()}",
            "display_name": f"{name} <{email}>" if name else email,
            "name": name,
            "email": email,
        }

    if contact:
        return {
            "key": f"contact:{_identity(contact)}",
            "display_name": contact,
            "name": contact,
            "email": "",
        }

    if source_domain:
        company = _text(application.get("company")) or source_domain
        return {
            "key": f"source:{source_domain}",
            "display_name": f"{company} careers",
            "name": f"{company} careers",
            "email": "",
        }

    return None


def _finalize_contact_record(record: dict[str, Any], today: date) -> dict[str, Any]:
    follow_up_dates: list[date] = record["follow_up_dates"]
    next_follow_up = min(follow_up_dates).isoformat() if follow_up_dates else ""
    follow_up_state = _follow_up_state(record["follow_up_needed"], follow_up_dates, today)
    application_ids = list(dict.fromkeys(record["application_ids"]))

    return {
        "contact_key": record["contact_key"],
        "contact": record["contact"],
        "name": record["name"],
        "email": record["email"],
        "contact_type": _top_counter_label(record["contact_types"], CONTACT_TYPE_PRIORITY),
        "channel": _top_counter_label(record["channels"], CHANNEL_PRIORITY),
        "companies": ", ".join(sorted(record["companies"])),
        "applications": len(application_ids),
        "open_applications": record["open_applications"],
        "follow_up_status": follow_up_state,
        "next_follow_up_date": next_follow_up,
        "last_contact_at": record["last_contact_at"],
        "application_ids": application_ids,
        "linked_applications": " | ".join(record["linked_applications"]),
    }


def _events_by_application(events: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        try:
            application_id = int(event["application_id"])
        except (KeyError, TypeError, ValueError):
            continue
        grouped[application_id].append(event)
    return grouped


def _latest_contact_timestamp(application: dict[str, Any], events: list[dict[str, Any]]) -> str:
    timestamps = [_text(application.get("updated_at")), _text(application.get("created_at"))]
    timestamps.extend(
        _text(event.get("created_at")) for event in events if _text(event.get("event_type")) in CONTACT_EVENT_TYPES
    )
    return max((timestamp for timestamp in timestamps if timestamp), default="")


def _top_counter_label(counter: Counter[str], priority: dict[str, int]) -> str:
    if not counter:
        return "Other"
    return sorted(counter.items(), key=lambda item: (item[1], priority.get(item[0], 0), item[0]), reverse=True)[0][0]


def _follow_up_state(needs_follow_up: bool, follow_up_dates: list[date], today: date) -> str:
    if any(follow_up_date <= today for follow_up_date in follow_up_dates):
        return "Due"
    if follow_up_dates:
        return "Planned"
    if needs_follow_up:
        return "Needed"
    return "None"


def _application_label(application: dict[str, Any]) -> str:
    company = _text(application.get("company")) or "Unknown"
    role = _text(application.get("role")) or "Unknown role"
    status = _text(application.get("status")) or "Applied"
    return f"{company} - {role} ({status})"


def _combined_contact_text(application: dict[str, Any]) -> str:
    return " ".join(
        _text(application.get(field)).casefold() for field in ["contact", "source_link", "notes", "company", "role"]
    )


def _source_domain(application: dict[str, Any]) -> str:
    source_link = _text(application.get("source_link"))
    if not source_link:
        return ""
    parsed = urlparse(source_link)
    return parsed.netloc.casefold().removeprefix("www.") if parsed.netloc else ""


def _extract_email(value: str) -> str:
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", value)
    return match.group(0) if match else ""


def _extract_contact_name(contact: str, email: str) -> str:
    name = contact.replace(email, "").replace("<>", "").replace("<", "").replace(">", "").strip(" -")
    return re.sub(r"\s+", " ", name)


def _is_open(application: dict[str, Any]) -> bool:
    return _text(application.get("status")) not in CLOSED_STATUSES


def _parse_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _contact_sort_key(record: dict[str, Any]) -> tuple[int, str, str]:
    follow_up_rank = {"Due": 0, "Needed": 1, "Planned": 2, "None": 3}
    return (
        follow_up_rank.get(str(record["follow_up_status"]), 3),
        str(record["last_contact_at"]),
        str(record["contact"]),
    )


def _identity(value: str) -> str:
    return " ".join(re.findall(r"[a-zA-Z0-9]+", value.casefold()))


def _text(value: object) -> str:
    return str(value or "").strip()
