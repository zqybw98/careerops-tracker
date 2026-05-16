from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from src.database import create_application
from src.email_insights import (
    build_confidence_threshold_rows,
    build_context_rows,
    build_email_analysis_summary,
    build_keyword_rows,
    build_match_candidate_rows,
    build_match_reason_rows,
    build_match_signal_rows,
    build_workflow_steps,
    confidence_gate,
)
from src.email_templates import TEMPLATE_LANGUAGES, TEMPLATE_TYPES, generate_email_template, suggest_template_type
from src.gmail_client import (
    DEFAULT_GMAIL_QUERY,
    GmailConfigurationError,
    GmailDependencyError,
    fetch_recruiting_emails,
)
from src.models import STATUS_OPTIONS
from src.services.email_workflow import (
    apply_email_workflow_update,
    apply_gmail_preview,
    build_email_create_recommendation,
    build_email_workflow_for_application,
    build_gmail_sync_preview,
    build_initial_email_create_notes,
    classify_email_for_workflow,
    get_email_category_options,
    record_email_feedback,
)
from src.services.job_post_workflow import build_job_post_application_draft


def render_assistant_workspace(applications: list[dict]) -> None:
    job_post_tab, email_tab, templates_tab, gmail_tab = st.tabs(
        ["Job Post Intake", "Classify Email", "Templates", "Gmail Sync"]
    )
    with job_post_tab:
        render_job_post_intake()
    with email_tab:
        render_email_assistant(applications)
    with templates_tab:
        render_email_templates(applications)
    with gmail_tab:
        render_gmail_sync_tools(applications)


def render_job_post_intake() -> None:
    st.subheader("Draft Application from Job Post")
    source_url = st.text_input("Job URL", key="job_post_url_input")
    job_post_text = st.text_area(
        "Job description / JD",
        height=260,
        placeholder="Paste the job title, company, location, requirements, deadline, or full JD text here.",
        key="job_post_text_input",
    )

    if st.button("Analyze job post", key="analyze_job_post"):
        st.session_state.pop("job_post_create_success_message", None)
        if not source_url.strip() and not job_post_text.strip():
            st.warning("Paste a job URL or JD text before analyzing.")
        else:
            st.session_state["last_job_post_draft"] = build_job_post_application_draft(
                job_text=job_post_text,
                source_url=source_url,
            )
            st.session_state["job_post_draft_version"] = int(st.session_state.get("job_post_draft_version", 0)) + 1

    success_message = st.session_state.get("job_post_create_success_message")
    if success_message:
        st.success(success_message)

    draft = st.session_state.get("last_job_post_draft")
    if not draft:
        st.info("Paste a JD or job URL to extract a draft Saved application record.")
        return

    analysis = draft["analysis"]
    payload = draft["payload"]
    details = analysis["details"]

    metric_cols = st.columns(5)
    metric_cols[0].metric("Company", details.get("company") or "-")
    metric_cols[1].metric("Role", details.get("role") or "-")
    metric_cols[2].metric("Location", details.get("location") or "-")
    metric_cols[3].metric("Confidence", analysis["confidence_label"])
    metric_cols[4].metric("Deadline", details.get("deadline") or "-")
    st.info(analysis["summary"])
    st.dataframe(pd.DataFrame(analysis["field_rows"]), use_container_width=True, hide_index=True, height=245)

    if analysis["missing_fields"]:
        st.warning("Required fields still need review: " + ", ".join(analysis["missing_fields"]))

    st.subheader("Create Saved Application")
    version = int(st.session_state.get("job_post_draft_version", 0))
    with st.form("create_from_job_post_form", clear_on_submit=False):
        col_company, col_role, col_location = st.columns(3)
        company = col_company.text_input(
            "Company",
            value=payload.get("company", ""),
            key=f"job_post_company_{version}",
        )
        role = col_role.text_input("Role", value=payload.get("role", ""), key=f"job_post_role_{version}")
        location = col_location.text_input(
            "Location",
            value=payload.get("location", ""),
            key=f"job_post_location_{version}",
        )

        col_date, col_status, col_follow_up = st.columns(3)
        saved_date = col_date.date_input(
            "Saved date",
            value=_text_to_date(payload.get("application_date")) or date.today(),
            key=f"job_post_date_{version}",
        )
        status = col_status.selectbox(
            "Status",
            STATUS_OPTIONS,
            index=_option_index(STATUS_OPTIONS, payload.get("status", "Saved")),
            key=f"job_post_status_{version}",
        )
        suggested_follow_up = _text_to_date(payload.get("follow_up_date"))
        follow_up_value = col_follow_up.date_input(
            "Deadline / follow-up date",
            value=suggested_follow_up or date.today() + timedelta(days=7),
            key=f"job_post_follow_up_{version}",
        )
        keep_follow_up = col_follow_up.checkbox(
            "Keep date",
            value=bool(suggested_follow_up),
            key=f"job_post_keep_follow_up_{version}",
        )

        source_link = st.text_input(
            "Source link",
            value=payload.get("source_link", ""),
            key=f"job_post_source_{version}",
        )
        contact = st.text_input("Contact", value=payload.get("contact", ""), key=f"job_post_contact_{version}")
        next_action = st.text_input(
            "Next action",
            value=payload.get("next_action", ""),
            key=f"job_post_next_action_{version}",
        )
        notes = st.text_area("Notes", value=payload.get("notes", ""), key=f"job_post_notes_{version}")

        if st.form_submit_button("Create saved application"):
            if not company.strip() or not role.strip():
                st.error("Company and role are required to create a saved application.")
            else:
                create_application(
                    {
                        "company": company,
                        "role": role,
                        "location": location,
                        "application_date": saved_date.isoformat(),
                        "status": status,
                        "source_link": source_link,
                        "contact": contact,
                        "notes": notes,
                        "rejection_reason": "",
                        "next_action": next_action,
                        "follow_up_date": follow_up_value.isoformat() if keep_follow_up else "",
                    },
                    source="job_post_intake",
                )
                st.session_state["job_post_create_success_message"] = (
                    f"Saved application created from JD: {company.strip()} / {role.strip()}."
                )
                st.rerun()


