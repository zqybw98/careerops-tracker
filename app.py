from __future__ import annotations

from datetime import date, timedelta

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
from src.calendar_export import (
    build_calendar_items,
    build_calendar_text_block,
    build_ics_calendar,
    calendar_items_to_rows,
)
from src.contacts import build_contact_records
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
from src.models import APPLICATION_COLUMNS, STATUS_OPTIONS
from src.reminder_engine import generate_reminders
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

WORKSPACE_OPTIONS = ["Overview", "Applications", "Contacts", "Email Assistant", "Data & Settings"]

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
    elif workspace == "Contacts":
        render_contacts(applications)
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
    events = get_application_events()

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

    response_time_col, rejection_reason_col = st.columns(2)
    with response_time_col:
        response_time_df = pd.DataFrame(build_time_to_first_response_by_source(applications, events))
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
        rejection_df = pd.DataFrame(build_rejection_reason_breakdown(applications))
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
            pd.DataFrame(build_interview_to_offer_funnel(applications, events)),
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
        follow_up_df = _with_rate_percent(pd.DataFrame(build_follow_up_effectiveness(applications, events)), "share")
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

    matrix_df = _with_rate_percent(pd.DataFrame(build_channel_role_type_matrix(applications)), "response_rate")
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


def _go_to_applications_workspace() -> None:
    st.session_state["workspace_nav"] = "Applications"


