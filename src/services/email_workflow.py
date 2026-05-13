from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from src.action_recommender import build_next_action_recommendation, build_workflow_decision
from src.database import DEFAULT_DB_PATH, create_application, update_application
from src.email_classifier import classify_email
from src.email_insights import build_operation_summary
from src.email_parser import (
    extract_application_details,
    match_application_from_email,
    rank_application_matches_from_email,
)


def classify_email_for_workflow(
    subject: str,
    body: str,
    applications: list[dict[str, Any]],
) -> dict[str, Any]:
    classification = classify_email(subject=subject, body=body)
    details = extract_application_details(subject=subject, body=body)
    match_candidates = rank_application_matches_from_email(
        applications,
        subject=subject,
        body=body,
        extracted_details=details,
    )
    match = match_application_from_email(
        applications,
        subject=subject,
        body=body,
        extracted_details=details,
    )
    return {
        "classification": classification,
        "details": details,
        "match": match,
        "match_candidates": match_candidates,
    }


def build_email_create_recommendation(
    classification: dict[str, Any],
    details: dict[str, str],
) -> dict[str, str]:
    return build_next_action_recommendation(classification, details)


def build_email_workflow_for_application(
    classification: dict[str, Any],
    details: dict[str, str],
    application: dict[str, Any],
    match: dict[str, Any] | None,
    match_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    recommendation = build_next_action_recommendation(classification, details, application)
    workflow_decision = build_workflow_decision(
        classification,
        details,
        recommendation,
        application=application,
        auto_match=match,
        match_candidates=match_candidates,
    )
    operation_summary = build_operation_summary(
        classification,
        details,
        recommendation,
        workflow_decision,
        selected_application=application,
        selected_match=match,
        match_candidates=match_candidates,
    )
    return {
        "recommendation": recommendation,
        "workflow_decision": workflow_decision,
        "operation_summary": operation_summary,
    }


def apply_email_workflow_update(
    selected_id: int,
    selected: dict[str, Any],
    classification: dict[str, Any],
    details: dict[str, str],
    recommendation: dict[str, str],
    apply_status: bool,
    operation_summary: dict[str, str] | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> None:
    follow_up_date = recommendation["follow_up_date"] or selected.get("follow_up_date", "")
    notes = _append_note(selected.get("notes", ""), _build_email_note(classification, details))
    notes = _append_note(notes, _build_next_action_note(recommendation))
    if operation_summary:
        notes = _append_note(notes, operation_summary["audit_note"])

    rejection_reason = selected.get("rejection_reason", "")
    if classification["suggested_status"] == "Rejected" and not rejection_reason:
        rejection_reason = details.get("rejection_reason") or "Rejected based on classified recruiting email."

    update_application(
        selected_id,
        {
            **selected,
            "status": classification["suggested_status"] if apply_status else selected.get("status", "Applied"),
            "location": selected.get("location", "") or details.get("location", ""),
            "contact": selected.get("contact", "") or details.get("contact", ""),
            "source_link": selected.get("source_link", "") or details.get("source_link", ""),
            "next_action": recommendation["next_action"],
            "follow_up_date": follow_up_date,
            "notes": notes,
            "rejection_reason": rejection_reason,
        },
        db_path=db_path,
        source="email_assistant" if apply_status else "email_next_action",
    )


def build_initial_email_create_notes(
    classification: dict[str, Any],
    details: dict[str, str],
    recommendation: dict[str, str],
) -> str:
    return _append_note(_build_email_note(classification, details), _build_next_action_note(recommendation))


def build_gmail_sync_preview(emails: list[dict[str, str]], applications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for index, email in enumerate(emails, start=1):
        workflow = classify_email_for_workflow(
            subject=email.get("subject", ""),
            body=email.get("body", ""),
            applications=applications,
        )
        classification = workflow["classification"]
        details = workflow["details"]
        match = workflow["match"]
        previews.append(
            {
                "index": index,
                "apply": False,
                "gmail_id": email.get("gmail_id", ""),
                "subject": email.get("subject", ""),
                "sender": email.get("sender", ""),
                "date": email.get("date", ""),
                "body": email.get("body", ""),
                "category": classification["category"],
                "confidence": classification["confidence"],
                "suggested_status": classification["suggested_status"],
                "suggested_next_action": classification["suggested_next_action"],
                "suggested_follow_up_days": classification["suggested_follow_up_days"],
                "matched_keywords": classification["matched_keywords"],
                "company": details.get("company", ""),
                "role": details.get("role", ""),
                "location": details.get("location", ""),
                "contact": details.get("contact", ""),
                "source_link": details.get("source_link", ""),
                "suggested_follow_up_date": details.get("suggested_follow_up_date", ""),
                "deadline": details.get("deadline", ""),
                "interview_date": details.get("interview_date", ""),
                "rejection_reason": details.get("rejection_reason", ""),
                "matched_application_id": int(match["application_id"]) if match else 0,
                "matched_application": f"{match['company']} / {match['role']}" if match else "",
                "classification": classification,
                "details": details,
            }
        )
    return previews


def apply_gmail_preview(
    preview: dict[str, Any],
    applications: list[dict[str, Any]],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> str:
    classification = preview["classification"]
    details = preview["details"]
    match_id = int(preview.get("matched_application_id") or 0)
    recommendation = build_next_action_recommendation(classification, details)

    if match_id:
        selected = next((item for item in applications if int(item["id"]) == match_id), None)
        if not selected:
            return "skipped"
        rejection_reason = selected.get("rejection_reason", "")
        if classification["suggested_status"] == "Rejected" and not rejection_reason:
            rejection_reason = details.get("rejection_reason") or "Rejected based on Gmail recruiting email."
        update_application(
            match_id,
            {
                **selected,
                "status": classification["suggested_status"],
                "location": selected.get("location", "") or details.get("location", ""),
                "contact": selected.get("contact", "") or details.get("contact", ""),
                "source_link": selected.get("source_link", "") or details.get("source_link", ""),
                "next_action": recommendation["next_action"],
                "follow_up_date": recommendation["follow_up_date"] or selected.get("follow_up_date", ""),
                "notes": _append_note(
                    _append_note(selected.get("notes", ""), _build_gmail_note(preview)),
                    _build_next_action_note(recommendation),
                ),
                "rejection_reason": rejection_reason,
            },
            db_path=db_path,
            source="gmail_sync",
        )
        return "updated"

    if not details.get("company") or not details.get("role"):
        return "skipped"

    create_application(
        {
            "company": details["company"],
            "role": details["role"],
            "location": details.get("location", ""),
            "application_date": date.today().isoformat(),
            "status": classification["suggested_status"],
            "source_link": details.get("source_link", ""),
            "contact": details.get("contact", ""),
            "notes": _append_note(_build_gmail_note(preview), _build_next_action_note(recommendation)),
            "rejection_reason": (details.get("rejection_reason") or "Rejected based on Gmail recruiting email.")
            if classification["suggested_status"] == "Rejected"
            else "",
            "next_action": recommendation["next_action"],
            "follow_up_date": recommendation["follow_up_date"],
        },
        db_path=db_path,
        source="gmail_sync",
    )
    return "created"


def _build_next_action_note(recommendation: dict[str, str]) -> str:
    note_parts = [
        f"Smart next action generated: {recommendation['next_action']}",
        f"Priority: {recommendation['priority']}",
    ]
    if recommendation["follow_up_date"]:
        note_parts.append(f"Follow-up date: {recommendation['follow_up_date']}")
    if recommendation["template_type"]:
        note_parts.append(f"Suggested template: {recommendation['template_type']}")
    if recommendation["rationale"]:
        note_parts.append(f"Rationale: {recommendation['rationale']}")
    return " | ".join(note_parts)


def _build_email_note(classification: dict[str, Any], details: dict[str, str]) -> str:
    note_parts = [
        f"Email classified as {classification['category']} with {classification['confidence']:.0%} confidence."
    ]
    extracted_parts = [
        f"{label}: {details[value]}"
        for label, value in [
            ("Company", "company"),
            ("Role", "role"),
            ("Location", "location"),
            ("Contact", "contact"),
            ("Source", "source_link"),
            ("Interview date", "interview_date"),
            ("Deadline", "deadline"),
            ("Suggested follow-up", "suggested_follow_up_date"),
            ("Rejection reason", "rejection_reason"),
        ]
        if details.get(value)
    ]
    if extracted_parts:
        note_parts.append("Extracted " + "; ".join(extracted_parts))
    return " ".join(note_parts)


def _build_gmail_note(preview: dict[str, Any]) -> str:
    note = _build_email_note(preview["classification"], preview["details"])
    subject = preview.get("subject", "")
    sender = preview.get("sender", "")
    return f"{note} Gmail source: {sender} | {subject}".strip()


def _append_note(existing_notes: str, new_note: str) -> str:
    existing = str(existing_notes or "").strip()
    note = str(new_note or "").strip()
    if not existing:
        return note
    if not note:
        return existing
    return f"{existing}\n\n{note}"