def render_email_assistant(applications: list[dict]) -> None:
    st.subheader("Classify Email")
    st.caption("Paste a recruiting email to classify it, match it to an application, and choose the next action.")
    with st.container(border=True):
        subject = st.text_input("Email subject", key="email_subject_input")
        body = st.text_area("Email body", height=180, key="email_body_input")
        action_col, helper_col = st.columns([1, 4])
        classify_clicked = action_col.button("Analyze email", type="primary")
        helper_col.caption("Supports English, German, and Chinese recruiting emails.")

    if classify_clicked:
        st.session_state.pop("email_create_success_message", None)
        workflow = classify_email_for_workflow(subject=subject, body=body, applications=applications, use_feedback=True)
        st.session_state["last_email_subject"] = subject
        st.session_state["last_email_body"] = body
        st.session_state["last_classification"] = workflow["classification"]
        st.session_state["last_email_details"] = workflow["details"]
        st.session_state["last_application_match"] = workflow["match"]
        st.session_state["last_application_matches"] = workflow["match_candidates"]
        st.session_state["last_email_feedback"] = workflow["feedback"]

    result = st.session_state.get("last_classification")
    if not result:
        st.info("Paste an email above and click Analyze email to get a recommended next step.")
        return

    details = st.session_state.get("last_email_details", {})
    match = st.session_state.get("last_application_match")
    match_candidates = st.session_state.get("last_application_matches", [])
    feedback = st.session_state.get("last_email_feedback")
    create_recommendation = build_email_create_recommendation(result, details)

    if feedback:
        st.success(
            "Saved manual feedback was applied to this email "
            f"({float(feedback.get('similarity') or 0):.0%} similarity)."
        )

    if applications:
        st.divider()
        st.subheader("Matched Application Update")
        label_id_map = _application_label_id_map(applications)
        labels = list(label_id_map.keys())
        default_match = match or (match_candidates[0] if match_candidates else None)
        default_index = _matched_label_index(labels, label_id_map, default_match)
        selected_label = st.selectbox(
            "Matched application",
            labels,
            index=default_index,
            key="email_update_select",
        )
        selected_id = label_id_map[selected_label]
        selected = next(item for item in applications if item["id"] == selected_id)
        selected_match = _match_for_application_id(selected_id, match, match_candidates)
        status_to_apply, details_for_update, classification_for_update = _render_email_status_control(
            result,
            details,
            selected,
        )
        workflow_context = build_email_workflow_for_application(
            classification_for_update,
            details_for_update,
            selected,
            selected_match,
            match_candidates,
        )
        recommendation = workflow_context["recommendation"]
        details_for_update, recommendation = _render_email_apply_draft_controls(
            selected,
            classification_for_update,
            details_for_update,
            recommendation,
        )
        workflow_context = build_email_workflow_for_application(
            classification_for_update,
            details_for_update,
            selected,
            selected_match,
            match_candidates,
            recommendation_override=recommendation,
        )
        recommendation = workflow_context["recommendation"]
        workflow_decision = workflow_context["workflow_decision"]
        operation_summary = workflow_context["operation_summary"]

        if selected_match:
            match_confidence = float(selected_match.get("confidence") or 0)
            match_text = f"{selected_match['company']} / {selected_match['role']} ({match_confidence:.0%})"
            if match and int(match.get("application_id") or 0) == selected_id:
                st.success(f"Matched to existing application: {match_text}")
            else:
                st.warning(f"Selected possible match: {match_text}. Review before applying.")
        else:
            st.warning("Manually selected application. Review the suggested changes before applying.")

        if status_to_apply != result.get("suggested_status"):
            st.info(f"Manual status override selected: {result.get('suggested_status')} -> {status_to_apply}.")

        _render_email_update_preview(
            selected,
            classification_for_update,
            details_for_update,
            recommendation,
            workflow_decision,
        )
        st.info(workflow_decision["decision"])
        if not workflow_decision["status_update_allowed"]:
            st.warning("Status update is disabled because the email is below the confidence threshold.")

        status_col, next_action_col = st.columns(2)
        if status_col.button(
            workflow_decision["primary_action_label"],
            type="primary",
            disabled=not workflow_decision["status_update_allowed"],
        ):
            apply_email_workflow_update(
                selected_id,
                selected,
                classification_for_update,
                details_for_update,
                recommendation,
                apply_status=True,
                operation_summary=operation_summary,
            )
            st.success("Application updated from email classification.")
            st.rerun()

        if next_action_col.button(workflow_decision["secondary_action_label"]):
            apply_email_workflow_update(
                selected_id,
                selected,
                classification_for_update,
                details_for_update,
                recommendation,
                apply_status=False,
                operation_summary=operation_summary,
            )
            st.success("Next action applied to the selected application.")
            st.rerun()

        with st.expander("Review workflow details"):
            st.write("Record action:", workflow_decision["record_action"])
            st.write("Status action:", workflow_decision["status_action"])
            st.caption("Why: " + workflow_decision["rationale"])
            st.markdown("**Operation Summary**")
            st.write(operation_summary["summary"])
            st.caption(operation_summary["audit_note"])
            st.dataframe(
                pd.DataFrame(
                    build_workflow_steps(
                        classification_for_update,
                        recommendation,
                        has_match=bool(selected_match),
                        workflow_decision=workflow_decision,
                    )
                ),
                use_container_width=True,
                hide_index=True,
            )

        with st.expander("Review analysis details"):
            render_email_analysis_details(
                classification_for_update,
                details_for_update,
                selected_match,
                match_candidates,
                create_recommendation,
                has_applications=bool(applications),
            )

        render_email_feedback_controls(
            applications=applications,
            classification=classification_for_update,
            details=details_for_update,
            match=selected_match,
            match_candidates=match_candidates,
        )
    else:
        render_email_analysis_report(
            result,
            details,
            match,
            match_candidates,
            create_recommendation,
            has_applications=False,
        )

    st.divider()
    success_message = st.session_state.get("email_create_success_message")
    if success_message:
        st.success(success_message)
    create_expanded = not applications or not (match or match_candidates)
    with (
        st.expander("Create a new application from this email", expanded=create_expanded),
        st.form("create_from_email_form", clear_on_submit=True),
    ):
        col_company, col_role, col_location = st.columns(3)
        company = col_company.text_input("Company", value=details.get("company", ""), key="email_create_company")
        role = col_role.text_input("Role", value=details.get("role", ""), key="email_create_role")
        location = col_location.text_input(
            "Location",
            value=details.get("location", ""),
            key="email_create_location",
        )

        col_date, col_status, col_follow_up = st.columns(3)
        application_date = col_date.date_input("Application date", value=date.today(), key="email_create_date")
        status_index = (
            STATUS_OPTIONS.index(result["suggested_status"]) if result["suggested_status"] in STATUS_OPTIONS else 1
        )
        status = col_status.selectbox("Status", STATUS_OPTIONS, index=status_index, key="email_create_status")
        follow_up_date = create_recommendation["follow_up_date"]
        keep_follow_up = col_follow_up.checkbox("Set suggested follow-up", value=bool(follow_up_date))

        source_link = st.text_input("Source link", value=details.get("source_link", ""), key="email_create_source")
        contact = st.text_input("Contact", value=details.get("contact", ""), key="email_create_contact")
        next_action = st.text_input(
            "Next action",
            value=create_recommendation["next_action"],
            key="email_create_next_action",
        )
        notes = st.text_area(
            "Notes",
            value=build_initial_email_create_notes(result, details, create_recommendation),
            key="email_create_notes",
        )
        rejection_reason = st.text_area(
            "Rejection reason",
            value=(details.get("rejection_reason") or "Rejected based on classified recruiting email.")
            if status == "Rejected"
            else "",
            key="email_create_rejection_reason",
        )

        if st.form_submit_button("Create application from email"):
            if not company.strip() or not role.strip():
                st.error("Company and role are required to create an application.")
            else:
                create_application(
                    {
                        "company": company,
                        "role": role,
                        "location": location,
                        "application_date": application_date.isoformat(),
                        "status": status,
                        "source_link": source_link,
                        "contact": contact,
                        "notes": notes,
                        "rejection_reason": rejection_reason,
                        "next_action": next_action,
                        "follow_up_date": create_recommendation["follow_up_date"] if keep_follow_up else "",
                    },
                    source="email_assistant",
                )
                st.session_state["email_create_success_message"] = (
                    f"Application created from email: {company.strip()} / {role.strip()}."
                )
                st.rerun()


