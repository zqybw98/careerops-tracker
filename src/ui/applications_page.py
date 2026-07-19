from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from src.application_list import (
    QuickFilter,
    build_company_suggestions,
    build_create_application_payload,
    build_edit_application_payload,
    build_list_rows,
    build_location_suggestions,
    count_quick_filters,
    filter_application_list,
    sort_application_list,
)
from src.database import create_application, update_application
from src.duplicates import find_likely_duplicate_applications, format_duplicate_candidate
from src.models import STATUS_OPTIONS

QUICK_FILTERS: tuple[QuickFilter, ...] = ("all", "active", "interview", "waiting", "rejected")
QUICK_FILTER_LABELS = {
    "all": "All",
    "active": "Active",
    "interview": "Interview",
    "waiting": "Waiting",
    "rejected": "Rejected",
}


def render_applications_page(applications: list[dict[str, Any]]) -> None:
    success_message = st.session_state.pop("applications_page_success", None)
    if success_message:
        st.success(success_message)

    pending_detail_id = st.session_state.pop("applications_pending_detail_id", None)
    add_clicked, filters = _render_toolbar(applications)
    quick_filter = _render_quick_filters(applications)

    filtered = sort_application_list(
        filter_application_list(
            applications,
            search_query=filters["search_query"],
            statuses=filters["statuses"],
            location=filters["location"],
            quick_filter=quick_filter,
        )
    )
    _render_application_table(filtered, len(applications), include_source=filters["include_source"])

    if add_clicked:
        _add_application_dialog(applications)

    if pending_detail_id is not None:
        selected = next(
            (application for application in applications if int(application.get("id") or 0) == pending_detail_id),
            None,
        )
        if selected is not None:
            _application_details_dialog(selected, applications)


