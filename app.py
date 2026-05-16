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
from src.contacts import build_contact_records
from src.dashboard import build_summary, filter_dashboard_applications
from src.database import (
    create_application,
    deduplicate_applications,
    delete_application,
    get_application_events,
    get_applications,
    init_db,
    update_application,
)
from src.models import STATUS_OPTIONS
from src.reminder_actions import PendingAction, build_pending_action_payload
from src.reminder_engine import generate_reminders
from src.ui.data_settings_page import render_data_tools
from src.ui.email_assistant_page import render_assistant_workspace

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


def render_dashboard(applications: list[dict], reminders: list[dict]) -> None:
    include_closed = st.toggle(
        "Include closed applications",
        value=False,
        key="overview_include_closed_applications",
        help="Show Rejected and No Response records in the dashboard.",
    )
    visible_applications = filter_dashboard_applications(applications, include_closed=include_closed)
    visible_reminders = _filter_reminders_for_applications(reminders, visible_applications)
    hidden_closed_count = len(applications) - len(visible_applications)

    if not include_closed and hidden_closed_count:
        st.caption(f"Hiding {hidden_closed_count} closed application(s): Rejected / No Response.")

    pending_action_message = st.session_state.pop("pending_action_success_message", None)
    if pending_action_message:
        st.success(pending_action_message)

    summary = build_summary(visible_applications)
    pipeline_health = build_pipeline_health(visible_applications)

    metric_columns = st.columns(6)
    metric_columns[0].metric("Total shown", summary["total"])
    metric_columns[1].metric("This week", summary["applied_this_week"])
    metric_columns[2].metric("Waiting", summary["waiting"])
    metric_columns[3].metric("Interviews", summary["interviews"])
    metric_columns[4].metric("Assessments", summary["assessments"])
    if include_closed:
        metric_columns[5].metric("Rejected", summary["rejections"])
    else:
        metric_columns[5].metric("Closed hidden", hidden_closed_count)

    if not visible_applications:
        if applications:
            st.info("No active applications to show. Turn on Include closed applications to review closed records.")
        else:
            st.info("Add your first application to start building the dashboard.")
        return

    df = pd.DataFrame(visible_applications)
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
    render_dashboard_recent_editor(visible_applications, display_df)
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
        if not visible_reminders:
            st.success("No reminders due right now.")
        else:
            st.caption(f"{len(visible_reminders)} pending action(s)")
            with st.container(height=520):
                for reminder in visible_reminders:
                    render_pending_action_card(reminder, visible_applications)

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


def _go_to_applications_workspace() -> None:
    st.session_state["workspace_nav"] = "Applications"


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
    st.session_state["workspace_nav"] = "Applications"
    st.session_state["application_edit_target_id"] = application_id
    st.session_state["application_status_filter"] = STATUS_OPTIONS
    st.session_state["application_company_search"] = ""
    st.session_state["application_source_search"] = ""
    st.session_state["application_date_range"] = ()
    st.session_state["application_stale_only"] = False


def _application_by_id(applications: list[dict], application_id: int) -> dict | None:
    return next(
        (application for application in applications if int(application.get("id") or 0) == application_id), None
    )


def _filter_reminders_for_applications(reminders: list[dict], applications: list[dict]) -> list[dict]:
    application_ids = {str(application.get("id")) for application in applications}
    return [reminder for reminder in reminders if str(reminder.get("application_id")) in application_ids]


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


def _option_index(options: list[str], value: str) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


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
