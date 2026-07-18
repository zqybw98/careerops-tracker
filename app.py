from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st
from src.analytics import (
    build_applications_per_month,
    build_average_waiting_days_by_company,
    build_channel_role_type_matrix,
    build_follow_up_effectiveness,
    build_interview_conversion_by_role_type,
    build_interview_to_offer_funnel,
    build_pipeline_health,
    build_rejection_reason_breakdown,
    build_response_rate_by_source,
    build_saved_vs_applied_summary,
    build_stale_pipeline_breakdown,
    build_time_to_first_response_by_source,
)
from src.application_filters import build_bulk_update_payload, filter_applications
from src.application_note_parser import build_application_payload, parse_application_note
from src.dashboard import build_daily_dashboard_sections, build_summary, filter_dashboard_applications
from src.database import (
    create_application,
    create_company_research_note,
    delete_application,
    get_application_events,
    get_applications,
    get_company_research_notes,
    init_db,
    update_application,
)
from src.duplicates import find_likely_duplicate_applications, format_duplicate_candidate
from src.email_insights import confidence_gate
from src.models import DEFAULT_NEXT_ACTION_BY_STATUS, STATUS_OPTIONS, normalize_status
from src.reminder_actions import PendingAction, build_pending_action_payload
from src.reminder_engine import generate_reminders
from src.services.email_workflow import (
    apply_email_workflow_update,
    build_email_workflow_for_application,
    classify_email_for_workflow,
)
from src.ui.applications_page import render_applications_page
from src.ui.components import render_app_header, with_display_sequence
from src.ui.more_page import render_more_page
from src.ui.sidebar import normalize_workspace, render_sidebar_navigation

DASHBOARD_EDITOR_COLUMNS = [
    "#",
    "company",
    "role",
    "location",
    "application_date",
    "status",
    "next_action",
    "follow_up_date",
]

DASHBOARD_EDITABLE_COLUMNS = [
    "company",
    "role",
    "location",
    "application_date",
    "status",
    "next_action",
    "follow_up_date",
]

DASHBOARD_SECTION_COLUMNS = [
    "#",
    "company",
    "role",
    "application_date",
    "status",
    "next_action",
    "follow_up_date",
    "source_link",
    "updated_at",
]