def _render_toolbar(applications: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    location_options = ["All locations", *build_location_suggestions(applications)]
    search_col, location_col, status_col, add_col = st.columns([2.4, 1.35, 1.2, 0.85], vertical_alignment="bottom")
    search_query = search_col.text_input(
        "Search applications",
        placeholder="Company or role...",
        key="applications_list_search",
    )
    location_selection = location_col.selectbox(
        "Location",
        location_options,
        key="applications_list_location",
    )
    status_selection = status_col.selectbox(
        "Status",
        ["All statuses", *STATUS_OPTIONS],
        key="applications_list_status",
    )
    add_clicked = add_col.button(
        "+ Add Application",
        type="primary",
        use_container_width=True,
        key="applications_open_add_dialog",
    )
    include_source = st.checkbox("Show source column", key="applications_list_show_source")
    return add_clicked, {
        "search_query": search_query,
        "location": "" if location_selection == "All locations" else location_selection,
        "statuses": None if status_selection == "All statuses" else [status_selection],
        "include_source": include_source,
    }


def _render_quick_filters(applications: list[dict[str, Any]]) -> QuickFilter:
    counts = count_quick_filters(applications)
    selected = st.segmented_control(
        "Quick filters",
        QUICK_FILTERS,
        default="all",
        format_func=lambda value: f"{QUICK_FILTER_LABELS[value]} {counts[value]}",
        key="applications_list_quick_filter",
        label_visibility="collapsed",
        width="stretch",
    )
    return selected if selected in QUICK_FILTERS else "all"


def _render_application_table(
    applications: list[dict[str, Any]],
    total_count: int,
    *,
    include_source: bool,
) -> None:
    st.caption(f"Showing {len(applications)} of {total_count} application(s). Select a row to view or edit details.")
    if not applications:
        st.info("No applications match the current filters.")
        return

    rows = build_list_rows(applications, include_source=include_source)
    table = pd.DataFrame(rows)
    styled_table = table.style.map(_status_cell_style, subset=["Status"])
    table_version = int(st.session_state.get("applications_table_version", 0))
    event = st.dataframe(
        styled_table,
        hide_index=True,
        width="stretch",
        height=min(720, 42 + len(table) * 39),
        row_height=38,
        on_select="rerun",
        selection_mode="single-row",
        key=f"applications_master_table_{table_version}",
        column_config={
            "Company": st.column_config.TextColumn(width=130),
            "Role": st.column_config.TextColumn(width=190),
            "Location": st.column_config.TextColumn(width=100),
            "Status": st.column_config.TextColumn(width=145),
            "Applied": st.column_config.TextColumn(width=90),
            "Follow-up": st.column_config.TextColumn(width=95),
            "Source": st.column_config.LinkColumn(width=110, display_text="Open link"),
        },
    )
    selection = getattr(event, "selection", None)
    selected_rows = list(getattr(selection, "rows", []))
    if selected_rows:
        selected_index = int(selected_rows[0])
        if 0 <= selected_index < len(applications):
            st.session_state["applications_pending_detail_id"] = int(applications[selected_index]["id"])
            st.session_state["applications_table_version"] = table_version + 1
            st.rerun()


@st.dialog("Add Application", width="large")
def _add_application_dialog(applications: list[dict[str, Any]]) -> None:
    with st.form("applications_add_dialog_form"):
        company_col, role_col = st.columns(2)
        company = company_col.selectbox(
            "Company *",
            build_company_suggestions(applications, include_blank=True),
            accept_new_options=True,
            key="applications_add_company",
        )
        role = role_col.text_input("Role *", key="applications_add_role")

        location_col, status_col, date_col = st.columns(3)
        location_options = build_location_suggestions(applications, preferred="Germany", include_blank=True)
        location = location_col.selectbox(
            "Location",
            location_options,
            index=_option_index(location_options, "Germany"),
            accept_new_options=True,
            key="applications_add_location",
        )
        status = status_col.selectbox("Status", STATUS_OPTIONS, key="applications_add_status")
        application_date = date_col.date_input(
            "Application date",
            value=date.today(),
            key="applications_add_date",
        )
        source_link = st.text_input("Job link", key="applications_add_source_link")

        with st.expander("More details"):
            contact = st.text_input("Contact", key="applications_add_contact")
            has_follow_up = st.checkbox("Set follow-up date", key="applications_add_has_follow_up")
            follow_up_date = st.date_input(
                "Follow-up date",
                value=date.today() + timedelta(days=7),
                disabled=not has_follow_up,
                key="applications_add_follow_up_date",
            )
            next_action = st.text_input("Next action", key="applications_add_next_action")
            notes = st.text_area("Notes", key="applications_add_notes")
            rejection_reason = st.text_area("Rejection reason", key="applications_add_rejection_reason")

        submitted = st.form_submit_button("Save Application", type="primary")

    if not submitted:
        return
    if not company.strip() or not role.strip():
        st.error("Company and role are required.")
        return

    payload = build_create_application_payload(
        company=company,
        role=role,
        location=location,
        status=status,
        application_date=application_date,
        source_link=source_link,
        contact=contact,
        follow_up_date=follow_up_date if has_follow_up else None,
        next_action=next_action,
        notes=notes,
        rejection_reason=rejection_reason,
    )
    duplicates = find_likely_duplicate_applications(payload, applications)
    if duplicates:
        st.warning("A likely duplicate already exists. Review it before creating another record.")
        for candidate in duplicates[:3]:
            st.caption(format_duplicate_candidate(candidate))
        return

    create_application(payload, source="applications_dialog")
    st.session_state["applications_page_success"] = f"Added {payload['company']} / {payload['role']}."
    st.rerun()


@st.dialog("Application Details", width="large")
def _application_details_dialog(application: dict[str, Any], applications: list[dict[str, Any]]) -> None:
    st.subheader(str(application.get("company", "")))
    st.caption(str(application.get("role", "")))

    source_link = str(application.get("source_link", "") or "").strip()
    if source_link.startswith(("http://", "https://")):
        st.link_button("Open job post", source_link)

    application_id = int(application["id"])
    with st.form(f"applications_details_form_{application_id}"):
        status_col, location_col = st.columns(2)
        status = status_col.selectbox(
            "Status",
            STATUS_OPTIONS,
            index=_option_index(STATUS_OPTIONS, str(application.get("status", ""))),
            key=f"applications_detail_status_{application_id}",
        )
        locations = build_location_suggestions(
            applications,
            preferred=application.get("location", ""),
            include_blank=True,
        )
        location = location_col.selectbox(
            "Location",
            locations,
            index=_option_index(locations, str(application.get("location", ""))),
            accept_new_options=True,
            key=f"applications_detail_location_{application_id}",
        )

        applied_col, follow_up_col = st.columns(2)
        application_date = applied_col.date_input(
            "Application date",
            value=_text_to_date(application.get("application_date")) or date.today(),
            key=f"applications_detail_date_{application_id}",
        )
        has_follow_up = follow_up_col.checkbox(
            "Keep follow-up date",
            value=bool(application.get("follow_up_date")),
            key=f"applications_detail_has_follow_up_{application_id}",
        )
        follow_up_date = follow_up_col.date_input(
            "Follow-up date",
            value=_text_to_date(application.get("follow_up_date")) or date.today() + timedelta(days=7),
            disabled=not has_follow_up,
            key=f"applications_detail_follow_up_{application_id}",
        )

        next_action = st.text_input(
            "Next action",
            value=str(application.get("next_action", "") or ""),
            key=f"applications_detail_next_action_{application_id}",
        )
        edited_source_link = st.text_input(
            "Source link",
            value=source_link,
            key=f"applications_detail_source_{application_id}",
        )
        contact = st.text_input(
            "Contact",
            value=str(application.get("contact", "") or ""),
            key=f"applications_detail_contact_{application_id}",
        )
        notes = st.text_area(
            "Notes",
            value=str(application.get("notes", "") or ""),
            height=140,
            key=f"applications_detail_notes_{application_id}",
        )
        rejection_reason = st.text_area(
            "Rejection reason",
            value=str(application.get("rejection_reason", "") or ""),
            key=f"applications_detail_rejection_{application_id}",
        )
        saved = st.form_submit_button("Save changes", type="primary")

    if saved:
        payload = build_edit_application_payload(
            application,
            status=status,
            location=location,
            application_date=application_date,
            follow_up_date=follow_up_date if has_follow_up else None,
            next_action=next_action,
            notes=notes,
            source_link=edited_source_link,
            contact=contact,
            rejection_reason=rejection_reason,
        )
        update_application(application_id, payload, source="applications_dialog")
        st.session_state["applications_page_success"] = (
            f"Updated {application.get('company', '')} / {application.get('role', '')}."
        )
        st.rerun()

    if st.button("Paste email update", key=f"applications_detail_email_{application_id}"):
        st.session_state["email_update_select"] = (
            f"{application_id} - {application.get('company', '')} - {application.get('role', '')}"
        )
        st.session_state["more_section"] = "Email tools"
        st.session_state["_workspace_nav_request"] = "More"
        st.rerun()


def _status_cell_style(value: object) -> str:
    styles = {
        "Rejected": "color: #dc2626; background-color: #fee2e2; font-weight: 700;",
        "Interview / Assessment": "color: #15803d; background-color: #dcfce7; font-weight: 700;",
        "Waiting": "color: #a16207; background-color: #fef9c3; font-weight: 700;",
        "Action Needed": "color: #c2410c; background-color: #ffedd5; font-weight: 700;",
        "Applied": "color: #1d4ed8; background-color: #dbeafe; font-weight: 700;",
    }
    return styles.get(str(value), "")


def _option_index(options: list[str], value: str) -> int:
    try:
        return options.index(value)
    except ValueError:
        return 0


def _text_to_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or ""))
    except ValueError:
        return None