def render_contacts(applications: list[dict]) -> None:
    contacts = build_contact_records(applications, get_application_events())

    if not contacts:
        st.info("Add contacts, source links, or recruiter emails to applications to build the contact view.")
        return

    total_contacts = len(contacts)
    recruiter_contacts = sum(1 for contact in contacts if contact["contact_type"] == "Recruiter")
    follow_up_contacts = sum(1 for contact in contacts if contact["follow_up_status"] in {"Due", "Needed", "Planned"})
    represented_applications = sum(int(contact["applications"]) for contact in contacts)

    metric_columns = st.columns(4)
    metric_columns[0].metric("Contacts", total_contacts)
    metric_columns[1].metric("Recruiters", recruiter_contacts)
    metric_columns[2].metric("With follow-up", follow_up_contacts)
    metric_columns[3].metric("Linked applications", represented_applications)

    filter_col_a, filter_col_b, filter_col_c, filter_col_d = st.columns([1.4, 1, 1, 0.8])
    search_query = filter_col_a.text_input("Search contact/company/application", key="contact_search")
    type_options = sorted({str(contact["contact_type"]) for contact in contacts})
    channel_options = sorted({str(contact["channel"]) for contact in contacts})
    selected_types = filter_col_b.multiselect(
        "Contact type",
        type_options,
        default=type_options,
        key="contact_type_filter",
    )
    selected_channels = filter_col_c.multiselect(
        "Channel",
        channel_options,
        default=channel_options,
        key="contact_channel_filter",
    )
    follow_up_only = filter_col_d.checkbox("Follow-up only", key="contact_follow_up_filter")

    filtered_contacts = _filter_contact_records(
        contacts,
        search_query=search_query,
        selected_types=selected_types,
        selected_channels=selected_channels,
        follow_up_only=follow_up_only,
    )
    st.caption(f"Showing {len(filtered_contacts)} of {len(contacts)} contact(s).")

    if not filtered_contacts:
        st.info("No contacts match the current filters.")
        return

    contact_df = pd.DataFrame(filtered_contacts)
    st.dataframe(
        contact_df[
            [
                "contact",
                "contact_type",
                "channel",
                "companies",
                "applications",
                "open_applications",
                "follow_up_status",
                "next_follow_up_date",
                "last_contact_at",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    label_map = {
        f"{contact['contact']} - {contact['companies']} ({contact['applications']} application(s))": contact
        for contact in filtered_contacts
    }
    selected_label = st.selectbox("Select contact to inspect", list(label_map.keys()))
    selected_contact = label_map[selected_label]

    detail_col_a, detail_col_b, detail_col_c = st.columns(3)
    detail_col_a.metric("Type", selected_contact["contact_type"])
    detail_col_b.metric("Channel", selected_contact["channel"])
    detail_col_c.metric("Follow-up", selected_contact["follow_up_status"])

    st.subheader("Linked Applications")
    linked_ids = set(selected_contact["application_ids"])
    linked_applications = [application for application in applications if int(application["id"]) in linked_ids]
    linked_df = _with_display_sequence(pd.DataFrame(linked_applications))
    st.dataframe(
        linked_df[
            [
                "#",
                "company",
                "role",
                "location",
                "application_date",
                "status",
                "next_action",
                "follow_up_date",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.caption(selected_contact["linked_applications"])


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

    filtered_df = _with_display_sequence(pd.DataFrame(filtered_applications))
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
        "Mark no response",
        disabled=not selected_ids,
        key="bulk_no_response_applications",
    ):
        changed = _apply_bulk_application_action(selected_ids, applications, "mark_no_response")
        st.session_state["application_bulk_success_message"] = f"Marked {changed} application(s) as no response."
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
    bulk_col_d.caption(
        "Select rows in the table, then apply one bulk action. Archive uses No Response and clears active follow-ups."
    )

    label_id_map = _application_label_id_map(filtered_applications)
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

    render_email_analysis_report(
        result,
        details,
        match,
        match_candidates,
        create_recommendation,
        has_applications=bool(applications),
    )
    if feedback:
        st.success(
            "Saved manual feedback was applied to this email "
            f"({float(feedback.get('similarity') or 0):.0%} similarity)."
        )

    render_email_feedback_controls(
        applications=applications,
        classification=result,
        details=details,
        match=match,
        match_candidates=match_candidates,
    )

    if applications:
        st.divider()
        st.subheader("Apply Recommendation")
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
        workflow_context = build_email_workflow_for_application(
            result,
            details,
            selected,
            match,
            match_candidates,
        )
        recommendation = workflow_context["recommendation"]
        workflow_decision = workflow_context["workflow_decision"]
        operation_summary = workflow_context["operation_summary"]

        decision_cols = st.columns(4)
        _render_compact_card(decision_cols[0], "Decision", workflow_decision["operation"])
        _render_compact_card(decision_cols[1], "Review level", workflow_decision["review_level"])
        _render_compact_card(decision_cols[2], "Follow-up", recommendation["follow_up_date"] or "-")
        _render_compact_card(decision_cols[3], "Target", selected.get("company", "-"))
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
                result,
                details,
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
                result,
                details,
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
                        result,
                        recommendation,
                        has_match=bool(match),
                        workflow_decision=workflow_decision,
                    )
                ),
                use_container_width=True,
                hide_index=True,
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


def _render_compact_card(column: object, label: str, value: object, detail: str = "") -> None:
    with column.container(border=True):
        st.caption(label)
        st.markdown(f"**{_compact_display(value)}**")
        if detail:
            st.caption(detail)


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

    st.subheader("Calendar Export")
    calendar_items = build_calendar_items(applications)
    if not calendar_items:
        st.info("Add follow-up dates to interviews, assessments, or applications to export calendar events.")
    else:
        event_type_options = sorted({item.event_type for item in calendar_items})
        cal_col_a, cal_col_b = st.columns([1, 1.4])
        selected_event_types = cal_col_a.multiselect(
            "Event types",
            event_type_options,
            default=event_type_options,
            key="calendar_event_type_filter",
        )
        calendar_date_range = cal_col_b.date_input(
            "Calendar date range",
            value=(),
            key="calendar_export_date_range",
        )
        calendar_start_date, calendar_end_date = _date_range_bounds(calendar_date_range)
        filtered_calendar_items = _filter_calendar_items(
            calendar_items,
            selected_event_types=selected_event_types,
            start_date=calendar_start_date,
            end_date=calendar_end_date,
        )

        if not filtered_calendar_items:
            st.info("No calendar events match the current filters.")
        else:
            st.dataframe(
                pd.DataFrame(calendar_items_to_rows(filtered_calendar_items)),
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                "Download calendar .ics",
                build_ics_calendar(filtered_calendar_items).encode("utf-8"),
                file_name="careerops_calendar.ics",
                mime="text/calendar",
            )
            st.text_area(
                "Calendar text block",
                value=build_calendar_text_block(filtered_calendar_items),
                height=220,
                key="calendar_text_block",
            )

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


def _filter_contact_records(
    contacts: list[dict],
    *,
    search_query: str,
    selected_types: list[str],
    selected_channels: list[str],
    follow_up_only: bool,
) -> list[dict]:
    normalized_query = " ".join(search_query.casefold().split())
    type_filter = set(selected_types)
    channel_filter = set(selected_channels)
    filtered = []

    for contact in contacts:
        if type_filter and str(contact["contact_type"]) not in type_filter:
            continue
        if channel_filter and str(contact["channel"]) not in channel_filter:
            continue
        if follow_up_only and contact["follow_up_status"] == "None":
            continue
        if normalized_query:
            haystack = " ".join(
                str(contact.get(field, ""))
                for field in ["contact", "email", "companies", "linked_applications", "contact_type", "channel"]
            ).casefold()
            if normalized_query not in haystack:
                continue
        filtered.append(contact)

    return filtered


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


def _option_index(options: list[str], value: str) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


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