st.set_page_config(
    page_title="CareerOps Tracker",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1480px;
        padding-top: 3.25rem;
        padding-bottom: 3rem;
    }
    [data-testid="stSidebar"] {
        background: #111418;
    }
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        font-size: 1.05rem;
    }
    div[data-testid="stMetric"] {
        background: #131820;
        border: 1px solid #252b35;
        border-radius: 8px;
        padding: 0.85rem 1rem;
    }
    div[data-testid="stExpander"] {
        border-color: #252b35;
        border-radius: 8px;
    }
    div[data-testid="stTabs"] button {
        font-weight: 600;
    }
    div[data-testid="stDataFrame"] div[role="gridcell"],
    div[data-testid="stDataFrame"] div[role="columnheader"] {
        font-size: 15px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

init_db()

WORKSPACE_NAV_REQUEST_KEY = "_workspace_nav_request"


def main() -> None:
    _apply_workspace_navigation_request()
    applications = get_applications()
    reminders = generate_reminders(applications)

    workspace = render_sidebar_navigation(applications, reminders)
    render_app_header(workspace)

    if workspace == "Applications":
        render_applications_page(applications)
    elif workspace == "Analytics":
        render_analytics(applications, reminders)
    else:
        render_more_page(applications, render_advanced_applications=render_applications)


def render_analytics(applications: list[dict], reminders: list[dict]) -> None:
    del reminders
    sections = build_daily_dashboard_sections(applications)
    include_closed = st.toggle(
        "Include closed applications in analytics",
        value=False,
        key="analytics_include_closed_applications",
        help="Include rejected records in analytics and charts.",
    )
    visible_applications = filter_dashboard_applications(applications, include_closed=include_closed)
    hidden_closed_count = len(applications) - len(visible_applications)

    if not include_closed and hidden_closed_count:
        st.caption(f"Hiding {hidden_closed_count} rejected application(s) from active analytics.")

    summary = build_summary(visible_applications)
    pipeline_health = build_pipeline_health(visible_applications)

    metric_columns = st.columns(6)
    metric_columns[0].metric("Total shown", summary["total"])
    metric_columns[1].metric("This week", summary["applied_this_week"])
    metric_columns[2].metric("Waiting / Applied", summary["waiting"])
    metric_columns[3].metric("Interview / Assessment", summary["interviews"])
    metric_columns[4].metric("Action needed", len(sections["today_actions"]))
    if include_closed:
        metric_columns[5].metric("Rejected", summary["rejections"])
    else:
        metric_columns[5].metric("Rejected hidden", hidden_closed_count)

    if not visible_applications:
        if applications:
            st.info(
                "No active applications to analyze. Turn on Include closed applications to review rejected records."
            )
        else:
            st.info("Add your first application to start building the dashboard.")
        return

    df = pd.DataFrame(visible_applications)
    events = get_application_events()

    status_counts = df["status"].value_counts().reset_index()
    status_counts.columns = ["status", "count"]
    fig = px.bar(
        status_counts,
        x="status",
        y="count",
        color="status",
        title="Applications by Status",
        text="count",
    )
    fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Applications")
    _style_bar_labels(fig)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Decision Analytics")
    health_columns = st.columns(4)
    health_columns[0].metric("Response rate", _format_rate(pipeline_health["response_rate"]))
    health_columns[1].metric("Interview conversion", _format_rate(pipeline_health["interview_conversion_rate"]))
    health_columns[2].metric("Avg active waiting", f"{pipeline_health['average_active_waiting_days']} days")
    health_columns[3].metric("Stale open", pipeline_health["stale_open_applications"])

    activity_col, source_col = st.columns(2)
    with activity_col:
        monthly_df = pd.DataFrame(build_applications_per_month(visible_applications))
        if monthly_df.empty:
            st.info("Add application dates to see monthly application volume.")
        else:
            monthly_fig = px.bar(
                monthly_df,
                x="month",
                y="applications",
                title="Applications per Month",
                text="applications",
            )
            monthly_fig.update_layout(xaxis_title="", yaxis_title="Applications")
            _style_bar_labels(monthly_fig)
            st.plotly_chart(monthly_fig, use_container_width=True)

    with source_col:
        source_df = _with_rate_percent(
            pd.DataFrame(build_response_rate_by_source(visible_applications)),
            "response_rate",
        )
        if source_df.empty:
            st.info("Add source links to compare response rates by channel.")
        else:
            source_fig = px.bar(
                source_df,
                x="source",
                y="response_rate_percent",
                color="source",
                title="Response Rate by Source",
                hover_data=["applications", "responses"],
                text="response_rate_label",
            )
            source_fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Response rate (%)")
            _style_bar_labels(source_fig)
            st.plotly_chart(source_fig, use_container_width=True)

    conversion_col, aging_col = st.columns(2)
    with conversion_col:
        conversion_df = _with_rate_percent(
            pd.DataFrame(build_interview_conversion_by_role_type(visible_applications)),
            "conversion_rate",
        )
        if conversion_df.empty:
            st.info("Add roles to compare conversion by role type.")
        else:
            conversion_fig = px.bar(
                conversion_df,
                x="role_type",
                y="conversion_rate_percent",
                color="role_type",
                title="Interview Conversion by Role Type",
                hover_data=["applications", "interview_or_assessment"],
                text="conversion_rate_label",
            )
            conversion_fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Conversion rate (%)")
            _style_bar_labels(conversion_fig)
            st.plotly_chart(conversion_fig, use_container_width=True)

    with aging_col:
        waiting_df = pd.DataFrame(build_average_waiting_days_by_company(visible_applications))
        if waiting_df.empty:
            st.info("Open applications with dates will show company waiting time.")
        else:
            waiting_fig = px.bar(
                waiting_df,
                x="average_waiting_days",
                y="company",
                orientation="h",
                title="Average Waiting Days by Company",
                hover_data=["open_applications"],
                text="average_waiting_days",
            )
            waiting_fig.update_layout(xaxis_title="Days", yaxis_title="")
            _style_bar_labels(waiting_fig, texttemplate="%{text:.1f} days")
            st.plotly_chart(waiting_fig, use_container_width=True)

    stale_col, saved_col = st.columns(2)
    with stale_col:
        stale_df = pd.DataFrame(build_stale_pipeline_breakdown(visible_applications))
        if stale_df.empty:
            st.info("No open applications to age yet.")
        else:
            stale_fig = px.bar(
                stale_df,
                x="bucket",
                y="applications",
                color="status",
                title="Stale Pipeline Breakdown",
                text="applications",
            )
            stale_fig.update_layout(xaxis_title="", yaxis_title="Open applications")
            _style_bar_labels(stale_fig, position="auto")
            st.plotly_chart(stale_fig, use_container_width=True)

    with saved_col:
        saved_df = pd.DataFrame(build_saved_vs_applied_summary(visible_applications))
        saved_fig = px.bar(
            saved_df,
            x="stage",
            y="applications",
            color="stage",
            title="Saved vs Submitted",
            text="applications",
        )
        saved_fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Applications")
        _style_bar_labels(saved_fig)
        st.plotly_chart(saved_fig, use_container_width=True)

    response_time_col, rejection_reason_col = st.columns(2)
    with response_time_col:
        response_time_df = pd.DataFrame(build_time_to_first_response_by_source(visible_applications, events))
        if response_time_df.empty:
            st.info("Status-change history will show time-to-first-response by source.")
        else:
            response_time_fig = px.bar(
                response_time_df,
                x="source",
                y="average_days_to_first_response",
                color="source",
                title="Time to First Response by Source",
                hover_data=["responses"],
                text="average_days_to_first_response",
            )
            response_time_fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Average days")
            _style_bar_labels(response_time_fig, texttemplate="%{text:.1f} days")
            st.plotly_chart(response_time_fig, use_container_width=True)

    with rejection_reason_col:
        rejection_df = pd.DataFrame(build_rejection_reason_breakdown(visible_applications))
        if rejection_df.empty:
            st.info("Rejected applications with reasons will show a breakdown here.")
        else:
            rejection_fig = px.bar(
                rejection_df,
                x="applications",
                y="rejection_reason",
                orientation="h",
                title="Rejection Reason Breakdown",
                text="applications",
            )
            rejection_fig.update_layout(xaxis_title="Applications", yaxis_title="")
            _style_bar_labels(rejection_fig)
            st.plotly_chart(rejection_fig, use_container_width=True)

    funnel_col, follow_up_col = st.columns(2)
    with funnel_col:
        funnel_df = _with_rate_percent(
            pd.DataFrame(build_interview_to_offer_funnel(visible_applications, events)),
            "conversion_rate",
        )
        if funnel_df.empty:
            st.info("Application status history will show interview-to-offer funnel.")
        else:
            funnel_fig = px.bar(
                funnel_df,
                x="stage",
                y="applications",
                color="stage",
                title="Interview-to-Offer Funnel",
                hover_data=["conversion_rate_label"],
                text="applications",
            )
            funnel_fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Applications")
            _style_bar_labels(funnel_fig)
            st.plotly_chart(funnel_fig, use_container_width=True)

    with follow_up_col:
        follow_up_df = _with_rate_percent(
            pd.DataFrame(build_follow_up_effectiveness(visible_applications, events)),
            "share",
        )
        if follow_up_df.empty:
            st.info("Applications with follow-up dates will show follow-up effectiveness.")
        else:
            follow_up_fig = px.bar(
                follow_up_df,
                x="outcome",
                y="applications",
                color="outcome",
                title="Follow-up Effectiveness",
                hover_data=["share_label"],
                text="applications",
            )
            follow_up_fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Applications")
            _style_bar_labels(follow_up_fig)
            st.plotly_chart(follow_up_fig, use_container_width=True)

    matrix_df = _with_rate_percent(pd.DataFrame(build_channel_role_type_matrix(visible_applications)), "response_rate")
    if not matrix_df.empty:
        matrix_df = _with_rate_percent(matrix_df, "interview_rate")
        st.subheader("Channel x Role-Type Cross Analysis")
        st.dataframe(
            matrix_df[
                [
                    "source",
                    "role_type",
                    "applications",
                    "response_rate_label",
                    "interview_rate_label",
                ]
            ].rename(
                columns={
                    "source": "Source",
                    "role_type": "Role type",
                    "applications": "Applications",
                    "response_rate_label": "Response rate",
                    "interview_rate_label": "Interview rate",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )


def _render_action_center(applications: list[dict], reminders: list[dict], sections: dict[str, list[dict]]) -> None:
    today = date.today()
    overdue_reminders = [
        reminder for reminder in reminders if (_text_to_date(reminder.get("due_date")) or today) < today
    ]
    today_reminders = [
        reminder for reminder in reminders if (_text_to_date(reminder.get("due_date")) or today) == today
    ]
    waiting_follow_up = _waiting_applications_may_need_follow_up(applications, today)
    recent_applications = _recent_active_applications(applications)

    action_cols = st.columns([1, 1, 1, 1, 1, 1.2, 1.2])
    action_cols[0].metric("Overdue", len(overdue_reminders))
    action_cols[1].metric("Due today", len(today_reminders))
    action_cols[2].metric("Due this week", len(sections["due_soon"]))
    action_cols[3].metric("Waiting follow-up", len(waiting_follow_up))
    action_cols[4].metric("Recent active", len(recent_applications))
    action_cols[5].button(
        "Add application",
        key="action_center_add_application",
        type="primary",
        use_container_width=True,
        on_click=_go_to_applications_workspace,
    )
    action_cols[6].button(
        "Email Assistant",
        key="action_center_email_assistant",
        use_container_width=True,
        on_click=_go_to_email_assistant_workspace,
    )

    urgent_col, pipeline_col = st.columns([1.05, 1])
    with urgent_col:
        st.markdown("**Overdue / Today**")
        urgent_reminders = overdue_reminders[:3] + today_reminders[: max(0, 4 - len(overdue_reminders[:3]))]
        if not urgent_reminders:
            st.success("No action is due right now.")
        for reminder in urgent_reminders:
            render_pending_action_card(reminder, applications)
        if len(overdue_reminders) + len(today_reminders) > len(urgent_reminders):
            st.caption("More due actions are available in the detailed workflow list below.")

    with pipeline_col:
        _render_compact_action_table(
            "Follow-up Due Soon",
            sections["due_soon"],
            empty_message="No follow-ups are due in the next 7 days.",
            limit=5,
        )
        _render_compact_action_table(
            "Waiting Applications That May Need Follow-up",
            waiting_follow_up,
            empty_message="No stale waiting applications detected.",
            limit=5,
        )
        _render_compact_action_table(
            "Recent Applications",
            recent_applications,
            empty_message="No recent active applications yet.",
            limit=5,
        )


def _render_overview_quick_tools(applications: list[dict]) -> None:
    quick_update_tab, email_tab = st.tabs(["Quick Update", "Paste Email Update"])
    with quick_update_tab:
        _render_overview_quick_update(applications)
    with email_tab:
        _render_overview_email_shortcut(applications)


def _render_overview_quick_update(applications: list[dict]) -> None:
    st.caption("Fast status, next-action, and follow-up edits without opening the full Applications form.")
    if not applications:
        st.info("Add an application before using Quick Update.")
        return

    label_id_map = _application_label_id_map(applications)
    selected_label = st.selectbox(
        "Application",
        list(label_id_map.keys()),
        key="overview_quick_update_application",
    )
    selected_id = label_id_map[selected_label]
    selected = _application_by_id(applications, selected_id)
    if selected is None:
        st.warning("Selected application was not found.")
        return

    with st.form(f"overview_quick_update_form_{selected_id}"):
        status_col, follow_col = st.columns([1, 1])
        current_status = normalize_status(selected.get("status"))
        status = status_col.selectbox(
            "Status",
            STATUS_OPTIONS,
            index=_option_index(STATUS_OPTIONS, current_status),
        )
        keep_follow_up = follow_col.checkbox(
            "Set follow-up date",
            value=bool(selected.get("follow_up_date")) and status != "Rejected",
            disabled=status == "Rejected",
        )
        follow_up_date = follow_col.date_input(
            "Follow-up date",
            value=_text_to_date(selected.get("follow_up_date")) or date.today() + timedelta(days=7),
            disabled=not keep_follow_up or status == "Rejected",
        )
        next_action = st.text_input(
            "Next action",
            value="No action" if status == "Rejected" else str(selected.get("next_action", "")),
        )
        note = st.text_area("Append note", height=90, placeholder="Short note, for example: recruiter replied today.")

        if st.form_submit_button("Save quick update", type="primary"):
            incoming_note = note.strip()
            if status == "Rejected" and not incoming_note:
                incoming_note = f"Rejection received by quick update on {date.today().isoformat()}."
            update_application(
                selected_id,
                {
                    **selected,
                    "status": status,
                    "next_action": next_action,
                    "follow_up_date": follow_up_date.isoformat() if keep_follow_up and status != "Rejected" else "",
                    "notes": _join_notes(selected.get("notes", ""), incoming_note),
                },
                source="quick_update",
            )
            st.success(f"Quick update saved for {selected.get('company', '')} / {selected.get('role', '')}.")
            st.rerun()


def _render_overview_email_shortcut(applications: list[dict]) -> None:
    st.caption("Paste a recruiting email here for a compact preview. Use the full Email Assistant for detailed review.")
    with st.container(border=True):
        subject = st.text_input("Email subject", key="overview_email_subject")
        body = st.text_area(
            "Email body or recruiter message",
            height=150,
            key="overview_email_body",
            placeholder="Paste the email text here...",
        )
        analyze_col, open_col = st.columns([1, 3])
        if analyze_col.button("Analyze email", key="overview_analyze_email", type="primary"):
            if not subject.strip() and not body.strip():
                st.warning("Paste an email subject or body first.")
            else:
                st.session_state["overview_email_workflow"] = classify_email_for_workflow(
                    subject=subject,
                    body=body,
                    applications=applications,
                    use_feedback=True,
                )
                st.session_state["overview_email_workflow_subject"] = subject
                st.session_state["overview_email_workflow_body"] = body
        open_col.caption("High-confidence matches can be applied here; everything else opens in Email Assistant.")

    workflow = st.session_state.get("overview_email_workflow")
    if isinstance(workflow, dict):
        _render_overview_email_preview(
            workflow,
            applications,
            str(st.session_state.get("overview_email_workflow_subject", "")),
            str(st.session_state.get("overview_email_workflow_body", "")),
        )


def _render_overview_email_preview(
    workflow: dict[str, Any],
    applications: list[dict],
    subject: str,
    body: str,
) -> None:
    classification = workflow["classification"]
    details = workflow["details"]
    match = workflow.get("match")
    match_candidates = workflow.get("match_candidates", [])
    confidence = float(classification.get("confidence") or 0)
    gate = confidence_gate(confidence)
    matched_application = (
        _application_by_id(applications, int(match.get("application_id") or 0)) if isinstance(match, dict) else None
    )

    recommendation: dict[str, Any] = {
        "next_action": classification.get("suggested_next_action", ""),
        "follow_up_date": details.get("suggested_follow_up_date", ""),
    }
    workflow_decision: dict[str, Any] = {"status_update_allowed": False, "primary_action_label": "Apply update"}
    operation_summary: dict[str, str] | None = None
    if matched_application is not None:
        workflow_context = build_email_workflow_for_application(
            classification,
            details,
            matched_application,
            match,
            match_candidates,
        )
        recommendation = workflow_context["recommendation"]
        workflow_decision = workflow_context["workflow_decision"]
        operation_summary = workflow_context["operation_summary"]

    st.markdown("**Suggested update preview**")
    preview_cols = st.columns(6)
    preview_cols[0].metric("Category", str(classification.get("category", "Other")))
    preview_cols[1].metric("Confidence", f"{confidence:.0%}")
    preview_cols[2].metric("Gate", gate["gate"])
    preview_cols[3].metric("Suggested status", normalize_status(classification.get("suggested_status")))
    preview_cols[4].metric("Company", details.get("company") or (matched_application or {}).get("company", "-"))
    preview_cols[5].metric("Role", details.get("role") or (matched_application or {}).get("role", "-"))
    st.info(str(recommendation.get("next_action") or "Review this email manually."))

    if matched_application is not None:
        st.success(
            "Matched existing application: "
            f"{matched_application.get('company', '')} / {matched_application.get('role', '')}"
        )
    elif match_candidates:
        st.warning("Possible matches found, but none were confident enough for a direct update.")
    else:
        st.warning("No existing application match found. Open Email Assistant to review or create a new record.")

    apply_allowed = (
        matched_application is not None
        and gate["gate"] == "Ready"
        and bool(workflow_decision.get("status_update_allowed"))
    )
    apply_col, full_review_col = st.columns([1, 2])
    if apply_col.button(
        str(workflow_decision.get("primary_action_label") or "Apply suggested update"),
        key="overview_apply_email_update",
        type="primary",
        disabled=not apply_allowed,
    ):
        if matched_application is None:
            st.warning("No matched application is available for this update.")
        else:
            apply_email_workflow_update(
                int(matched_application["id"]),
                matched_application,
                classification,
                details,
                recommendation,
                apply_status=True,
                operation_summary=operation_summary,
            )
            st.success("Suggested email update applied.")
            st.rerun()
    if not apply_allowed:
        st.caption("Status update is disabled unless the match exists and the confidence gate is Ready.")

    if full_review_col.button("Open in Email Assistant for full review", key="overview_open_email_assistant"):
        _prime_email_assistant_from_overview(subject, body, workflow)
        _go_to_email_assistant_workspace()
        st.rerun()


def _prime_email_assistant_from_overview(subject: str, body: str, workflow: dict[str, Any]) -> None:
    st.session_state["email_subject_input"] = subject
    st.session_state["email_body_input"] = body
    st.session_state["last_email_subject"] = subject
    st.session_state["last_email_body"] = body
    st.session_state["last_classification"] = workflow["classification"]
    st.session_state["last_email_details"] = workflow["details"]
    st.session_state["last_application_match"] = workflow["match"]
    st.session_state["last_application_matches"] = workflow["match_candidates"]
    st.session_state["last_email_feedback"] = workflow["feedback"]


def _render_compact_action_table(
    title: str,
    rows: list[dict],
    *,
    empty_message: str,
    limit: int,
) -> None:
    st.markdown(f"**{title}**")
    if not rows:
        st.caption(empty_message)
        return
    compact_columns = ["company", "role", "status", "next_action", "follow_up_date"]
    display_df = pd.DataFrame(rows[:limit])
    available_columns = [column for column in compact_columns if column in display_df.columns]
    st.dataframe(display_df[available_columns], use_container_width=True, hide_index=True, height=180)
    if len(rows) > limit:
        st.caption(f"Showing {limit} of {len(rows)} records.")


def _waiting_applications_may_need_follow_up(applications: list[dict], today: date) -> list[dict]:
    candidates: list[dict] = []
    for application in applications:
        status = normalize_status(application.get("status"))
        if status not in {"Applied", "Waiting", "Interview / Assessment"}:
            continue
        if _text_to_date(application.get("follow_up_date")):
            continue
        application_date = _text_to_date(application.get("application_date"))
        if application_date and (today - application_date).days >= 7:
            candidates.append(application)
    return sorted(
        candidates,
        key=lambda item: _text_to_date(item.get("application_date")) or date.min,
        reverse=True,
    )


def _recent_active_applications(applications: list[dict]) -> list[dict]:
    active_applications = [
        application for application in applications if normalize_status(application.get("status")) != "Rejected"
    ]
    return sorted(
        active_applications,
        key=lambda item: (
            _text_to_date(item.get("application_date")) or date.min,
            str(item.get("updated_at", "")),
        ),
        reverse=True,
    )[:8]


def _render_dashboard_section(
    title: str,
    rows: list[dict],
    *,
    empty_message: str,
    include_rejection_reason: bool = False,
    limit: int = 10,
) -> None:
    st.subheader(title)
    if not rows:
        st.info(empty_message)
        return

    section_df = with_display_sequence(pd.DataFrame(rows[:limit]))
    columns = list(DASHBOARD_SECTION_COLUMNS)
    if include_rejection_reason:
        columns.insert(-1, "rejection_reason")
    available_columns = [column for column in columns if column in section_df.columns]
    display_df = section_df[available_columns].rename(
        columns={
            "company": "Company",
            "role": "Position",
            "application_date": "Application Date",
            "status": "Status",
            "next_action": "Next Action",
            "follow_up_date": "Follow-up Date",
            "source_link": "Source",
            "rejection_reason": "Rejection Reason",
            "updated_at": "Last Updated",
        }
    )
    st.dataframe(display_df, use_container_width=True, hide_index=True)
    if len(rows) > limit:
        st.caption(f"Showing {limit} of {len(rows)} records. Use Applications for the full list.")


def _go_to_applications_workspace() -> None:
    _request_workspace_navigation("Applications")


def _go_to_email_assistant_workspace() -> None:
    st.session_state["more_section"] = "Email tools"
    _request_workspace_navigation("More")


def _request_workspace_navigation(workspace: str) -> None:
    st.session_state[WORKSPACE_NAV_REQUEST_KEY] = normalize_workspace(workspace)


def _apply_workspace_navigation_request() -> None:
    requested_workspace = st.session_state.pop(WORKSPACE_NAV_REQUEST_KEY, None)
    if requested_workspace:
        st.session_state["workspace_nav"] = normalize_workspace(requested_workspace)


def render_pending_action_card(reminder: dict, applications: list[dict]) -> None:
    application_id = int(reminder.get("application_id") or 0)
    application = _application_by_id(applications, application_id)
    if application is None:
        return

    with st.container(border=True):
        st.markdown(
            f"**{reminder['priority']}** - {reminder['company']} / {reminder['role']}  \n"
            f"{reminder['message']}  \n"
            f"Due: `{reminder['due_date']}`"
        )
        done_col, snooze_three_col, snooze_seven_col, open_col = st.columns(4)
        key_suffix = f"{application_id}_{reminder.get('reason', '')}_{reminder.get('due_date', '')}"

        if done_col.button("Done", key=f"pending_done_{key_suffix}", use_container_width=True):
            _apply_pending_action(application, reminder, "mark_done")
            st.rerun()
        if snooze_three_col.button("Snooze 3d", key=f"pending_snooze_3_{key_suffix}", use_container_width=True):
            _apply_pending_action(application, reminder, "snooze_3")
            st.rerun()
        if snooze_seven_col.button("Snooze 7d", key=f"pending_snooze_7_{key_suffix}", use_container_width=True):
            _apply_pending_action(application, reminder, "snooze_7")
            st.rerun()
        if open_col.button("Open", key=f"pending_open_{key_suffix}", use_container_width=True):
            _open_application_from_pending(application_id)
            st.rerun()


def _apply_pending_action(application: dict, reminder: dict, action: PendingAction) -> None:
    application_id = int(application["id"])
    payload = build_pending_action_payload(application, reminder, action)
    update_application(application_id, payload, source=f"pending_{action}")

    if action == "mark_done":
        message = f"Marked done: {application.get('company', '')} / {application.get('role', '')}."
    else:
        message = (
            f"Snoozed until {payload['follow_up_date']}: "
            f"{application.get('company', '')} / {application.get('role', '')}."
        )
    st.session_state["pending_action_success_message"] = message


def _open_application_from_pending(application_id: int) -> None:
    _request_workspace_navigation("Applications")
    st.session_state["applications_pending_detail_id"] = application_id


def _application_by_id(applications: list[dict], application_id: int) -> dict | None:
    return next(
        (application for application in applications if int(application.get("id") or 0) == application_id), None
    )


def _filter_reminders_for_applications(reminders: list[dict], applications: list[dict]) -> list[dict]:
    application_ids = {str(application.get("id")) for application in applications}
    return [reminder for reminder in reminders if str(reminder.get("application_id")) in application_ids]


def render_dashboard_recent_editor(applications: list[dict], display_df: pd.DataFrame) -> None:
    editor_df = display_df[["id"] + DASHBOARD_EDITOR_COLUMNS].copy()
    edited_df = st.data_editor(
        editor_df,
        use_container_width=True,
        hide_index=True,
        height=420,
        row_height=34,
        disabled=["id", "#"],
        column_order=DASHBOARD_EDITOR_COLUMNS,
        column_config={
            "id": None,
            "#": st.column_config.NumberColumn("#", width="small"),
            "company": st.column_config.TextColumn("company", width="medium"),
            "role": st.column_config.TextColumn("role", width="large"),
            "location": st.column_config.TextColumn("location", width="small"),
            "application_date": st.column_config.TextColumn("application_date", help="Use YYYY-MM-DD."),
            "status": st.column_config.SelectboxColumn("status", options=STATUS_OPTIONS, width="medium"),
            "next_action": st.column_config.TextColumn("next_action", width="large"),
            "follow_up_date": st.column_config.TextColumn("follow_up_date", help="Use YYYY-MM-DD."),
        },
        key="dashboard_recent_applications_editor",
    )

    save_col, helper_col = st.columns([1, 4])
    if save_col.button("Save dashboard edits", key="save_dashboard_recent_edits"):
        changed_count = _save_dashboard_editor_changes(applications, editor_df, edited_df)
        if changed_count:
            st.success(f"Saved changes for {changed_count} application(s).")
            st.rerun()
        else:
            st.info("No dashboard table changes to save.")
    helper_col.caption("Edit visible fields directly here. Detailed notes and rejection reasons stay in Applications.")


def render_applications(applications: list[dict]) -> None:
    st.subheader("Add Application")
    _render_application_note_intake(applications)
    prefill = st.session_state.get("add_application_prefill", {})
    prefill_fields = prefill.get("fields", {}) if isinstance(prefill, dict) else {}
    prefill_notes = str(prefill.get("notes", "")) if isinstance(prefill, dict) else ""

    with st.form("add_application_form", clear_on_submit=True):
        col_a, col_b, col_c = st.columns(3)
        company = col_a.text_input("Company", value=str(prefill_fields.get("company", "")))
        role = col_b.text_input("Role", value=str(prefill_fields.get("role", "")))
        location = col_c.text_input("Location", value=str(prefill_fields.get("location", "Germany")))

        col_d, col_e, col_f = st.columns(3)
        application_date = col_d.date_input(
            "Application date",
            value=_text_to_date(prefill_fields.get("application_date")) or date.today(),
        )
        status = col_e.selectbox(
            "Status",
            STATUS_OPTIONS,
            index=_option_index(STATUS_OPTIONS, str(prefill_fields.get("status", "Applied"))),
        )
        has_follow_up = col_f.checkbox("Set follow-up date", value=bool(prefill_fields.get("follow_up_date")))
        follow_up_date = ""
        if has_follow_up:
            follow_up_date = col_f.date_input(
                "Follow-up date",
                value=_text_to_date(prefill_fields.get("follow_up_date")) or date.today() + timedelta(days=7),
            )

        source_link = st.text_input("Source link", value=str(prefill_fields.get("source_link", "")))
        contact = st.text_input("Contact", value=str(prefill_fields.get("contact", "")))
        next_action = st.text_input("Next action", value=str(prefill_fields.get("next_action", "")))
        rejection_reason = st.text_area(
            "Rejection reason",
            value=str(prefill_fields.get("rejection_reason", "")),
            placeholder="Optional. Useful when status is Rejected, for example after HR screen or position closed.",
        )
        notes = st.text_area("Notes", value=prefill_notes)

        submitted = st.form_submit_button("Add application")
        if submitted:
            if not company.strip() or not role.strip():
                st.error("Company and role are required.")
            else:
                payload = {
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
                    "follow_up_date": _date_to_text(follow_up_date),
                }
                duplicate_candidates = find_likely_duplicate_applications(payload, applications)
                if duplicate_candidates:
                    st.session_state["pending_duplicate_payload"] = payload
                    st.session_state["pending_duplicate_candidate_ids"] = [
                        int(candidate["application"]["id"]) for candidate in duplicate_candidates
                    ]
                    st.warning(
                        "Likely duplicate found. Review the suggested existing record before creating a new one."
                    )
                    st.rerun()
                else:
                    create_application(payload, source="manual")
                    st.session_state.pop("add_application_prefill", None)
                    st.success("Application added.")
                    st.rerun()

    _render_pending_duplicate_resolution(applications)
    _render_company_explorer(applications)

    st.subheader("Manage Applications")
    if not applications:
        st.info("No applications yet.")
        return

    duplicate_col, helper_col = st.columns([1, 4])
    if duplicate_col.button("Check duplicates", key="manage_check_duplicates"):
        likely_duplicates = _find_existing_duplicate_pairs(applications)
        st.session_state["duplicate_review_pairs"] = likely_duplicates
    helper_col.caption("Detects likely company/position duplicates without deleting any records.")
    _render_duplicate_review_pairs()

    stored_message = st.session_state.pop("application_bulk_success_message", None)
    if stored_message:
        st.success(stored_message)

    selected_statuses = st.multiselect(
        "Filter by status",
        STATUS_OPTIONS,
        default=STATUS_OPTIONS,
        key="application_status_filter",
    )
    filter_col_a, filter_col_b, filter_col_c, filter_col_d = st.columns([1.3, 1.3, 1.5, 0.8])
    company_query = filter_col_a.text_input("Search company or role", key="application_company_search")
    source_query = filter_col_b.text_input("Search source/contact/notes", key="application_source_search")
    date_range = filter_col_c.date_input("Application date range", value=(), key="application_date_range")
    start_date, end_date = _date_range_bounds(date_range)
    stale_only = filter_col_d.checkbox("Stale only", key="application_stale_only")

    filtered_applications = filter_applications(
        applications,
        statuses=selected_statuses,
        company_query=company_query,
        source_query=source_query,
        start_date=start_date,
        end_date=end_date,
        stale_only=stale_only,
    )
    st.caption(f"Showing {len(filtered_applications)} of {len(applications)} application(s).")

    if not filtered_applications:
        st.info("No applications match the current filters.")
        return

    filtered_df = with_display_sequence(pd.DataFrame(filtered_applications))
    visible_columns = [
        "#",
        "company",
        "role",
        "location",
        "application_date",
        "status",
        "next_action",
        "follow_up_date",
        "updated_at",
    ]
    bulk_df = filtered_df[visible_columns].copy()
    bulk_df.insert(0, "select", False)
    edited_bulk_df = st.data_editor(
        bulk_df,
        use_container_width=True,
        hide_index=True,
        height=360,
        disabled=[column for column in bulk_df.columns if column != "select"],
        column_config={
            "select": st.column_config.CheckboxColumn("Select", width="small"),
            "#": st.column_config.NumberColumn("#", width="small"),
            "company": st.column_config.TextColumn("company", width="medium"),
            "role": st.column_config.TextColumn("role", width="large"),
            "location": st.column_config.TextColumn("location", width="medium"),
            "application_date": st.column_config.TextColumn("application_date", width="medium"),
            "status": st.column_config.TextColumn("status", width="medium"),
            "next_action": st.column_config.TextColumn("next_action", width="large"),
            "follow_up_date": st.column_config.TextColumn("follow_up_date", width="medium"),
            "updated_at": st.column_config.TextColumn("updated_at", width="medium"),
        },
        key="applications_bulk_editor",
    )
    selected_ids = _selected_application_ids_from_editor(filtered_df, edited_bulk_df)

    bulk_col_a, bulk_col_b, bulk_col_c, bulk_col_d = st.columns([1, 1.1, 1.2, 3])
    follow_up_target = bulk_col_c.date_input(
        "Bulk follow-up date",
        value=date.today() + timedelta(days=7),
        key="bulk_follow_up_target",
    )
    if bulk_col_a.button(
        "Archive selected",
        disabled=not selected_ids,
        key="bulk_archive_applications",
    ):
        changed = _apply_bulk_application_action(selected_ids, applications, "archive")
        st.session_state["application_bulk_success_message"] = f"Archived {changed} application(s)."
        st.rerun()
    if bulk_col_b.button(
        "Mark waiting",
        disabled=not selected_ids,
        key="bulk_no_response_applications",
    ):
        changed = _apply_bulk_application_action(selected_ids, applications, "mark_no_response")
        st.session_state["application_bulk_success_message"] = f"Marked {changed} application(s) as waiting."
        st.rerun()
    if bulk_col_d.button(
        "Set follow-up for selected",
        disabled=not selected_ids,
        key="bulk_follow_up_applications",
    ):
        changed = _apply_bulk_application_action(
            selected_ids,
            applications,
            "set_follow_up",
            follow_up_date=follow_up_target,
        )
        st.session_state["application_bulk_success_message"] = f"Set follow-up for {changed} application(s)."
        st.rerun()
    bulk_col_d.caption("Select rows in the table, then apply one bulk action. These actions do not delete records.")

    label_id_map = _application_label_id_map(filtered_applications)
    edit_labels = list(label_id_map.keys())
    target_id = st.session_state.pop("application_edit_target_id", None)
    if target_id:
        target_label = _application_label_for_id(label_id_map, int(target_id))
        if target_label:
            st.session_state["application_edit_select"] = target_label
    selected_label = st.selectbox("Select application to edit", edit_labels, key="application_edit_select")
    selected_id = label_id_map[selected_label]
    selected = next(item for item in applications if item["id"] == selected_id)
    key_prefix = f"edit_{selected_id}"

    st.markdown("**Quick update**")
    with st.form(f"quick_update_application_form_{selected_id}"):
        quick_col_a, quick_col_b, quick_col_c = st.columns([1, 2, 1])
        quick_status_index = STATUS_OPTIONS.index(selected["status"]) if selected["status"] in STATUS_OPTIONS else 0
        quick_status = quick_col_a.selectbox(
            "Status",
            STATUS_OPTIONS,
            index=quick_status_index,
            key=f"quick_{selected_id}_status",
        )
        quick_next_action = quick_col_b.text_input(
            "Next action",
            value=selected.get("next_action", ""),
            key=f"quick_{selected_id}_next_action",
        )
        quick_keep_follow_up = quick_col_c.checkbox(
            "Keep follow-up",
            value=bool(selected.get("follow_up_date")),
            key=f"quick_{selected_id}_keep_follow_up",
        )
        quick_follow_up = quick_col_c.date_input(
            "Follow-up date",
            value=_text_to_date(selected.get("follow_up_date")) or date.today(),
            disabled=not quick_keep_follow_up,
            key=f"quick_{selected_id}_follow_up",
        )
        quick_notes = st.text_area("Notes", value=selected.get("notes", ""), key=f"quick_{selected_id}_notes")

        if st.form_submit_button("Save quick update"):
            update_application(
                selected_id,
                {
                    **selected,
                    "status": quick_status,
                    "next_action": quick_next_action,
                    "follow_up_date": quick_follow_up.isoformat() if quick_keep_follow_up else "",
                    "notes": quick_notes,
                },
                source="manual_quick_update",
            )
            st.success("Quick update saved.")
            st.rerun()

    quick_button_cols = st.columns(4)
    if quick_button_cols[0].button("Mark as Rejected", key=f"quick_mark_rejected_{selected_id}"):
        _quick_set_status(selected_id, selected, "Rejected")
        st.rerun()
    if quick_button_cols[1].button("Mark as Waiting", key=f"quick_mark_waiting_{selected_id}"):
        _quick_set_status(selected_id, selected, "Waiting")
        st.rerun()
    if quick_button_cols[2].button("Mark as Action Needed", key=f"quick_mark_action_needed_{selected_id}"):
        _quick_set_status(selected_id, selected, "Action Needed")
        st.rerun()
    if quick_button_cols[3].button("Clear Follow-up", key=f"quick_clear_follow_up_{selected_id}"):
        update_application(selected_id, {**selected, "follow_up_date": ""}, source="manual_clear_follow_up")
        st.rerun()

    st.markdown("**Detailed edit**")
    with st.form("edit_application_form"):
        col_a, col_b, col_c = st.columns(3)
        company = col_a.text_input("Company", value=selected["company"], key=f"{key_prefix}_company")
        role = col_b.text_input("Role", value=selected["role"], key=f"{key_prefix}_role")
        location = col_c.text_input("Location", value=selected.get("location", ""), key=f"{key_prefix}_location")

        col_d, col_e, col_f = st.columns(3)
        application_date = col_d.date_input(
            "Application date",
            value=_text_to_date(selected.get("application_date")) or date.today(),
            key=f"{key_prefix}_application_date",
        )
        status_index = STATUS_OPTIONS.index(selected["status"]) if selected["status"] in STATUS_OPTIONS else 1
        status = col_e.selectbox("Status", STATUS_OPTIONS, index=status_index, key=f"{key_prefix}_status")
        follow_up_value = col_f.date_input(
            "Follow-up date",
            value=_text_to_date(selected.get("follow_up_date")) or date.today() + timedelta(days=7),
            key=f"{key_prefix}_follow_up_date",
        )
        keep_follow_up = col_f.checkbox(
            "Keep follow-up date",
            value=bool(selected.get("follow_up_date")),
            key=f"{key_prefix}_keep_follow_up",
        )

        source_link = st.text_input("Source link", value=selected.get("source_link", ""), key=f"{key_prefix}_source")
        contact = st.text_input("Contact", value=selected.get("contact", ""), key=f"{key_prefix}_contact")
        next_action = st.text_input(
            "Next action",
            value=selected.get("next_action", ""),
            key=f"{key_prefix}_next_action",
        )
        rejection_reason = st.text_area(
            "Rejection reason",
            value=selected.get("rejection_reason", ""),
            placeholder="Optional. Add context such as no interview, after HR screen, position closed, or mismatch.",
            key=f"{key_prefix}_rejection_reason",
        )
        notes = st.text_area("Notes", value=selected.get("notes", ""), key=f"{key_prefix}_notes")

        col_save, col_delete = st.columns(2)
        save_clicked = col_save.form_submit_button("Save changes")
        delete_clicked = col_delete.form_submit_button("Delete application")

        if save_clicked:
            update_application(
                selected_id,
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
                    "follow_up_date": follow_up_value.isoformat() if keep_follow_up else "",
                },
                source="manual",
            )
            st.success("Application updated.")
            st.rerun()

        if delete_clicked:
            delete_application(selected_id, source="manual")
            st.warning("Application deleted.")
            st.rerun()

    st.subheader("Activity Log")
    render_activity_log(selected_id)


def _render_company_explorer(applications: list[dict]) -> None:
    stored_message = st.session_state.pop("company_watch_success_message", None)
    if stored_message:
        st.success(stored_message)

    with st.expander("Company Explorer / company watch"):
        st.caption(
            "Search a company or role, review previous applications, and record career-page checks "
            "when there are no suitable openings yet."
        )
        query = st.text_input("Search company or position", key="company_explorer_query")
        matching_applications = _matching_company_applications(applications, query)
        company_options = _company_input_options(matching_applications or applications, query)
        selected_company = st.selectbox(
            "Company to inspect",
            company_options,
            index=_option_index(company_options, query),
            accept_new_options=True,
            key="company_explorer_selected_company",
        )
        selected_company_text = str(selected_company or "").strip()
        related_applications = (
            _matching_company_applications(applications, selected_company_text, company_only=True)
            if selected_company_text
            else matching_applications[:10]
        )

        if related_applications:
            summary_cols = st.columns(4)
            summary_cols[0].metric("Applications", len(related_applications))
            summary_cols[1].metric(
                "Active",
                sum(1 for item in related_applications if item.get("status") != "Rejected"),
            )
            summary_cols[2].metric(
                "Rejected",
                sum(1 for item in related_applications if item.get("status") == "Rejected"),
            )
            summary_cols[3].metric(
                "Latest date",
                max(str(item.get("application_date", "") or "-") for item in related_applications),
            )
            company_df = with_display_sequence(pd.DataFrame(related_applications))
            st.dataframe(
                company_df[
                    [
                        "#",
                        "company",
                        "role",
                        "location",
                        "application_date",
                        "status",
                        "next_action",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No matching applications yet. You can still record a company check below.")

        research_query = selected_company_text or query
        research_notes = get_company_research_notes(research_query, limit=20) if research_query else []
        if research_notes:
            st.markdown("**Company check history**")
            st.dataframe(
                pd.DataFrame(research_notes)[
                    [
                        "checked_at",
                        "company",
                        "decision",
                        "relevant_roles",
                        "skipped_roles",
                        "notes",
                        "source_link",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )

        st.markdown("**Record company check**")
        with st.form("company_research_note_form", clear_on_submit=True):
            form_col_a, form_col_b, form_col_c = st.columns([1.4, 1, 1.2])
            company = form_col_a.selectbox(
                "Company",
                _company_input_options(applications, selected_company_text or query),
                index=0,
                accept_new_options=True,
                key="company_research_company",
            )
            checked_at = form_col_b.date_input("Checked date", value=date.today())
            decision = form_col_c.selectbox(
                "Decision",
                [
                    "No suitable role today",
                    "Potential roles found",
                    "Applied",
                    "Follow up later",
                    "Other",
                ],
            )
            relevant_roles = st.text_area(
                "Potential roles found",
                placeholder="Optional. Paste roles that may be relevant later.",
            )
            skipped_roles = st.text_area(
                "Skipped / not suitable roles",
                placeholder="Paste roles you checked but decided not to apply for, plus short reasons.",
            )
            source_link = st.text_input("Career page / source link")
            notes = st.text_area("Notes", placeholder="Example: no Junior IT Support / QA role today.")

            if st.form_submit_button("Save company check"):
                if not str(company or "").strip():
                    st.error("Company is required before saving a company check.")
                    return
                create_company_research_note(
                    {
                        "company": company,
                        "checked_at": checked_at.isoformat(),
                        "decision": decision,
                        "relevant_roles": relevant_roles,
                        "skipped_roles": skipped_roles,
                        "summary": _company_research_summary(decision, relevant_roles, skipped_roles),
                        "notes": notes,
                        "source_link": source_link,
                    }
                )
                st.session_state["company_watch_success_message"] = f"Saved company check for {company}."
                st.rerun()


def _render_pending_duplicate_resolution(applications: list[dict]) -> None:
    payload = st.session_state.get("pending_duplicate_payload")
    candidate_ids = st.session_state.get("pending_duplicate_candidate_ids", [])
    if not isinstance(payload, dict) or not candidate_ids:
        return

    applications_by_id = {int(application["id"]): application for application in applications}
    candidates = [
        applications_by_id[application_id] for application_id in candidate_ids if application_id in applications_by_id
    ]
    if not candidates:
        st.session_state.pop("pending_duplicate_payload", None)
        st.session_state.pop("pending_duplicate_candidate_ids", None)
        return

    st.warning("Possible duplicate application detected.")
    st.caption("No record will be deleted. You can update an existing record or create the new record anyway.")
    for candidate in candidates:
        candidate_match = find_likely_duplicate_applications(payload, [candidate])
        match_label = (
            format_duplicate_candidate(candidate_match[0])
            if candidate_match
            else (f"{candidate.get('company', '')} / {candidate.get('role', '')}")
        )
        st.write(f"Suggested existing record: {match_label}")
        update_col, create_col, cancel_col = st.columns([1.2, 1.2, 3])
        if update_col.button(f"Update #{candidate['id']}", key=f"duplicate_update_{candidate['id']}"):
            update_application(
                int(candidate["id"]),
                _merge_application_payload_for_update(candidate, payload),
                source="manual_duplicate_resolution",
            )
            st.session_state.pop("pending_duplicate_payload", None)
            st.session_state.pop("pending_duplicate_candidate_ids", None)
            st.session_state.pop("add_application_prefill", None)
            st.success("Existing application updated instead of creating a duplicate.")
            st.rerun()
        if create_col.button("Create new anyway", key=f"duplicate_create_anyway_{candidate['id']}"):
            create_application(payload, source="manual_duplicate_override")
            st.session_state.pop("pending_duplicate_payload", None)
            st.session_state.pop("pending_duplicate_candidate_ids", None)
            st.session_state.pop("add_application_prefill", None)
            st.success("New application created after duplicate review.")
            st.rerun()
        if cancel_col.button("Cancel duplicate review", key=f"duplicate_cancel_{candidate['id']}"):
            st.session_state.pop("pending_duplicate_payload", None)
            st.session_state.pop("pending_duplicate_candidate_ids", None)
            st.rerun()


def _merge_application_payload_for_update(existing: dict, incoming: dict) -> dict:
    merged = dict(existing)
    for column in [
        "company",
        "role",
        "location",
        "application_date",
        "status",
        "source_link",
        "contact",
        "rejection_reason",
        "next_action",
        "follow_up_date",
    ]:
        incoming_value = str(incoming.get(column, "") or "").strip()
        if incoming_value:
            merged[column] = incoming_value
    merged["notes"] = _join_notes(existing.get("notes", ""), incoming.get("notes", ""))
    return merged


def _join_notes(existing_notes: object, incoming_notes: object) -> str:
    notes: list[str] = []
    for value in [existing_notes, incoming_notes]:
        for part in str(value or "").split(" | "):
            cleaned = part.strip()
            if cleaned and cleaned not in notes:
                notes.append(cleaned)
    return " | ".join(notes)


def _find_existing_duplicate_pairs(applications: list[dict]) -> list[dict]:
    pairs: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for application in applications:
        application_id = int(application["id"])
        candidates = find_likely_duplicate_applications(
            application,
            [item for item in applications if int(item["id"]) != application_id],
            limit=3,
        )
        for candidate in candidates:
            other = candidate["application"]
            other_id = int(other["id"])
            pair_key = tuple(sorted((application_id, other_id)))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            pairs.append(
                {
                    "Record A": f"#{application_id} {application.get('company', '')} / {application.get('role', '')}",
                    "Record B": f"#{other_id} {other.get('company', '')} / {other.get('role', '')}",
                    "Similarity": f"{float(candidate['score']):.0%}",
                    "Reason": candidate["reason"],
                }
            )
    return pairs[:20]


def _render_duplicate_review_pairs() -> None:
    pairs = st.session_state.get("duplicate_review_pairs")
    if pairs is None:
        return
    if not pairs:
        st.info("No likely duplicate records found.")
        return
    st.warning("Likely duplicates found. Review and update the correct record manually; nothing was deleted.")
    st.dataframe(pd.DataFrame(pairs), use_container_width=True, hide_index=True)


def _render_application_note_intake(applications: list[dict] | None = None) -> None:
    stored_message = st.session_state.pop("application_note_prefill_message", None)
    if stored_message:
        st.success(stored_message)

    should_expand = bool(
        stored_message
        or st.session_state.get("add_application_prefill")
        or st.session_state.get("pending_duplicate_payload")
    )
    with st.expander("ChatGPT Import / auto-add application", expanded=should_expand):
        st.caption(
            "Paste JSON, a Markdown code block, or a short labeled note from ChatGPT. "
            "Import directly when company and role are clear, or extract into the form when you want to review first."
        )
        note_text = st.text_area(
            "ChatGPT application record",
            key="structured_application_note_text",
            height=180,
            placeholder=(
                "{\n"
                '  "company": "EY",\n'
                '  "role": "SAP Innovation Engineer (w/m/d)",\n'
                '  "location": "Berlin, Germany",\n'
                '  "status": "Applied",\n'
                '  "application_date": "2026-05-17",\n'
                '  "cv_version": "EY SAP Innovation Engineer 2-page German CV",\n'
                '  "next_action": "Wait for confirmation email; follow up after 5-7 working days."\n'
                "}"
            ),
        )
        import_col, extract_col, clear_col = st.columns([1.2, 1.1, 3])
        if import_col.button("Import and add directly", key="import_structured_application_note", type="primary"):
            _import_application_note_directly(note_text, applications or [])
        if extract_col.button("Extract into form", key="extract_structured_application_note"):
            parsed = parse_application_note(note_text)
            if not parsed["fields"]:
                st.warning("No structured fields found. Use lines like `Company: SAP` or `Position: QA Engineer`.")
            else:
                st.session_state["add_application_prefill"] = parsed
                st.session_state["application_note_prefill_message"] = (
                    f"Extracted {len(parsed['fields'])} field(s). Review the Add Application form before saving."
                )
                st.rerun()
        if clear_col.button("Clear extracted prefill", key="clear_structured_application_prefill"):
            st.session_state.pop("add_application_prefill", None)
            st.session_state.pop("application_note_prefill_message", None)
            st.rerun()

        current_prefill = st.session_state.get("add_application_prefill")
        if isinstance(current_prefill, dict) and current_prefill.get("fields"):
            st.caption(current_prefill.get("summary", "Extracted fields are ready for review."))
            preview_rows = [
                {"Field": field.replace("_", " "), "Value": value}
                for field, value in current_prefill["fields"].items()
                if value
            ]
            st.dataframe(preview_rows, use_container_width=True, hide_index=True)


def _import_application_note_directly(note_text: str, applications: list[dict]) -> None:
    parsed = parse_application_note(note_text)
    if not parsed["fields"]:
        st.warning("No structured fields found. Use lines like `Company: SAP` or `Position: QA Engineer`.")
        return

    payload = build_application_payload(parsed)
    if not payload["company"] or not payload["role"]:
        st.session_state["add_application_prefill"] = parsed
        st.warning("Company and role are required. Extracted fields were saved for manual review.")
        return

    duplicate_candidates = find_likely_duplicate_applications(payload, applications)
    if duplicate_candidates:
        st.session_state["pending_duplicate_payload"] = payload
        st.session_state["pending_duplicate_candidate_ids"] = [
            int(candidate["application"]["id"]) for candidate in duplicate_candidates
        ]
        st.session_state["add_application_prefill"] = parsed
        st.warning("Likely duplicate found. Review the suggested existing record before creating a new one.")
        st.rerun()

    application_id = create_application(payload, source="chatgpt_import")
    st.session_state.pop("add_application_prefill", None)
    st.session_state.pop("pending_duplicate_payload", None)
    st.session_state.pop("pending_duplicate_candidate_ids", None)
    st.session_state["application_note_prefill_message"] = (
        f"Imported application #{application_id}: {payload['company']} / {payload['role']}."
    )
    st.rerun()


def render_activity_log(application_id: int) -> None:
    events = get_application_events(application_id)
    if not events:
        st.info("No activity recorded for this application yet.")
        return

    event_df = pd.DataFrame(events)
    event_df = event_df[
        [
            "created_at",
            "event_type",
            "source",
            "old_value",
            "new_value",
        ]
    ]
    st.dataframe(event_df, use_container_width=True, hide_index=True)


def _company_input_options(applications: list[dict], preferred: object = "") -> list[str]:
    options: list[str] = []
    preferred_text = str(preferred or "").strip()
    if preferred_text:
        options.append(preferred_text)
    else:
        options.append("")

    for application in applications:
        company = str(application.get("company", "") or "").strip()
        if company and company not in options:
            options.append(company)
    return options


def _matching_company_applications(
    applications: list[dict],
    query: object,
    company_only: bool = False,
) -> list[dict]:
    query_text = str(query or "").casefold().strip()
    if not query_text:
        return applications[:10]

    matched: list[dict] = []
    for application in applications:
        company = str(application.get("company", "") or "")
        role = str(application.get("role", "") or "")
        notes = str(application.get("notes", "") or "")
        source = str(application.get("source_link", "") or "")
        haystack = company if company_only else " ".join([company, role, notes, source])
        if query_text in haystack.casefold():
            matched.append(application)
    return matched


def _company_research_summary(decision: str, relevant_roles: str, skipped_roles: str) -> str:
    relevant_count = _non_empty_line_count(relevant_roles)
    skipped_count = _non_empty_line_count(skipped_roles)
    parts = [decision]
    if relevant_count:
        parts.append(f"{relevant_count} possible role(s)")
    if skipped_count:
        parts.append(f"{skipped_count} skipped role(s)")
    return " | ".join(parts)


def _non_empty_line_count(value: str) -> int:
    return sum(1 for line in str(value or "").splitlines() if line.strip())


def _application_label_id_map(applications: list[dict]) -> dict[str, int]:
    display_df = with_display_sequence(pd.DataFrame(applications))
    labels: dict[str, int] = {}
    for row in display_df.to_dict(orient="records"):
        label = f"{row['#']} - {row['company']} - {row['role']}"
        labels[label] = int(row["id"])
    return labels


def _application_label_for_id(label_id_map: dict[str, int], application_id: int) -> str:
    return next((label for label, mapped_id in label_id_map.items() if mapped_id == application_id), "")


def _date_range_bounds(value: object) -> tuple[date | None, date | None]:
    if isinstance(value, tuple | list):
        dates = [item for item in value if isinstance(item, date)]
        if len(dates) >= 2:
            return dates[0], dates[1]
        if len(dates) == 1:
            return dates[0], None
    if isinstance(value, date):
        return value, value
    return None, None


def _filter_calendar_items(
    calendar_items: list,
    *,
    selected_event_types: list[str],
    start_date: date | None,
    end_date: date | None,
) -> list:
    event_type_filter = set(selected_event_types)
    filtered = []
    for item in calendar_items:
        if event_type_filter and item.event_type not in event_type_filter:
            continue
        if start_date and item.event_date < start_date:
            continue
        if end_date and item.event_date > end_date:
            continue
        filtered.append(item)
    return filtered


def _selected_application_ids_from_editor(display_df: pd.DataFrame, edited_df: pd.DataFrame) -> list[int]:
    rows_by_sequence = {int(row["#"]): row for row in display_df.to_dict(orient="records")}
    selected_ids: list[int] = []
    for row in edited_df.to_dict(orient="records"):
        if not bool(row.get("select")):
            continue
        sequence_number = int(row["#"])
        selected_ids.append(int(rows_by_sequence[sequence_number]["id"]))
    return selected_ids


def _apply_bulk_application_action(
    selected_ids: list[int],
    applications: list[dict],
    action: str,
    *,
    follow_up_date: date | None = None,
) -> int:
    applications_by_id = {int(application["id"]): application for application in applications}
    changed = 0
    for application_id in selected_ids:
        application = applications_by_id.get(application_id)
        if not application:
            continue
        update_application(
            application_id,
            build_bulk_update_payload(application, action, follow_up_date=follow_up_date),
            source=f"bulk_{action}",
        )
        changed += 1
    return changed


def _quick_set_status(application_id: int, application: dict, status: str) -> None:
    payload = {
        **application,
        "status": status,
        "next_action": DEFAULT_NEXT_ACTION_BY_STATUS.get(status, application.get("next_action", "")),
    }
    if status == "Action Needed":
        payload["follow_up_date"] = date.today().isoformat()
    if status in {"Rejected", "Waiting"}:
        payload["follow_up_date"] = ""
    update_application(application_id, payload, source="manual_quick_status")


def _option_index(options: list[str], value: str) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


def _save_dashboard_editor_changes(
    applications: list[dict],
    original_df: pd.DataFrame,
    edited_df: pd.DataFrame,
) -> int:
    original_rows = {int(row["#"]): row for row in original_df.to_dict(orient="records")}
    applications_by_id = {int(item["id"]): item for item in applications}
    changed_count = 0

    for row in edited_df.to_dict(orient="records"):
        original = original_rows[int(row["#"])]
        application_id = int(original["id"])
        updates = {
            column: _editor_value_to_text(row.get(column, ""))
            for column in DASHBOARD_EDITABLE_COLUMNS
            if _editor_value_to_text(row.get(column, "")) != _editor_value_to_text(original.get(column, ""))
        }
        if not updates:
            continue

        update_application(
            application_id,
            {**applications_by_id[application_id], **updates},
            source="dashboard_inline_edit",
        )
        changed_count += 1

    return changed_count


def _editor_value_to_text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass
    return str(value).strip()


def _with_rate_percent(df: pd.DataFrame, rate_column: str) -> pd.DataFrame:
    if df.empty:
        return df
    formatted = df.copy()
    formatted[f"{rate_column}_percent"] = (formatted[rate_column] * 100).round(1)
    formatted[f"{rate_column}_label"] = formatted[f"{rate_column}_percent"].map(_format_percent_label)
    return formatted


def _style_bar_labels(fig: object, texttemplate: str = "%{text}", position: str = "outside") -> None:
    fig.update_traces(texttemplate=texttemplate, textposition=position, cliponaxis=False)
    fig.update_layout(uniformtext_minsize=10, uniformtext_mode="show")


def _format_percent_label(value: object) -> str:
    return f"{float(value):.0f}%"


def _format_rate(value: object) -> str:
    return f"{float(value) * 100:.0f}%"


def _date_to_text(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    return str(value) if value else ""


def _text_to_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


if __name__ == "__main__":
    main()
