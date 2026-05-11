from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def build_next_action_recommendation(
    classification: dict[str, Any],
    details: dict[str, str],
    application: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, str]:
    current_date = today or date.today()
    status = str(classification.get("suggested_status") or "Applied")
    category = str(classification.get("category") or "Other")
    company = _value(application, details, "company", "the company")
    role = _value(application, details, "role", "the role")
    deadline = _valid_date(details.get("deadline", ""))
    interview_date = _valid_date(details.get("interview_date", ""))
    extracted_follow_up = _valid_date(details.get("suggested_follow_up_date", ""))
    relative_follow_up = _relative_follow_up(classification, current_date)

    if status == "Interview Scheduled" or category == "Interview Invitation":
        follow_up_date = interview_date or extracted_follow_up or relative_follow_up
        due_phrase = f" before {follow_up_date}" if follow_up_date else ""
        return {
            "priority": "High",
            "next_action": f"Confirm availability with {company} and prepare interview notes for {role}{due_phrase}.",
            "follow_up_date": follow_up_date,
            "template_type": "Interview Thank-you Email",
            "rationale": "Interview-related email detected; the next step is confirmation and preparation.",
        }

    if status == "Assessment" or category == "Assessment / Coding Test":
        follow_up_date = deadline or extracted_follow_up or relative_follow_up
        due_phrase = f" by {follow_up_date}" if follow_up_date else ""
        return {
            "priority": "High",
            "next_action": f"Complete the assessment for {company} / {role}{due_phrase}.",
            "follow_up_date": follow_up_date,
            "template_type": "Follow-up Email",
            "rationale": "Assessment email detected; deadline tracking is the highest-risk action.",
        }

    if status == "Rejected" or category == "Rejection":
        reason = details.get("rejection_reason", "").strip()
        reason_phrase = f" Reason: {reason}" if reason else ""
        return {
            "priority": "Medium",
            "next_action": (
                f"Capture rejection reason and archive lessons learned for {company} / {role}.{reason_phrase}"
            ),
            "follow_up_date": "",
            "template_type": "Rejection Acknowledgement Email",
            "rationale": "Rejection email detected; close the loop and preserve review context.",
        }

    if status == "Confirmation Received" or category == "Application Confirmation":
        follow_up_date = extracted_follow_up or relative_follow_up or (current_date + timedelta(days=7)).isoformat()
        return {
            "priority": "Medium",
            "next_action": f"Wait for response from {company} and follow up if there is no update by {follow_up_date}.",
            "follow_up_date": follow_up_date,
            "template_type": "Follow-up Email",
            "rationale": "Confirmation email detected; the useful action is scheduled follow-up tracking.",
        }

    if status == "Follow-up Needed" or category in {"Recruiter Reply", "Follow-up Needed"}:
        follow_up_date = deadline or extracted_follow_up or relative_follow_up or current_date.isoformat()
        return {
            "priority": "High",
            "next_action": f"Reply to the recruiter about {company} / {role} and update the application record.",
            "follow_up_date": follow_up_date,
            "template_type": "Recruiter Outreach Email",
            "rationale": "Recruiter or follow-up email detected; the next action requires a response.",
        }

    if status == "Offer":
        follow_up_date = (
            deadline or extracted_follow_up or relative_follow_up or (current_date + timedelta(days=2)).isoformat()
        )
        return {
            "priority": "High",
            "next_action": f"Review the offer details from {company} and prepare questions before responding.",
            "follow_up_date": follow_up_date,
            "template_type": "Recruiter Outreach Email",
            "rationale": "Offer-like status detected; the next action is review and response planning.",
        }

    return {
        "priority": "Low",
        "next_action": f"Review the email manually and decide whether {company} / {role} needs an update.",
        "follow_up_date": extracted_follow_up or relative_follow_up,
        "template_type": "Follow-up Email",
        "rationale": "No high-confidence workflow action was detected.",
    }


def _relative_follow_up(classification: dict[str, Any], today: date) -> str:
    days = classification.get("suggested_follow_up_days")
    if days is None:
        return ""
    try:
        return (today + timedelta(days=int(days))).isoformat()
    except (TypeError, ValueError):
        return ""


def _valid_date(value: str) -> str:
    if not value:
        return ""
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ""


def _value(
    application: dict[str, Any] | None,
    details: dict[str, str],
    key: str,
    fallback: str,
) -> str:
    if application:
        application_value = str(application.get(key, "") or "").strip()
        if application_value:
            return application_value

    detail_value = details.get(key, "").strip()
    return detail_value or fallback
