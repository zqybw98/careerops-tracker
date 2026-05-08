from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st
from src.analytics import (
    build_applications_per_week,
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
from src.email_parser import extract_application_details, match_application_from_email
from src.email_templates import TEMPLATE_TYPES, generate_email_template, suggest_template_type
from src.models import APPLICATION_COLUMNS, STATUS_OPTIONS
from src.reminder_engine import generate_reminders

st.set_page_config(
    page_title="CareerOps Tracker",
    layout="wide",
)

init_db()


def main() -> None:
    st.title("CareerOps Tracker")
    st.caption("Job application tracking, email classification, and follow-up reminders.")

    applications = get_applications()
    reminders = generate_reminders(applications)

    dashboard_tab, applications_tab, email_tab, templates_tab, data_tab = st.tabs(
        ["Dashboard", "Applications", "Email Assistant", "Templates", "Data"]
    )

    with dashboard_tab:
        render_dashboard(applications, reminders)

    with applications_tab:
        render_applications(applications)

    with email_tab:
        render_email_assistant(applications)

    with templates_tab:
        render_email_templates(applications)

    with data_tab:
        render_data_tools(applications)


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
        weekly_df = pd.DataFrame(build_applications_per_week(applications))
        if weekly_df.empty:
            st.info("Add application dates to see weekly application volume.")
        else:
            weekly_fig = px.bar(
                weekly_df,
                x="week",
                y="applications",
                title="Applications per Week",
                text="applications",
            )
            weekly_fig.update_layout(xaxis_title="", yaxis_title="Applications")
            _style_bar_labels(weekly_fig)
            st.plotly_chart(weekly_fig, use_container_width=True)

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

    st.subheader("Recent Applications")
    display_df = _with_display_sequence(df)
    st.dataframe(
        display_df[
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
        result = classify_email(subject=subject, body=body)
        details = extract_application_details(subject=subject, body=body)
        match = match_application_from_email(
            applications,
            subject=subject,
            body=body,
            extracted_details=details,
        )
        st.session_state["last_classification"] = result
        st.session_state["last_email_details"] = details
        st.session_state["last_application_match"] = match

    result = st.session_state.get("last_classification")
    if not result:
        st.info("Paste an email and classify it to get a suggested status update.")
        return

    details = st.session_state.get("last_email_details", {})
    match = st.session_state.get("last_application_match")

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Category", result["category"])
    col_b.metric("Confidence", f"{result['confidence']:.0%}")
    col_c.metric("Suggested status", result["suggested_status"])
    st.write("Suggested next action:", result["suggested_next_action"])

    if result["matched_keywords"]:
        st.write("Matched keywords:", ", ".join(result["matched_keywords"]))

    st.divider()
    st.subheader("Extracted Application Context")
    if any(details.values()):
        detail_cols = st.columns(4)
        detail_cols[0].metric("Company", details.get("company") or "-")
        detail_cols[1].metric("Role", details.get("role") or "-")
        detail_cols[2].metric("Contact", details.get("contact") or "-")
        detail_cols[3].metric("Source link", "Found" if details.get("source_link") else "-")
        if details.get("source_link"):
            st.write("Source link:", details["source_link"])
    else:
        st.info("No company, role, contact, or source link could be extracted automatically.")

    if match:
        st.success(f"Best application match: {match['company']} / {match['role']} (score {match['score']})")
        if match["reasons"]:
            st.caption("Match reason: " + ", ".join(match["reasons"]))
    elif applications:
        st.warning("No confident application match found. You can select one manually or create a new record.")

    if applications:
        st.divider()
        st.subheader("Apply Suggestion")
        label_id_map = _application_label_id_map(applications)
        labels = list(label_id_map.keys())
        default_index = _matched_label_index(labels, label_id_map, match)
        selected_label = st.selectbox(
            "Update an existing application",
            labels,
            index=default_index,
            key="email_update_select",
        )
        selected_id = label_id_map[selected_label]
        selected = next(item for item in applications if item["id"] == selected_id)

        if st.button("Apply suggested status"):
            follow_up_date = selected.get("follow_up_date", "")
            if result["suggested_follow_up_days"] is not None:
                follow_up_date = (date.today() + timedelta(days=result["suggested_follow_up_days"])).isoformat()

            notes = selected.get("notes", "")
            note_line = _build_email_note(result, details)
            updated_notes = _append_note(notes, note_line)
            contact = selected.get("contact", "") or details.get("contact", "")
            source_link = selected.get("source_link", "") or details.get("source_link", "")

            update_application(
                selected_id,
                {
                    **selected,
                    "status": result["suggested_status"],
                    "contact": contact,
                    "source_link": source_link,
                    "next_action": result["suggested_next_action"],
                    "follow_up_date": follow_up_date,
                    "notes": updated_notes,
                },
                source="email_assistant",
            )
            st.success("Application updated from email classification.")
            st.rerun()

    st.divider()
    st.subheader("Create Application from Email")
    with st.form("create_from_email_form", clear_on_submit=True):
        col_company, col_role, col_location = st.columns(3)
        company = col_company.text_input("Company", value=details.get("company", ""), key="email_create_company")
        role = col_role.text_input("Role", value=details.get("role", ""), key="email_create_role")
        location = col_location.text_input("Location", value="", key="email_create_location")

        col_date, col_status, col_follow_up = st.columns(3)
        application_date = col_date.date_input("Application date", value=date.today(), key="email_create_date")
        status_index = (
            STATUS_OPTIONS.index(result["suggested_status"]) if result["suggested_status"] in STATUS_OPTIONS else 1
        )
        status = col_status.selectbox("Status", STATUS_OPTIONS, index=status_index, key="email_create_status")
        follow_up_date = ""
        if result["suggested_follow_up_days"] is not None:
            follow_up_date = (date.today() + timedelta(days=result["suggested_follow_up_days"])).isoformat()
        keep_follow_up = col_follow_up.checkbox("Set suggested follow-up", value=bool(follow_up_date))

        source_link = st.text_input("Source link", value=details.get("source_link", ""), key="email_create_source")
        contact = st.text_input("Contact", value=details.get("contact", ""), key="email_create_contact")
        next_action = st.text_input(
            "Next action",
            value=result["suggested_next_action"],
            key="email_create_next_action",
        )
        notes = st.text_area("Notes", value=_build_email_note(result, details), key="email_create_notes")

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
                        "next_action": next_action,
                        "follow_up_date": follow_up_date if keep_follow_up else "",
                    },
                    source="email_assistant",
                )
                st.success("Application created from email.")
                st.rerun()


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
    st.subheader("Import / Export")

    if st.button("Load sample applications"):
        created = seed_sample_applications()
        if created:
            st.success(f"Loaded {created} sample applications.")
        else:
            st.info("Sample applications are already loaded.")
        st.rerun()

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

    if applications:
        export_df = _with_display_sequence(pd.DataFrame(applications))
        export_columns = ["#"] + APPLICATION_COLUMNS + ["created_at", "updated_at"]
        st.download_button(
            "Download applications CSV",
            export_df[export_columns].to_csv(index=False).encode("utf-8"),
            file_name="careerops_applications.csv",
            mime="text/csv",
        )

    st.subheader("Expected CSV Columns")
    st.code(", ".join(APPLICATION_COLUMNS), language="text")
    st.caption(
        "English and common Chinese headers are supported, "
        "for example 公司名称, 职位名称, 申请日期, 最新状态, 备注/来源."
    )


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


def _build_email_note(result: dict, details: dict[str, str]) -> str:
    note_parts = [f"Email classified as {result['category']} with {result['confidence']:.0%} confidence."]
    extracted_parts = [
        f"{label}: {details[value]}"
        for label, value in [
            ("Company", "company"),
            ("Role", "role"),
            ("Contact", "contact"),
            ("Source", "source_link"),
        ]
        if details.get(value)
    ]
    if extracted_parts:
        note_parts.append("Extracted " + "; ".join(extracted_parts))
    return " ".join(note_parts)


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
