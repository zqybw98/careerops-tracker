from __future__ import annotations

from typing import Any

HIGH_CONFIDENCE_THRESHOLD = 0.85
MEDIUM_CONFIDENCE_THRESHOLD = 0.6

CONTEXT_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("Company", "company", "Application identity"),
    ("Role", "role", "Application identity"),
    ("Location", "location", "Application context"),
    ("Contact", "contact", "Reply context"),
    ("Source link", "source_link", "Traceability"),
    ("Interview date", "interview_date", "Scheduling"),
    ("Deadline", "deadline", "Scheduling"),
    ("Suggested follow-up", "suggested_follow_up_date", "Reminder"),
    ("Rejection reason", "rejection_reason", "Outcome context"),
)


def build_email_analysis_summary(
    classification: dict[str, Any],
    details: dict[str, str],
    match: dict[str, Any] | None,
    candidate_count: int = 0,
) -> dict[str, str]:
    confidence = _coerce_float(classification.get("confidence"), default=0.0)
    confidence_info = confidence_band(confidence)
    detected_count = detected_context_count(details)
    total_fields = len(CONTEXT_FIELDS)
    category = str(classification.get("category") or "Other")
    suggested_status = str(classification.get("suggested_status") or "Applied")

    if match:
        match_confidence = confidence_band(match.get("confidence"))
        decision = (
            f"Classified as {category}. Suggested status is {suggested_status}. "
            f"Best existing match is {match['company']} / {match['role']} "
            f"with {match_confidence['label'].lower()} match confidence."
        )
        match_label = f"{match_confidence['label']} match"
    elif detected_count:
        if candidate_count:
            decision = (
                f"Classified as {category}. Suggested status is {suggested_status}. "
                f"{candidate_count} possible existing application match(es) need review."
            )
            match_label = "Review candidates"
        else:
            decision = (
                f"Classified as {category}. Suggested status is {suggested_status}. "
                "Structured context was detected, but no confident existing application match was found."
            )
            match_label = "Needs review"
    else:
        decision = (
            f"Classified as {category}. Suggested status is {suggested_status}. "
            "No structured application context was detected; review the email manually before applying updates."
        )
        match_label = "Manual review"

    return {
        "confidence_label": confidence_info["label"],
        "confidence_description": confidence_info["description"],
        "detected_context": f"{detected_count}/{total_fields}",
        "decision": decision,
        "match_label": match_label,
    }


