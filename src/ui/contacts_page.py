from __future__ import annotations

import pandas as pd
import streamlit as st

from src.contacts import build_contact_records
from src.database import get_application_events
from src.ui.components import with_display_sequence


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
    linked_df = with_display_sequence(pd.DataFrame(linked_applications))
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
