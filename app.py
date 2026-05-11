from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from src.action_recommender import build_next_action_recommendation, build_workflow_decision
from src.analytics import (
    build_applications_per_month,
    build_average_waiting_days_by_company,
    build_interview_conversion_by_role_type,
    build_pipeline_health,
    build_response_rate_by_source,
    build_saved_vs_applied_summary,
    build_stale_pipeline_breakdown,
)
from src.csv_importer import normalize_import_rows
from src.dashboard import build_summary
from src.database import (
    create_application,
    deduplicate_applications,
    delete_application,
    get_application_events,
    get_applications,
    init_db,
    sync_applications,
    update_application,
)
from src.demo_data import seed_sample_applications
from src.email_classifier import classify_email
from src.email_insights import (
    build_context_rows,
    build_email_analysis_summary,
    build_keyword_rows,
    build_match_candidate_rows,
    build_match_reason_rows,
    build_match_signal_rows,
    build_workflow_steps,
)
from src.email_parser import (
    extract_application_details,
    match_application_from_email,
    rank_application_matches_from_email,
)
from src.email_templates import TEMPLATE_TYPES, generate_email_template, suggest_template_type
from src.gmail_client import (
    DEFAULT_GMAIL_QUERY,
    GmailConfigurationError,
    GmailDependencyError,
    fetch_recruiting_emails,
)
from src.models import APPLICATION_COLUMNS, STATUS_OPTIONS
from src.reminder_engine import generate_reminders

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

WORKSPACE_OPTIONS = ["Overview", "Applications", "Email Assistant", "Data & Settings"]

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


def main() -> None:
    applications = get_applications()
    reminders = generate_reminders(applications)

    workspace = render_sidebar_navigation(applications, reminders)
    render_app_header(workspace)

    if workspace == "Overview":
        render_dashboard(applications, reminders)
    elif workspace == "Applications":
        render_applications(applications)
    elif workspace == "Email Assistant":
        render_assistant_workspace(applications)
    else:
        render_data_tools(applications)


def render_sidebar_navigation(applications: list[dict], reminders: list[dict]) -> str:
    with st.sidebar:
        st.title("CareerOps")
        st.caption("Job search operations tracker")
        if st.session_state.get("workspace_nav") == "Assistant":
            st.session_state["workspace_nav"] = "Email Assistant"
        workspace = st.radio(
            "Workspace",
            WORKSPACE_OPTIONS,
            key="workspace_nav",
            label_visibility="collapsed",
        )
        st.divider()
        st.metric("Applications", len(applications))
        st.metric("Pending actions", len(reminders))
        st.caption("Local data stays in SQLite. Gmail sync is optional and read-only.")
    return workspace


def render_app_header(workspace: str) -> None:
    st.title(workspace)
    st.caption("Job application tracking, email classification, and follow-up reminders.")


def render_assistant_workspace(applications: list[dict]) -> None:
    email_tab, templates_tab, gmail_tab = st.tabs(["Email Classification", "Templates", "Gmail Sync"])
    with email_tab:
        render_email_assistant(applications)
    with templates_tab:
        render_email_templates(applications)
    with gmail_tab:
        render_gmail_sync_tools(applications)