def render_email_feedback_controls(
    applications: list[dict],
    classification: dict,
    details: dict[str, str],
    match: dict | None,
    match_candidates: list[dict],
) -> None:
    success_message = st.session_state.pop("email_feedback_success_message", None)
    if success_message:
        st.success(success_message)

    with st.expander("Correction Feedback", expanded=bool(classification.get("feedback_override"))):
        st.caption(
            "Save a manual correction when the assistant picked the wrong category, status, or application. "
            "Similar future emails will use this preference before applying workflow actions."
        )
        category_options = get_email_category_options()
        labels = ["No application preference"]
        label_id_map: dict[str, int] = {}
        default_application_index = 0
        if applications:
            label_id_map = _application_label_id_map(applications)
            labels.extend(label_id_map.keys())
            default_match = match or (match_candidates[0] if match_candidates else None)
            if default_match:
                matched_id = int(default_match.get("application_id") or 0)
                matched_label = next((label for label in labels[1:] if label_id_map[label] == matched_id), "")
                default_application_index = labels.index(matched_label) if matched_label else 0

        col_category, col_status, col_application = st.columns(3)
        corrected_category = col_category.selectbox(
            "Correct category",
            category_options,
            index=_option_index(category_options, str(classification.get("category") or "Other")),
            key="email_feedback_category",
        )
        corrected_status = col_status.selectbox(
            "Correct status",
            STATUS_OPTIONS,
            index=_option_index(STATUS_OPTIONS, str(classification.get("suggested_status") or "Applied")),
            key="email_feedback_status",
        )
        corrected_label = col_application.selectbox(
            "Correct matched application",
            labels,
            index=default_application_index,
            key="email_feedback_application",
        )
        corrected_application_id = label_id_map.get(corrected_label)

        if st.button("Save correction feedback", key="save_email_feedback"):
            subject = str(st.session_state.get("last_email_subject", ""))
            body = str(st.session_state.get("last_email_body", ""))
            if not subject and not body:
                st.warning("Classify an email before saving feedback.")
                return

            feedback_id = record_email_feedback(
                subject=subject,
                body=body,
                classification=classification,
                details=details,
                corrected_category=corrected_category,
                corrected_status=corrected_status,
                corrected_application_id=corrected_application_id,
                applications=applications,
            )
            workflow = classify_email_for_workflow(
                subject=subject,
                body=body,
                applications=applications,
                use_feedback=True,
            )
            st.session_state["last_classification"] = workflow["classification"]
            st.session_state["last_email_details"] = workflow["details"]
            st.session_state["last_application_match"] = workflow["match"]
            st.session_state["last_application_matches"] = workflow["match_candidates"]
            st.session_state["last_email_feedback"] = workflow["feedback"]
            st.session_state["email_feedback_success_message"] = (
                f"Correction feedback saved as preference #{feedback_id}."
            )
            st.rerun()