def build_operation_summary(
    classification: dict[str, Any],
    details: dict[str, str],
    recommendation: dict[str, str],
    workflow_decision: dict[str, Any],
    selected_application: dict[str, Any] | None = None,
    selected_match: dict[str, Any] | None = None,
    match_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    confidence = _coerce_float(classification.get("confidence"), default=0.0)
    gate = confidence_gate(confidence)
    category = str(classification.get("category") or "Other")
    suggested_status = str(classification.get("suggested_status") or "Applied")
    operation = str(workflow_decision.get("operation") or "Review email")
    review_level = str(workflow_decision.get("review_level") or "Medium")
    status_action = str(workflow_decision.get("status_action") or "No status change")
    record_action = str(workflow_decision.get("record_action") or "Review the email.")
    next_action = str(recommendation.get("next_action") or "Review the email manually.")
    follow_up_date = str(recommendation.get("follow_up_date") or "")
    target = _target_label(selected_application, details)
    match_summary = _operation_match_summary(selected_match, match_candidates)

    follow_up_sentence = f" Follow-up date: {follow_up_date}." if follow_up_date else ""
    summary = (
        f"{operation} for {target}. Email classified as {category} "
        f"({confidence:.0%}, {gate['gate']}) with suggested status {suggested_status}. "
        f"{match_summary} Recommended record action: {record_action}. "
        f"Recommended next action: {next_action} Status action: {status_action}."
        f"{follow_up_sentence}"
    )
    audit_note = (
        f"Operation summary: {operation} | Review level: {review_level} | "
        f"Email: {category} ({confidence:.0%}, gate: {gate['gate']}) | "
        f"Target: {target} | Status action: {status_action} | Next action: {next_action}"
    )

    return {
        "headline": f"{operation} - {target}",
        "summary": summary,
        "audit_note": audit_note,
        "gate": gate["gate"],
        "review_level": review_level,
    }


def confidence_band(value: object) -> dict[str, str]:
    confidence = _coerce_float(value, default=0.0)
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return {
            "label": "High",
            "description": "Strong evidence. The suggestion is likely ready to apply after a quick review.",
        }
    if confidence >= MEDIUM_CONFIDENCE_THRESHOLD:
        return {
            "label": "Medium",
            "description": "Useful evidence, but the user should review the extracted context before applying changes.",
        }
    return {
        "label": "Low",
        "description": "Limited evidence. Treat this as a manual review candidate.",
    }


def confidence_gate(value: object) -> dict[str, str]:
    confidence = _coerce_float(value, default=0.0)
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return {
            "gate": "Ready",
            "threshold": ">= 85%",
            "allowed_action": "Allow status update after quick review",
            "requires": "Check extracted fields and matched application",
        }
    if confidence >= MEDIUM_CONFIDENCE_THRESHOLD:
        return {
            "gate": "Review required",
            "threshold": "60% - 84%",
            "allowed_action": "Require explicit user confirmation",
            "requires": "Review extracted fields, match, and workflow action",
        }
    return {
        "gate": "Blocked",
        "threshold": "< 60%",
        "allowed_action": "Disable status update; save task only",
        "requires": "Manual review before changing application status",
    }


def build_confidence_threshold_rows() -> list[dict[str, str]]:
    return [
        {
            "Band": "High",
            "Threshold": ">= 85%",
            "Workflow rule": "Ready to apply after quick review",
        },
        {
            "Band": "Medium",
            "Threshold": "60% - 84%",
            "Workflow rule": "Require explicit confirmation",
        },
        {
            "Band": "Low",
            "Threshold": "< 60%",
            "Workflow rule": "Block status update; save task only",
        },
    ]


def detected_context_count(details: dict[str, str]) -> int:
    return sum(1 for _, key, _ in CONTEXT_FIELDS if str(details.get(key, "")).strip())


def build_context_rows(details: dict[str, str]) -> list[dict[str, str]]:
    rows = []
    for label, key, use in CONTEXT_FIELDS:
        value = str(details.get(key, "")).strip()
        rows.append(
            {
                "Field": label,
                "Value": value or "-",
                "Use": use,
                "Detected": "yes" if value else "no",
            }
        )
    return rows


def build_keyword_rows(classification: dict[str, Any]) -> list[dict[str, str]]:
    keywords = classification.get("matched_keywords") or []
    return [{"Matched keyword": str(keyword)} for keyword in keywords]


def build_match_reason_rows(match: dict[str, Any] | None) -> list[dict[str, str]]:
    if not match:
        return []
    return [{"Reason": str(reason)} for reason in match.get("reasons", [])]


def build_match_signal_rows(match: dict[str, Any] | None) -> list[dict[str, str]]:
    if not match:
        return []

    signals = match.get("signals") or {}
    signal_labels = [
        ("Company", "company"),
        ("Role", "role"),
        ("Domain", "domain"),
        ("Status context", "status"),
    ]
    return [
        {
            "Signal": label,
            "Score": str(int(signals.get(key, 0) or 0)),
        }
        for label, key in signal_labels
    ]


def build_match_candidate_rows(
    matches: list[dict[str, Any]],
    selected_match: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    selected_id = int(selected_match["application_id"]) if selected_match else 0
    rows = []
    for index, match in enumerate(matches, start=1):
        match_id = int(match.get("application_id") or 0)
        confidence = _coerce_float(match.get("confidence"), default=0.0)
        if selected_id and match_id == selected_id:
            recommendation = "Auto-selected"
        elif index == 1:
            recommendation = "Top candidate"
        else:
            recommendation = "Alternative"

        rows.append(
            {
                "Rank": str(index),
                "Recommendation": recommendation,
                "Company": str(match.get("company", "")),
                "Role": str(match.get("role", "")),
                "Confidence": f"{confidence:.0%}",
                "Band": confidence_band(confidence)["label"],
                "Score": str(int(match.get("score", 0) or 0)),
                "Why": _summarize_reasons(match),
            }
        )
    return rows


def build_workflow_steps(
    classification: dict[str, Any],
    recommendation: dict[str, str],
    has_match: bool,
    workflow_decision: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    steps = [
        {
            "Step": "1",
            "Action": (
                f"Review classification: {classification.get('category')} -> {classification.get('suggested_status')}"
            ),
        },
        {
            "Step": "2",
            "Action": _workflow_step_two(workflow_decision, has_match),
        },
        {
            "Step": "3",
            "Action": recommendation.get("next_action", "Review the email manually."),
        },
    ]
    if workflow_decision and workflow_decision.get("status_action"):
        steps.append(
            {
                "Step": str(len(steps) + 1),
                "Action": workflow_decision["status_action"],
            }
        )
    if recommendation.get("follow_up_date"):
        steps.append(
            {
                "Step": str(len(steps) + 1),
                "Action": f"Set follow-up date to {recommendation['follow_up_date']}",
            }
        )
    return steps


def _coerce_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, int | float):
        return float(value)
    if not isinstance(value, str):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _summarize_reasons(match: dict[str, Any]) -> str:
    reasons = [str(reason) for reason in match.get("reasons", []) if str(reason).strip()]
    if not reasons:
        return "No strong evidence recorded"
    return "; ".join(reasons[:3])


def _target_label(
    selected_application: dict[str, Any] | None,
    details: dict[str, str],
) -> str:
    if selected_application:
        company = str(selected_application.get("company", "") or "").strip()
        role = str(selected_application.get("role", "") or "").strip()
    else:
        company = details.get("company", "").strip()
        role = details.get("role", "").strip()

    if company and role:
        return f"{company} / {role}"
    if company:
        return company
    if role:
        return role
    return "unmatched application"


def _operation_match_summary(
    selected_match: dict[str, Any] | None,
    match_candidates: list[dict[str, Any]] | None,
) -> str:
    if selected_match:
        confidence = _coerce_float(selected_match.get("confidence"), default=0.0)
        return (
            f"Existing record match: {selected_match.get('company', '')} / "
            f"{selected_match.get('role', '')} ({confidence:.0%})."
        )

    candidate_count = len(match_candidates or [])
    if candidate_count:
        return f"{candidate_count} possible existing match(es) were found and need confirmation."

    return "No confident existing application match was found."


def _workflow_step_two(workflow_decision: dict[str, Any] | None, has_match: bool) -> str:
    if workflow_decision and workflow_decision.get("record_action"):
        return str(workflow_decision["record_action"])
    return "Confirm the matched application" if has_match else "Select an application or create a new record"