def render_dashboard(applications: list[dict], reminders: list[dict]) -> None:
    summary = build_summary(applications)
    pipeline_health = build_pipeline_health(applications)

    metric_columns = st.columns(6)
    metric_columns[0].metric("Total", summary["total"])
    metric_columns[1].metric("This week", summary["applied_this_week"])
    metric_columns[2].metric("Waiting", summary["waiting"])
    metric_columns[3].metric("Interviews", summary["interviews"])
    metric_columns[4].metric("Assessments", summary["assessments"])
    metric_columns[5].metric("Rejected", summary["rejections"])

    if not applications:
        st.info("Add your first application to start building the dashboard.")
        return

    df = pd.DataFrame(applications)

    recent_title_col, recent_action_col = st.columns([4, 1])
    recent_title_col.subheader("Recent Applications")
    recent_action_col.button(
        "Add application",
        key="dashboard_add_application",
        type="primary",
        use_container_width=True,
        on_click=_go_to_applications_workspace,
    )
    display_df = _with_display_sequence(df)
    render_dashboard_recent_editor(applications, display_df)
    st.divider()

    chart_col, reminder_col = st.columns([2, 1])

    with chart_col:
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

    with reminder_col:
        st.subheader("Pending Actions")
        if not reminders:
            st.success("No reminders due right now.")
        else:
            st.caption(f"{len(reminders)} pending action(s)")
            with st.container(height=520):
                for reminder in reminders:
                    st.markdown(
                        f"**{reminder['priority']}** - {reminder['company']} / "
                        f"{reminder['role']}  \n"
                        f"{reminder['message']}  \n"
                        f"Due: `{reminder['due_date']}`"
                    )
                    st.divider()

    st.subheader("Decision Analytics")
    health_columns = st.columns(4)
    health_columns[0].metric("Response rate", _format_rate(pipeline_health["response_rate"]))
    health_columns[1].metric("Interview conversion", _format_rate(pipeline_health["interview_conversion_rate"]))
    health_columns[2].metric("Avg active waiting", f"{pipeline_health['average_active_waiting_days']} days")
    health_columns[3].metric("Stale open", pipeline_health["stale_open_applications"])

    activity_col, source_col = st.columns(2)
    with activity_col:
        monthly_df = pd.DataFrame(build_applications_per_month(applications))
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
        source_df = _with_rate_percent(pd.DataFrame(build_response_rate_by_source(applications)), "response_rate")
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
            pd.DataFrame(build_interview_conversion_by_role_type(applications)),
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
        waiting_df = pd.DataFrame(build_average_waiting_days_by_company(applications))
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
        stale_df = pd.DataFrame(build_stale_pipeline_breakdown(applications))
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
        saved_df = pd.DataFrame(build_saved_vs_applied_summary(applications))
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