def _compact_display(value: object, limit: int = 46) -> str:
    text = str(value or "-").strip() or "-"
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _render_compact_card(column: Any, label: str, value: object, detail: str = "") -> None:
    with column.container(border=True):
        st.caption(label)
        st.markdown(f"**{_compact_display(value)}**")
        if detail:
            st.caption(detail)


def _render_email_status_control(
    classification: dict,
    details: dict[str, str],
    selected: dict,
) -> tuple[str, dict[str, str], dict]:
    selected_id = int(selected.get("id") or 0)
    original_status = str(classification.get("suggested_status") or "Applied")
    st.markdown("**Review and adjust before applying**")
    status_to_apply = st.selectbox(
        "Status to apply",
        STATUS_OPTIONS,
        index=_option_index(STATUS_OPTIONS, original_status),
        key=f"email_status_override_{selected_id}_{original_status}",
        help="Change this if the email was classified into the wrong workflow stage.",
    )

    details_for_update = dict(details)
    return status_to_apply, details_for_update, _classification_with_status_override(classification, status_to_apply)


def _render_email_apply_draft_controls(
    selected: dict,
    classification: dict,
    details: dict[str, str],
    recommendation: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    selected_id = int(selected.get("id") or 0)
    suggested_status = str(classification.get("suggested_status") or selected.get("status") or "Applied")
    follow_up_date = _text_to_date(recommendation.get("follow_up_date") or selected.get("follow_up_date"))

    draft_col_a, draft_col_b = st.columns([2, 1])
    next_action = draft_col_a.text_area(
        "Next action to save",
        value=str(recommendation.get("next_action") or selected.get("next_action") or ""),
        height=90,
        key=f"email_next_action_override_{selected_id}_{suggested_status}",
        help="Edit the task that will be written to the application.",
    )
    keep_follow_up = draft_col_b.checkbox(
        "Set follow-up date",
        value=bool(follow_up_date),
        key=f"email_keep_follow_up_override_{selected_id}_{suggested_status}",
    )
    follow_up_value = draft_col_b.date_input(
        "Follow-up date",
        value=follow_up_date or date.today() + timedelta(days=7),
        disabled=not keep_follow_up,
        key=f"email_follow_up_override_{selected_id}_{suggested_status}",
    )

    default_rejection_reason = (
        details.get("rejection_reason")
        or selected.get("rejection_reason")
        or ("Rejected based on classified recruiting email." if suggested_status == "Rejected" else "")
    )
    rejection_reason = st.text_area(
        "Rejection reason",
        value=default_rejection_reason,
        height=80,
        key=f"email_rejection_reason_override_{selected_id}_{suggested_status}",
        placeholder=(
            "Optional. Useful for rejected applications, for example no interview, position closed, or mismatch."
        ),
    )

    details_for_update = dict(details)
    if rejection_reason.strip():
        details_for_update["rejection_reason"] = rejection_reason.strip()
    else:
        details_for_update.pop("rejection_reason", None)

    recommendation_for_update = {
        **recommendation,
        "next_action": next_action.strip(),
        "follow_up_date": follow_up_value.isoformat() if keep_follow_up else "",
    }
    return details_for_update, recommendation_for_update


def _classification_with_status_override(classification: dict, status_to_apply: str) -> dict:
    original_status = str(classification.get("suggested_status") or "")
    if status_to_apply == original_status:
        return classification

    adjusted = dict(classification)
    adjusted["suggested_status"] = status_to_apply
    adjusted["category"] = _category_for_status(status_to_apply)
    adjusted["confidence"] = max(float(classification.get("confidence") or 0), 0.85)
    adjusted["suggested_next_action"] = _next_action_for_status(status_to_apply)
    adjusted["suggested_follow_up_days"] = _follow_up_days_for_status(status_to_apply)
    adjusted["matched_keywords"] = [*classification.get("matched_keywords", []), "manual status override"]
    adjusted["manual_override"] = True
    return adjusted


def _category_for_status(status: str) -> str:
    return {
        "Confirmation Received": "Application Confirmation",
        "Interview Scheduled": "Interview Invitation",
        "Assessment": "Assessment / Coding Test",
        "Rejected": "Rejection",
        "Follow-up Needed": "Follow-up Needed",
        "Offer": "Offer",
        "No Response": "No Response",
        "Saved": "Other",
        "Applied": "Other",
    }.get(status, "Other")


def _next_action_for_status(status: str) -> str:
    return {
        "Confirmation Received": "Wait for the next response and follow up if needed.",
        "Interview Scheduled": "Confirm availability and prepare interview notes.",
        "Assessment": "Review the assessment instructions and deadline.",
        "Rejected": "Close the application and capture useful notes.",
        "Follow-up Needed": "Send or prepare a polite follow-up message.",
        "Offer": "Review the offer details and prepare a response.",
        "No Response": "Archive or mark the application as no response.",
        "Saved": "Review the saved application and decide whether to apply.",
        "Applied": "Wait for response and follow up if needed.",
    }.get(status, "Review manually and decide whether the application needs an update.")


def _follow_up_days_for_status(status: str) -> int | None:
    return {
        "Confirmation Received": 7,
        "Interview Scheduled": 1,
        "Assessment": 2,
        "Follow-up Needed": 0,
        "Offer": 2,
        "Applied": 7,
        "Saved": 7,
    }.get(status)


def _render_email_update_preview(
    application: dict,
    classification: dict,
    details: dict[str, str],
    recommendation: dict[str, str],
    workflow_decision: dict[str, object],
) -> None:
    current_status = str(application.get("status") or "-")
    suggested_status = str(classification.get("suggested_status") or current_status)
    confidence = float(classification.get("confidence") or 0)

    summary_cols = st.columns(4)
    _render_compact_card(summary_cols[0], "Current status", current_status)
    _render_compact_card(summary_cols[1], "Suggested status", suggested_status)
    _render_compact_card(summary_cols[2], "Email confidence", f"{confidence:.0%}")
    _render_compact_card(summary_cols[3], "Action type", workflow_decision["operation"])

    current_cols = st.columns(4)
    _render_compact_card(current_cols[0], "Company", application.get("company", "-"))
    _render_compact_card(current_cols[1], "Role", application.get("role", "-"))
    _render_compact_card(current_cols[2], "Location", application.get("location", "-"))
    _render_compact_card(current_cols[3], "Follow-up", application.get("follow_up_date") or "-")

    st.markdown("**Suggested changes from this email**")
    st.dataframe(
        pd.DataFrame(_build_email_update_rows(application, classification, details, recommendation)),
        use_container_width=True,
        hide_index=True,
    )


def _build_email_update_rows(
    application: dict,
    classification: dict,
    details: dict[str, str],
    recommendation: dict[str, str],
) -> list[dict[str, str]]:
    suggested_status = str(classification.get("suggested_status") or application.get("status") or "")
    suggested_rejection_reason = str(application.get("rejection_reason") or "")
    if suggested_status == "Rejected" and not suggested_rejection_reason:
        suggested_rejection_reason = details.get("rejection_reason") or "Rejected based on classified recruiting email."

    suggested_values = {
        "Status": suggested_status,
        "Next action": recommendation.get("next_action", ""),
        "Follow-up date": recommendation.get("follow_up_date") or application.get("follow_up_date", ""),
        "Location": application.get("location", "") or details.get("location", ""),
        "Contact": application.get("contact", "") or details.get("contact", ""),
        "Source link": application.get("source_link", "") or details.get("source_link", ""),
        "Rejection reason": suggested_rejection_reason,
    }
    current_values = {
        "Status": application.get("status", ""),
        "Next action": application.get("next_action", ""),
        "Follow-up date": application.get("follow_up_date", ""),
        "Location": application.get("location", ""),
        "Contact": application.get("contact", ""),
        "Source link": application.get("source_link", ""),
        "Rejection reason": application.get("rejection_reason", ""),
    }

    rows = []
    always_show = {"Status", "Next action", "Follow-up date"}
    for field, suggested in suggested_values.items():
        current = str(current_values.get(field) or "")
        suggested_text = str(suggested or "")
        if field not in always_show and not current and not suggested_text:
            continue
        rows.append(
            {
                "Field": field,
                "Current": current or "-",
                "Suggested": suggested_text or "-",
                "Change": _change_label(current, suggested_text),
            }
        )
    return rows


def _change_label(current: str, suggested: str) -> str:
    current_text = str(current or "").strip()
    suggested_text = str(suggested or "").strip()
    if not suggested_text:
        return "No change"
    if current_text == suggested_text:
        return "Keep"
    if not current_text:
        return "Fill"
    return "Update"


def render_email_analysis_details(
    result: dict,
    details: dict[str, str],
    match: dict | None,
    match_candidates: list[dict],
    recommendation: dict[str, str],
    has_applications: bool,
) -> None:
    summary = build_email_analysis_summary(result, details, match, candidate_count=len(match_candidates))
    classification_confidence = float(result.get("confidence") or 0)
    gate = confidence_gate(classification_confidence)
    visible_match = match or (match_candidates[0] if match_candidates else None)

    detail_cols = st.columns(5)
    _render_compact_card(detail_cols[0], "Email type", result["category"])
    _render_compact_card(detail_cols[1], "Confidence", summary["confidence_label"], f"{classification_confidence:.0%}")
    _render_compact_card(detail_cols[2], "Gate", gate["gate"])
    _render_compact_card(detail_cols[3], "Suggested status", result["suggested_status"])
    _render_compact_card(detail_cols[4], "Context fields", summary["detected_context"])

    evidence_col, context_col = st.columns([1, 1])
    with evidence_col:
        st.markdown("**Classification evidence**")
        st.write("Suggested next action:", result["suggested_next_action"])
        keyword_rows = build_keyword_rows(result)
        if keyword_rows:
            st.dataframe(pd.DataFrame(keyword_rows), use_container_width=True, hide_index=True, height=160)
        else:
            st.caption("No specific recruiting keywords were matched.")

    with context_col:
        st.markdown("**Extracted context**")
        st.dataframe(
            pd.DataFrame(build_context_rows(details)),
            use_container_width=True,
            hide_index=True,
            height=220,
        )

    if match_candidates:
        st.markdown("**Top existing application matches**")
        st.dataframe(
            pd.DataFrame(build_match_candidate_rows(match_candidates, selected_match=match)),
            use_container_width=True,
            hide_index=True,
            height=170,
        )
    elif has_applications:
        st.caption("No existing application passed the match threshold.")

    if visible_match:
        reason_col, signal_col = st.columns([2, 1])
        with reason_col:
            reason_rows = build_match_reason_rows(visible_match)
            if reason_rows:
                st.dataframe(pd.DataFrame(reason_rows), use_container_width=True, hide_index=True, height=180)
        with signal_col:
            st.dataframe(
                pd.DataFrame(build_match_signal_rows(visible_match)),
                use_container_width=True,
                hide_index=True,
                height=180,
            )

    st.markdown("**Confidence threshold rules**")
    st.dataframe(pd.DataFrame(build_confidence_threshold_rows()), use_container_width=True, hide_index=True)


def render_email_analysis_report(
    result: dict,
    details: dict[str, str],
    match: dict | None,
    match_candidates: list[dict],
    recommendation: dict[str, str],
    has_applications: bool,
) -> None:
    summary = build_email_analysis_summary(result, details, match, candidate_count=len(match_candidates))
    classification_confidence = float(result.get("confidence") or 0)
    gate = confidence_gate(classification_confidence)
    visible_match = match or (match_candidates[0] if match_candidates else None)
    best_match_label = (
        f"{visible_match['company']} / {visible_match['role']}"
        if visible_match
        else ("Manual selection needed" if has_applications else "Create a new record")
    )

    st.subheader("Recommendation")
    summary_cols = st.columns(5)
    _render_compact_card(summary_cols[0], "Email type", result["category"])
    _render_compact_card(summary_cols[1], "Confidence", summary["confidence_label"], f"{classification_confidence:.0%}")
    _render_compact_card(summary_cols[2], "Gate", gate["gate"])
    _render_compact_card(summary_cols[3], "Suggested status", result["suggested_status"])
    _render_compact_card(summary_cols[4], "Best match", best_match_label)
    st.info(summary["decision"])
    st.caption(f"{summary['confidence_description']} Threshold: {gate['threshold']} - {gate['allowed_action']}.")

    if match_candidates:
        if match:
            st.success(f"Best match: {match['company']} / {match['role']}")
        else:
            st.warning("No auto-selected confident match. Review the ranked candidates before applying changes.")
    elif has_applications:
        st.warning("No confident application match found. Select one manually below or create a new record.")
    else:
        st.info("No existing applications are available yet. Use the extracted context to create a new record.")

    with st.expander("Review extracted context and classification evidence"):
        evidence_col, context_col = st.columns([1, 1])
        with evidence_col:
            st.markdown("**Classification Evidence**")
            st.write("Suggested next action:", result["suggested_next_action"])
            keyword_rows = build_keyword_rows(result)
            if keyword_rows:
                st.dataframe(pd.DataFrame(keyword_rows), use_container_width=True, hide_index=True, height=160)
            else:
                st.caption("No specific recruiting keywords were matched.")

        with context_col:
            st.markdown("**Extracted Application Context**")
            st.dataframe(
                pd.DataFrame(build_context_rows(details)),
                use_container_width=True,
                hide_index=True,
                height=260,
            )
            if details.get("source_link"):
                st.write("Source link:", details["source_link"])

    with st.expander("Review application match details"):
        if match_candidates:
            st.markdown("**Top 3 Existing Application Matches**")
            st.caption(f"Showing {len(match_candidates)} candidate(s), ranked by score and confidence.")
            st.dataframe(
                pd.DataFrame(build_match_candidate_rows(match_candidates, selected_match=match)),
                use_container_width=True,
                hide_index=True,
                height=170,
            )
        elif has_applications:
            st.caption("No candidates were strong enough to rank for this email.")
        else:
            st.caption("Add or import applications to enable existing-record matching.")

        if visible_match:
            match_confidence = float(visible_match.get("confidence") or 0)
            match_cols = st.columns(4)
            _render_compact_card(match_cols[0], "Match status", summary["match_label"])
            _render_compact_card(match_cols[1], "Match confidence", f"{match_confidence:.0%}")
            _render_compact_card(match_cols[2], "Match score", visible_match["score"])
            _render_compact_card(match_cols[3], "Workflow priority", recommendation["priority"])

            reason_col, signal_col = st.columns([2, 1])
            with reason_col:
                reason_rows = build_match_reason_rows(visible_match)
                if reason_rows:
                    st.dataframe(pd.DataFrame(reason_rows), use_container_width=True, hide_index=True, height=180)
            with signal_col:
                st.dataframe(
                    pd.DataFrame(build_match_signal_rows(visible_match)),
                    use_container_width=True,
                    hide_index=True,
                    height=180,
                )

    with st.expander("Confidence threshold rules"):
        st.dataframe(
            pd.DataFrame(build_confidence_threshold_rows()),
            use_container_width=True,
            hide_index=True,
        )


def render_email_templates(applications: list[dict]) -> None:
    st.subheader("Generate Career Email Template")
    if not applications:
        st.info("Add or import an application first to generate a personalized template.")
        return

    label_id_map = _application_label_id_map(applications)
    selected_label = st.selectbox("Application", list(label_id_map.keys()), key="template_application_select")
    selected_id = label_id_map[selected_label]
    selected = next(item for item in applications if item["id"] == selected_id)

    suggested_type = suggest_template_type(selected)
    suggested_index = TEMPLATE_TYPES.index(suggested_type)

    col_type, col_language, col_recipient, col_sender = st.columns(4)
    template_type = col_type.selectbox(
        "Template type",
        TEMPLATE_TYPES,
        index=suggested_index,
        key=f"template_type_{selected_id}",
    )
    template_language = col_language.selectbox(
        "Language",
        TEMPLATE_LANGUAGES,
        key=f"template_language_{selected_id}",
    )
    recipient_name = col_recipient.text_input(
        "Recipient name",
        value=_recipient_name_from_contact(selected.get("contact", "")),
        key=f"template_recipient_{selected_id}",
    )
    sender_name = col_sender.text_input("Sender name", value="Yibo Zhang", key="template_sender")

    generated = generate_email_template(
        selected,
        template_type=template_type,
        recipient_name=recipient_name,
        sender_name=sender_name,
        language=template_language,
    )

    template_key = f"{selected_id}_{template_type}_{template_language}"
    st.text_input("Subject", value=generated["subject"], key=f"template_subject_{template_key}")
    st.text_area(
        "Email body",
        value=generated["body"],
        height=320,
        key=f"template_body_{template_key}",
    )


def render_gmail_sync_tools(applications: list[dict]) -> None:
    st.subheader("Gmail Recruiting Email Sync")
    st.caption(
        "Local-only Gmail API sync. Uses read-only access and previews suggestions before changing applications."
    )
    query = st.text_input("Gmail search query", value=DEFAULT_GMAIL_QUERY, key="gmail_query")
    max_results = st.number_input("Max emails", min_value=1, max_value=25, value=10, step=1, key="gmail_max")
    col_credentials, col_token = st.columns(2)
    credentials_path = col_credentials.text_input(
        "OAuth credentials path",
        value="credentials.json",
        key="gmail_credentials_path",
    )
    token_path = col_token.text_input("Token path", value="token.json", key="gmail_token_path")

    if st.button("Sync Gmail emails", key="gmail_sync_button"):
        try:
            emails = fetch_recruiting_emails(
                credentials_path=credentials_path,
                token_path=token_path,
                query=query,
                max_results=int(max_results),
            )
            st.session_state["gmail_sync_preview"] = build_gmail_sync_preview(emails, applications)
        except (GmailDependencyError, GmailConfigurationError) as error:
            st.error(str(error))
            st.info("Install optional dependencies with `pip install -r requirements-gmail.txt`.")

    previews = st.session_state.get("gmail_sync_preview", [])
    if not previews:
        st.info("Sync Gmail to preview recruiting email classifications here.")
        return

    st.write(f"Previewed {len(previews)} email(s). Select rows to apply suggested updates.")
    preview_df = _gmail_preview_display_df(previews)
    edited_preview = st.data_editor(
        preview_df,
        use_container_width=True,
        hide_index=True,
        disabled=[
            "index",
            "subject",
            "sender",
            "category",
            "confidence",
            "suggested_status",
            "company",
            "role",
            "matched_application",
        ],
        column_config={
            "apply": st.column_config.CheckboxColumn("apply"),
            "confidence": st.column_config.TextColumn("confidence"),
            "subject": st.column_config.TextColumn("subject", width="large"),
            "matched_application": st.column_config.TextColumn("matched_application", width="large"),
        },
        key="gmail_sync_preview_editor",
    )

    if st.button("Apply selected Gmail suggestions", key="gmail_apply_selected"):
        apply_result = _apply_selected_gmail_suggestions(previews, edited_preview, applications)
        st.success(
            f"Applied Gmail suggestions: {apply_result['updated']} updated, "
            f"{apply_result['created']} created, {apply_result['skipped']} skipped."
        )
        st.session_state["gmail_sync_preview"] = []
        st.rerun()


def _application_label_id_map(applications: list[dict]) -> dict[str, int]:
    return {
        f"{application['id']} - {application.get('company', '')} - {application.get('role', '')}": int(
            application["id"]
        )
        for application in applications
    }


def _option_index(options: list[str], value: str) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


def _text_to_date(value: object) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _matched_label_index(
    labels: list[str],
    label_id_map: dict[str, int],
    match: dict | None,
) -> int:
    if not match:
        return 0

    matched_id = int(match["application_id"])
    for index, label in enumerate(labels):
        if label_id_map[label] == matched_id:
            return index
    return 0


def _match_for_application_id(
    application_id: int,
    match: dict | None,
    match_candidates: list[dict],
) -> dict | None:
    if match and int(match.get("application_id") or 0) == application_id:
        return match
    return next(
        (candidate for candidate in match_candidates if int(candidate.get("application_id") or 0) == application_id),
        None,
    )


def _gmail_preview_display_df(previews: list[dict]) -> pd.DataFrame:
    rows = []
    for preview in previews:
        rows.append(
            {
                "apply": preview["apply"],
                "index": preview["index"],
                "subject": preview["subject"],
                "sender": preview["sender"],
                "category": preview["category"],
                "confidence": f"{preview['confidence']:.0%}",
                "suggested_status": preview["suggested_status"],
                "company": preview["company"],
                "role": preview["role"],
                "location": preview["location"],
                "matched_application": preview["matched_application"],
            }
        )
    return pd.DataFrame(rows)


def _apply_selected_gmail_suggestions(
    previews: list[dict],
    edited_preview: pd.DataFrame,
    applications: list[dict],
) -> dict[str, int]:
    selected_indexes = {int(row["index"]) for row in edited_preview.to_dict(orient="records") if bool(row.get("apply"))}
    preview_by_index = {int(preview["index"]): preview for preview in previews}
    result = {"updated": 0, "created": 0, "skipped": 0}

    for index in selected_indexes:
        preview = preview_by_index[index]
        action = apply_gmail_preview(preview, applications)
        result[action] += 1
    return result


def _recipient_name_from_contact(contact: object) -> str:
    text = str(contact or "").strip()
    if not text:
        return ""
    if "<" in text:
        return text.split("<", 1)[0].strip()
    if "@" in text:
        return ""
    return text
