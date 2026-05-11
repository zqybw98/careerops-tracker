from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from src.email_insights import MEDIUM_CONFIDENCE_THRESHOLD
from src.models import CLOSED_STATUSES


def build_next_action_recommendation(
    classification: dict[str, Any],
    details: dict[str, str],
    application: dict[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
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


def build_workflow_decision(
    classification: dict[str, Any],
    details: dict[str, str],
    recommendation: dict[str, str],
    application: dict[str, Any] | None = None,
    auto_match: dict[str, Any] | None = None,
    match_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    confidence = _confidence(classification)
    category = str(classification.get("category") or "Other")
    suggested_status = str(classification.get("suggested_status") or "Applied")
    current_status = str(application.get("status", "") or "Applied") if application else ""
    candidate_count = len(match_candidates or [])
    has_extracted_record = bool(details.get("company") and details.get("role"))

    if confidence < MEDIUM_CONFIDENCE_THRESHOLD or category == "Other":
        return {
            "operation": "Manual review",
            "review_level": "High",
            "record_action": "Review the email before changing a record.",
            "status_action": _status_action_text(current_status, current_status or suggested_status),
            "primary_action_label": "Status update disabled",
            "secondary_action_label": "Save next action only",
            "status_update_allowed": False,
            "decision": "The email evidence is weak, so the safest next step is manual review.",
            "rationale": "Low-confidence or unknown emails should not drive automatic workflow changes.",
        }

    if application is None:
        if has_extracted_record:
            return {
                "operation": "Create application",
                "review_level": "Medium",
                "record_action": "Create a new application from extracted company and role.",
                "status_action": f"Create as {suggested_status}",
                "primary_action_label": "Create application from email",
                "secondary_action_label": "Review extracted fields",
                "status_update_allowed": True,
                "decision": (
                    "No existing application was selected, but the email contains enough context to create one."
                ),
                "rationale": "Company and role were extracted, so this can become a structured application record.",
            }
        return {
            "operation": "Manual review",
            "review_level": "High",
            "record_action": "Add missing company and role before creating a record.",
            "status_action": "No status change",
            "primary_action_label": "Review manually",
            "secondary_action_label": "Add missing fields",
            "status_update_allowed": False,
            "decision": "The email does not contain enough structured context to create or update a record.",
            "rationale": "A reliable application record needs at least company and role.",
        }

    if auto_match is None and candidate_count:
        return {
            "operation": "Confirm match",
            "review_level": "Medium",
            "record_action": "Confirm the selected candidate before applying workflow changes.",
            "status_action": _status_action_text(current_status, suggested_status),
            "primary_action_label": "Apply to selected application",
            "secondary_action_label": "Save next action only",
            "status_update_allowed": True,
            "decision": "The assistant found possible matches, but none were strong enough for automatic selection.",
            "rationale": "A human confirmation step reduces the risk of updating the wrong application.",
        }

    if suggested_status == "Rejected":
        return {
            "operation": "Close application" if current_status not in CLOSED_STATUSES else "Record outcome",
            "review_level": "Low" if auto_match else "Medium",
            "record_action": "Save rejection reason and add a traceable activity event.",
            "status_action": _status_action_text(current_status, "Rejected"),
            "primary_action_label": "Apply rejection update",
            "secondary_action_label": "Save rejection note only",
            "status_update_allowed": True,
            "decision": "The email indicates a rejection, so the application should be closed with context preserved.",
            "rationale": "Rejected emails are terminal workflow events and are valuable for later review.",
        }

    if suggested_status == "Interview Scheduled":
        return {
            "operation": "Prepare interview",
            "review_level": "Low" if auto_match else "Medium",
            "record_action": "Update status, store interview context, and schedule preparation.",
            "status_action": _status_action_text(current_status, "Interview Scheduled"),
            "primary_action_label": "Apply interview update",
            "secondary_action_label": "Save preparation task only",
            "status_update_allowed": True,
            "decision": "The email indicates an interview step, so preparation and scheduling are the next priority.",
            "rationale": "Interview invitations are high-value workflow events with time-sensitive preparation work.",
        }

    if suggested_status == "Assessment":
        return {
            "operation": "Track assessment",
            "review_level": "Low" if auto_match else "Medium",
            "record_action": "Update status and track the assessment deadline.",
            "status_action": _status_action_text(current_status, "Assessment"),
            "primary_action_label": "Apply assessment update",
            "secondary_action_label": "Save deadline task only",
            "status_update_allowed": True,
            "decision": "The email contains an assessment step, so deadline tracking is the safest next action.",
            "rationale": "Assessment emails usually create a time-bound task.",
        }

    if suggested_status == "Confirmation Received":
        return {
            "operation": "Schedule follow-up",
            "review_level": "Low" if auto_match else "Medium",
            "record_action": "Update early-stage status and set a follow-up reminder.",
            "status_action": _status_action_text(current_status, "Confirmation Received"),
            "primary_action_label": "Apply confirmation update",
            "secondary_action_label": "Save follow-up only",
            "status_update_allowed": True,
            "decision": "The email confirms receipt, so the useful action is waiting plus scheduled follow-up.",
            "rationale": "Confirmation emails rarely need a reply, but they should start a follow-up timer.",
        }

    if suggested_status == "Follow-up Needed":
        return {
            "operation": "Reply required",
            "review_level": "Medium",
            "record_action": "Keep the record active and prepare a recruiter response.",
            "status_action": _status_action_text(current_status, "Follow-up Needed"),
            "primary_action_label": "Apply reply-needed update",
            "secondary_action_label": "Save reply task only",
            "status_update_allowed": True,
            "decision": "The email appears to require a response, so the next step is a recruiter reply task.",
            "rationale": "Recruiter messages often need human-written responses before a status change is final.",
        }

    if current_status == suggested_status:
        return {
            "operation": "Refresh next action",
            "review_level": "Low",
            "record_action": "Keep the current status and refresh next action details.",
            "status_action": _status_action_text(current_status, suggested_status),
            "primary_action_label": "Refresh application task",
            "secondary_action_label": "Save next action only",
            "status_update_allowed": True,
            "decision": "The status is already aligned, so only the action details need to be updated.",
            "rationale": "Avoid unnecessary status churn when the application is already in the suggested stage.",
        }

    return {
        "operation": "Update status",
        "review_level": "Medium",
        "record_action": "Update the selected application and save the assistant rationale.",
        "status_action": _status_action_text(current_status, suggested_status),
        "primary_action_label": "Apply recommended update",
        "secondary_action_label": "Save next action only",
        "status_update_allowed": True,
        "decision": recommendation.get("next_action", "Update the selected application based on this email."),
        "rationale": recommendation.get("rationale", "The email classification suggests a workflow update."),
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


def _confidence(classification: dict[str, Any]) -> float:
    try:
        return float(classification.get("confidence", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _status_action_text(current_status: str, suggested_status: str) -> str:
    if not current_status:
        return f"Set {suggested_status}"
    if current_status == suggested_status:
        return f"Keep {current_status}"
    return f"{current_status} -> {suggested_status}"