def _go_to_applications_workspace() -> None:
    st.session_state["workspace_nav"] = "Applications"


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
    with st.form("add_application_form", clear_on_submit=True):
        col_a, col_b, col_c = st.columns(3)
        company = col_a.text_input("Company")
        role = col_b.text_input("Role")
        location = col_c.text_input("Location", value="Germany")

        col_d, col_e, col_f = st.columns(3)
        application_date = col_d.date_input("Application date", value=date.today())
        status = col_e.selectbox("Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index("Applied"))
        has_follow_up = col_f.checkbox("Set follow-up date")
        follow_up_date = ""
        if has_follow_up:
            follow_up_date = col_f.date_input("Follow-up date", value=date.today() + timedelta(days=7))

        source_link = st.text_input("Source link")
        contact = st.text_input("Contact")
        next_action = st.text_input("Next action")
        rejection_reason = st.text_area(
            "Rejection reason",
            placeholder="Optional. Useful when status is Rejected, for example after HR screen or position closed.",
        )
        notes = st.text_area("Notes")

        submitted = st.form_submit_button("Add application")
        if submitted:
            if not company.strip() or not role.strip():
                st.error("Company and role are required.")
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
                        "follow_up_date": _date_to_text(follow_up_date),
                    },
                    source="manual",
                )
                st.success("Application added.")
                st.rerun()

    st.subheader("Manage Applications")
    if not applications:
        st.info("No applications yet.")
        return

    cleanup_col, helper_col = st.columns([1, 4])
    if cleanup_col.button("Clean duplicate applications", key="manage_clean_duplicates"):
        removed = deduplicate_applications()
        if removed:
            st.success(f"Removed {removed} duplicate records.")
        else:
            st.info("No duplicate records found.")
        st.rerun()
    helper_col.caption("Removes repeated rows with the same company, role, and application date.")

    df = _with_display_sequence(pd.DataFrame(applications))
    selected_statuses = st.multiselect("Filter by status", STATUS_OPTIONS, default=STATUS_OPTIONS)
    filtered = df[df["status"].isin(selected_statuses)]
    st.dataframe(
        filtered[
            [
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
        ],
        use_container_width=True,
        hide_index=True,
    )

    label_id_map = _application_label_id_map(applications)
    selected_label = st.selectbox("Select application to edit", list(label_id_map.keys()))
    selected_id = label_id_map[selected_label]
    selected = next(item for item in applications if item["id"] == selected_id)
    key_prefix = f"edit_{selected_id}"

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


def render_email_assistant(applications: list[dict]) -> None:
    st.subheader("Classify Recruiting Email")
    subject = st.text_input("Email subject")
    body = st.text_area("Email body", height=220)

    if st.button("Classify email"):
        st.session_state.pop("email_create_success_message", None)
        result = classify_email(subject=subject, body=body)
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
        st.session_state["last_classification"] = result
        st.session_state["last_email_details"] = details
        st.session_state["last_application_match"] = match
        st.session_state["last_application_matches"] = match_candidates

    result = st.session_state.get("last_classification")
    if not result:
        st.info("Paste an email and classify it to get a suggested status update.")
        return

    details = st.session_state.get("last_email_details", {})
    match = st.session_state.get("last_application_match")
    match_candidates = st.session_state.get("last_application_matches", [])
    create_recommendation = build_next_action_recommendation(result, details)

    render_email_analysis_report(
        result,
        details,
        match,
        match_candidates,
        create_recommendation,
        has_applications=bool(applications),
    )

    if applications:
        st.divider()
        st.subheader("Recommended Workflow")
        label_id_map = _application_label_id_map(applications)
        labels = list(label_id_map.keys())
        default_match = match or (match_candidates[0] if match_candidates else None)
        default_index = _matched_label_index(labels, label_id_map, default_match)
        selected_label = st.selectbox(
            "Update an existing application",
            labels,
            index=default_index,
            key="email_update_select",
        )
        if not match and match_candidates:
            st.caption("Default selection uses the highest-ranked candidate. Review it before applying changes.")
        selected_id = label_id_map[selected_label]
        selected = next(item for item in applications if item["id"] == selected_id)
        recommendation = build_next_action_recommendation(result, details, selected)
        workflow_decision = build_workflow_decision(
            result,
            details,
            recommendation,
            application=selected,
            auto_match=match,
            match_candidates=match_candidates,
        )

        decision_cols = st.columns(5)
        decision_cols[0].metric("Decision", workflow_decision["operation"])
        decision_cols[1].metric("Review level", workflow_decision["review_level"])
        decision_cols[2].metric("Priority", recommendation["priority"])
        decision_cols[3].metric("Follow-up", recommendation["follow_up_date"] or "-")
        decision_cols[4].metric("Target", f"{selected.get('company', '')}")
        st.info(workflow_decision["decision"])
        st.write("Record action:", workflow_decision["record_action"])
        st.write("Status action:", workflow_decision["status_action"])
        st.caption("Why: " + workflow_decision["rationale"])
        st.dataframe(
            pd.DataFrame(
                build_workflow_steps(
                    result,
                    recommendation,
                    has_match=bool(match),
                    workflow_decision=workflow_decision,
                )
            ),
            use_container_width=True,
            hide_index=True,
        )

        next_action_col, status_col = st.columns(2)
        if next_action_col.button(workflow_decision["secondary_action_label"], type="primary"):
            _update_application_from_email_action(
                selected_id,
                selected,
                result,
                details,
                recommendation,
                apply_status=False,
            )
            st.success("Next action applied to the selected application.")
            st.rerun()

        if status_col.button(workflow_decision["primary_action_label"]):
            _update_application_from_email_action(
                selected_id,
                selected,
                result,
                details,
                recommendation,
                apply_status=True,
            )
            st.success("Application updated from email classification.")
            st.rerun()

    st.divider()
    st.subheader("Create Application from Email")
    success_message = st.session_state.get("email_create_success_message")
    if success_message:
        st.success(success_message)
    with st.form("create_from_email_form", clear_on_submit=True):
        col_company, col_role, col_location = st.columns(3)
        company = col_company.text_input("Company", value=details.get("company", ""), key="email_create_company")
        role = col_role.text_input("Role", value=details.get("role", ""), key="email_create_role")
        location = col_location.text_input("Location", value=details.get("location", ""), key="email_create_location")

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
            value=_append_note(_build_email_note(result, details), _build_next_action_note(create_recommendation)),
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

    st.subheader("Email Analysis")
    with st.container(border=True):
        summary_cols = st.columns(4)
        summary_cols[0].metric("Email type", result["category"])
        summary_cols[1].metric("Confidence", summary["confidence_label"], f"{classification_confidence:.0%}")
        summary_cols[2].metric("Suggested status", result["suggested_status"])
        summary_cols[3].metric("Context fields", summary["detected_context"])
        st.caption(summary["confidence_description"])
        st.info(summary["decision"])

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

    st.markdown("**Application Match**")
    visible_match = match or (match_candidates[0] if match_candidates else None)
    if match_candidates:
        if match:
            st.success(f"Best match: {match['company']} / {match['role']}")
        else:
            st.warning("No auto-selected confident match. Review the ranked candidates before applying changes.")
        st.markdown("**Top 3 Existing Application Matches**")
        st.caption(f"Showing {len(match_candidates)} candidate(s), ranked by score and confidence.")
        st.dataframe(
            pd.DataFrame(build_match_candidate_rows(match_candidates, selected_match=match)),
            use_container_width=True,
            hide_index=True,
            height=170,
        )

    if visible_match:
        match_confidence = float(visible_match.get("confidence") or 0)
        match_cols = st.columns(4)
        match_cols[0].metric("Match status", summary["match_label"])
        match_cols[1].metric("Match confidence", f"{match_confidence:.0%}")
        match_cols[2].metric("Match score", visible_match["score"])
        match_cols[3].metric("Workflow priority", recommendation["priority"])

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
    elif has_applications:
        st.warning("No confident application match found. Select one manually below or create a new record.")
    else:
        st.info("No existing applications are available yet. Use the extracted context to create a new record.")


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

    col_type, col_recipient, col_sender = st.columns(3)
    template_type = col_type.selectbox(
        "Template type",
        TEMPLATE_TYPES,
        index=suggested_index,
        key=f"template_type_{selected_id}",
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
    )

    st.text_input("Subject", value=generated["subject"], key=f"template_subject_{selected_id}_{template_type}")
    st.text_area(
        "Email body",
        value=generated["body"],
        height=320,
        key=f"template_body_{selected_id}_{template_type}",
    )


def render_data_tools(applications: list[dict]) -> None:
    st.subheader("Sample Data")

    if st.button("Load sample applications"):
        created = seed_sample_applications()
        if created:
            st.success(f"Loaded {created} sample applications.")
        else:
            st.info("Sample applications are already loaded.")
        st.rerun()

    st.subheader("CSV Import")
    uploaded_file = st.file_uploader("Import applications from CSV", type=["csv"])
    if uploaded_file is not None:
        uploaded_df = pd.read_csv(uploaded_file, dtype=str).fillna("")
        import_result = normalize_import_rows(uploaded_df.to_dict(orient="records"))

        if not import_result.rows:
            st.error("No valid application rows found in this CSV.")
            st.caption("Detected columns: " + ", ".join(import_result.source_columns))
        else:
            st.success(f"Detected {len(import_result.rows)} application rows ready to import.")
            if import_result.skipped_count:
                st.caption(f"Skipped {import_result.skipped_count} blank, duplicate, or header-like rows.")

            preview_df = pd.DataFrame(import_result.rows)
            st.dataframe(
                preview_df[["company", "role", "application_date", "status", "next_action"]].head(10),
                use_container_width=True,
                hide_index=True,
            )

        if import_result.rows and st.button("Import CSV"):
            result = sync_applications(import_result.rows, source="csv_import")
            st.success(
                f"Import complete: {result['created']} created, "
                f"{result['updated']} updated, {result['skipped']} unchanged."
            )
            st.rerun()

    st.subheader("Export")
    if applications:
        export_df = _with_display_sequence(pd.DataFrame(applications))
        export_columns = ["#"] + APPLICATION_COLUMNS + ["created_at", "updated_at"]
        st.download_button(
            "Download applications CSV",
            export_df[export_columns].to_csv(index=False).encode("utf-8"),
            file_name="careerops_applications.csv",
            mime="text/csv",
        )
    else:
        st.info("Add or import applications before exporting CSV data.")

    with st.expander("CSV format"):
        st.code(", ".join(APPLICATION_COLUMNS), language="text")
        st.caption(
            "English and common Chinese headers are supported, "
            "for example 公司名称, 职位名称, 申请日期, 最新状态, 备注/来源."
        )

    if applications:
        with st.expander("Maintenance"):
            st.caption("Use this after repeated CSV imports to remove duplicate company/role/date records.")
            if st.button("Clean duplicate applications", key="data_clean_duplicates"):
                removed = deduplicate_applications()
                if removed:
                    st.success(f"Removed {removed} duplicate records.")
                else:
                    st.info("No duplicate records found.")
                st.rerun()


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
            st.session_state["gmail_sync_preview"] = _build_gmail_sync_preview(emails, applications)
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


def _application_label_id_map(applications: list[dict]) -> dict[str, int]:
    display_df = _with_display_sequence(pd.DataFrame(applications))
    labels: dict[str, int] = {}
    for row in display_df.to_dict(orient="records"):
        label = f"{row['#']} - {row['company']} - {row['role']}"
        labels[label] = int(row["id"])
    return labels


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


def _update_application_from_email_action(
    selected_id: int,
    selected: dict,
    result: dict,
    details: dict[str, str],
    recommendation: dict[str, str],
    apply_status: bool,
) -> None:
    follow_up_date = recommendation["follow_up_date"] or selected.get("follow_up_date", "")
    notes = _append_note(selected.get("notes", ""), _build_email_note(result, details))
    notes = _append_note(notes, _build_next_action_note(recommendation))

    rejection_reason = selected.get("rejection_reason", "")
    if result["suggested_status"] == "Rejected" and not rejection_reason:
        rejection_reason = details.get("rejection_reason") or "Rejected based on classified recruiting email."

    update_application(
        selected_id,
        {
            **selected,
            "status": result["suggested_status"] if apply_status else selected.get("status", "Applied"),
            "location": selected.get("location", "") or details.get("location", ""),
            "contact": selected.get("contact", "") or details.get("contact", ""),
            "source_link": selected.get("source_link", "") or details.get("source_link", ""),
            "next_action": recommendation["next_action"],
            "follow_up_date": follow_up_date,
            "notes": notes,
            "rejection_reason": rejection_reason,
        },
        source="email_assistant" if apply_status else "email_next_action",
    )


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


def _build_email_note(result: dict, details: dict[str, str]) -> str:
    note_parts = [f"Email classified as {result['category']} with {result['confidence']:.0%} confidence."]
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


def _build_gmail_sync_preview(emails: list[dict[str, str]], applications: list[dict]) -> list[dict]:
    previews: list[dict] = []
    for index, email in enumerate(emails, start=1):
        subject = email.get("subject", "")
        body = email.get("body", "")
        result = classify_email(subject=subject, body=body)
        details = extract_application_details(subject=subject, body=body)
        match = match_application_from_email(
            applications,
            subject=subject,
            body=body,
            extracted_details=details,
        )
        previews.append(
            {
                "index": index,
                "apply": False,
                "gmail_id": email.get("gmail_id", ""),
                "subject": subject,
                "sender": email.get("sender", ""),
                "date": email.get("date", ""),
                "body": body,
                "category": result["category"],
                "confidence": result["confidence"],
                "suggested_status": result["suggested_status"],
                "suggested_next_action": result["suggested_next_action"],
                "suggested_follow_up_days": result["suggested_follow_up_days"],
                "matched_keywords": result["matched_keywords"],
                "company": details.get("company", ""),
                "role": details.get("role", ""),
                "location": details.get("location", ""),
                "contact": details.get("contact", ""),
                "source_link": details.get("source_link", ""),
                "suggested_follow_up_date": details.get("suggested_follow_up_date", ""),
                "rejection_reason": details.get("rejection_reason", ""),
                "matched_application_id": int(match["application_id"]) if match else 0,
                "matched_application": f"{match['company']} / {match['role']}" if match else "",
                "details": details,
                "classification": result,
            }
        )
    return previews


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
        action = _apply_gmail_preview(preview, applications)
        result[action] += 1
    return result


def _apply_gmail_preview(preview: dict, applications: list[dict]) -> str:
    if preview["matched_application_id"]:
        selected = next(item for item in applications if int(item["id"]) == int(preview["matched_application_id"]))
        recommendation = build_next_action_recommendation(preview["classification"], preview["details"], selected)
        follow_up_date = recommendation["follow_up_date"] or selected.get("follow_up_date", "")

        rejection_reason = selected.get("rejection_reason", "")
        if preview["suggested_status"] == "Rejected" and not rejection_reason:
            rejection_reason = preview.get("rejection_reason") or "Rejected based on Gmail recruiting email."

        update_application(
            int(selected["id"]),
            {
                **selected,
                "status": preview["suggested_status"],
                "location": selected.get("location", "") or preview.get("location", ""),
                "contact": selected.get("contact", "") or preview.get("contact", ""),
                "source_link": selected.get("source_link", "") or preview.get("source_link", ""),
                "next_action": recommendation["next_action"],
                "follow_up_date": follow_up_date,
                "notes": _append_note(
                    _append_note(selected.get("notes", ""), _build_gmail_note(preview)),
                    _build_next_action_note(recommendation),
                ),
                "rejection_reason": rejection_reason,
            },
            source="gmail_sync",
        )
        return "updated"

    if not preview.get("company") or not preview.get("role"):
        return "skipped"

    recommendation = build_next_action_recommendation(preview["classification"], preview["details"])
    create_application(
        {
            "company": preview["company"],
            "role": preview["role"],
            "location": preview.get("location", ""),
            "application_date": date.today().isoformat(),
            "status": preview["suggested_status"],
            "source_link": preview.get("source_link", ""),
            "contact": preview.get("contact", ""),
            "notes": _append_note(_build_gmail_note(preview), _build_next_action_note(recommendation)),
            "rejection_reason": (preview.get("rejection_reason") or "Rejected based on Gmail recruiting email.")
            if preview["suggested_status"] == "Rejected"
            else "",
            "next_action": recommendation["next_action"],
            "follow_up_date": recommendation["follow_up_date"],
        },
        source="gmail_sync",
    )
    return "created"


def _build_gmail_note(preview: dict) -> str:
    note = _build_email_note(preview["classification"], preview["details"])
    subject = str(preview.get("subject", "")).strip()
    sender = str(preview.get("sender", "")).strip()
    metadata = " | ".join(value for value in [f"Gmail subject: {subject}" if subject else "", sender] if value)
    return _append_note(note, metadata) if metadata else note


def _append_note(existing_notes: str, new_note: str) -> str:
    if not existing_notes:
        return new_note
    if new_note in existing_notes:
        return existing_notes
    return f"{existing_notes}\n{new_note}"


def _recipient_name_from_contact(contact: object) -> str:
    text = str(contact or "").strip()
    if not text:
        return ""
    if "<" in text:
        return text.split("<", 1)[0].strip()
    if "@" in text:
        return ""
    return text


def _with_display_sequence(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    sorted_df = df.sort_values(
        by=["application_date", "company", "role", "id"],
        ascending=[False, True, True, False],
        na_position="last",
    ).reset_index(drop=True)
    sorted_df.insert(0, "#", range(1, len(sorted_df) + 1))
    return sorted_df


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
