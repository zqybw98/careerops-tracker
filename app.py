from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from src.dashboard import build_summary
from src.database import (
    bulk_create_applications,
    create_application,
    delete_application,
    get_applications,
    init_db,
    update_application,
)
from src.csv_importer import normalize_import_rows
from src.demo_data import seed_sample_applications
from src.email_classifier import classify_email
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

    dashboard_tab, applications_tab, email_tab, data_tab = st.tabs(
        ["Dashboard", "Applications", "Email Assistant", "Data"]
    )

    with dashboard_tab:
        render_dashboard(applications, reminders)

    with applications_tab:
        render_applications(applications)

    with email_tab:
        render_email_assistant(applications)

    with data_tab:
        render_data_tools(applications)


def render_dashboard(applications: list[dict], reminders: list[dict]) -> None:
    summary = build_summary(applications)

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
        )
        fig.update_layout(showlegend=False, xaxis_title="", yaxis_title="Applications")
        st.plotly_chart(fig, use_container_width=True)

    with reminder_col:
        st.subheader("Pending Actions")
        if not reminders:
            st.success("No reminders due right now.")
        else:
            for reminder in reminders[:8]:
                st.markdown(
                    f"**{reminder['priority']}** - {reminder['company']} / "
                    f"{reminder['role']}  \n"
                    f"{reminder['message']}  \n"
                    f"Due: `{reminder['due_date']}`"
                )

    st.subheader("Recent Applications")
    st.dataframe(
        df[
            [
                "id",
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
                    }
                )
                st.success("Application added.")
                st.rerun()

    st.subheader("Manage Applications")
    if not applications:
        st.info("No applications yet.")
        return

    df = pd.DataFrame(applications)
    selected_statuses = st.multiselect("Filter by status", STATUS_OPTIONS, default=STATUS_OPTIONS)
    filtered = df[df["status"].isin(selected_statuses)]
    st.dataframe(filtered, use_container_width=True, hide_index=True)

    selected_label = st.selectbox(
        "Select application to edit",
        [format_application_label(item) for item in applications],
    )
    selected_id = int(selected_label.split(" - ")[0])
    selected = next(item for item in applications if item["id"] == selected_id)

    with st.form("edit_application_form"):
        col_a, col_b, col_c = st.columns(3)
        company = col_a.text_input("Company", value=selected["company"], key="edit_company")
        role = col_b.text_input("Role", value=selected["role"], key="edit_role")
        location = col_c.text_input("Location", value=selected.get("location", ""), key="edit_location")

        col_d, col_e, col_f = st.columns(3)
        application_date = col_d.date_input(
            "Application date",
            value=_text_to_date(selected.get("application_date")) or date.today(),
            key="edit_application_date",
        )
        status_index = STATUS_OPTIONS.index(selected["status"]) if selected["status"] in STATUS_OPTIONS else 1
        status = col_e.selectbox("Status", STATUS_OPTIONS, index=status_index, key="edit_status")
        follow_up_value = col_f.date_input(
            "Follow-up date",
            value=_text_to_date(selected.get("follow_up_date")) or date.today() + timedelta(days=7),
            key="edit_follow_up_date",
        )
        keep_follow_up = col_f.checkbox(
            "Keep follow-up date",
            value=bool(selected.get("follow_up_date")),
            key="edit_keep_follow_up",
        )

        source_link = st.text_input("Source link", value=selected.get("source_link", ""), key="edit_source")
        contact = st.text_input("Contact", value=selected.get("contact", ""), key="edit_contact")
        next_action = st.text_input("Next action", value=selected.get("next_action", ""), key="edit_next_action")
        notes = st.text_area("Notes", value=selected.get("notes", ""), key="edit_notes")

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
            )
            st.success("Application updated.")
            st.rerun()

        if delete_clicked:
            delete_application(selected_id)
            st.warning("Application deleted.")
            st.rerun()


def render_email_assistant(applications: list[dict]) -> None:
    st.subheader("Classify Recruiting Email")
    subject = st.text_input("Email subject")
    body = st.text_area("Email body", height=220)

    if st.button("Classify email"):
        result = classify_email(subject=subject, body=body)
        st.session_state["last_classification"] = result

    result = st.session_state.get("last_classification")
    if not result:
        st.info("Paste an email and classify it to get a suggested status update.")
        return

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Category", result["category"])
    col_b.metric("Confidence", f"{result['confidence']:.0%}")
    col_c.metric("Suggested status", result["suggested_status"])
    st.write("Suggested next action:", result["suggested_next_action"])

    if result["matched_keywords"]:
        st.write("Matched keywords:", ", ".join(result["matched_keywords"]))

    if applications:
        st.divider()
        st.subheader("Apply Suggestion")
        selected_label = st.selectbox(
            "Update an existing application",
            [format_application_label(item) for item in applications],
            key="email_update_select",
        )
        selected_id = int(selected_label.split(" - ")[0])
        selected = next(item for item in applications if item["id"] == selected_id)

        if st.button("Apply suggested status"):
            follow_up_date = selected.get("follow_up_date", "")
            if result["suggested_follow_up_days"] is not None:
                follow_up_date = (date.today() + timedelta(days=result["suggested_follow_up_days"])).isoformat()

            notes = selected.get("notes", "")
            note_line = f"Email classified as {result['category']} with {result['confidence']:.0%} confidence."
            updated_notes = f"{notes}\n{note_line}".strip()

            update_application(
                selected_id,
                {
                    **selected,
                    "status": result["suggested_status"],
                    "next_action": result["suggested_next_action"],
                    "follow_up_date": follow_up_date,
                    "notes": updated_notes,
                },
            )
            st.success("Application updated from email classification.")
            st.rerun()


def render_data_tools(applications: list[dict]) -> None:
    st.subheader("Import / Export")

    if st.button("Load sample applications"):
        created = seed_sample_applications()
        if created:
            st.success(f"Loaded {created} sample applications.")
        else:
            st.info("Sample applications are already loaded.")
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
            created = bulk_create_applications(import_result.rows)
            st.success(f"Imported {created} applications.")
            st.rerun()

    if applications:
        export_df = pd.DataFrame(applications)
        st.download_button(
            "Download applications CSV",
            export_df.to_csv(index=False).encode("utf-8"),
            file_name="careerops_applications.csv",
            mime="text/csv",
        )

    st.subheader("Expected CSV Columns")
    st.code(", ".join(APPLICATION_COLUMNS), language="text")
    st.caption("English and common Chinese headers are supported, for example 公司名称, 职位名称, 申请日期, 最新状态, 备注/来源.")


def format_application_label(application: dict) -> str:
    return f"{application['id']} - {application['company']} - {application['role']}"


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
