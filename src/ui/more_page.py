from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from src.ui.contacts_page import render_contacts
from src.ui.data_settings_page import render_data_tools
from src.ui.email_assistant_page import render_assistant_workspace

MORE_SECTIONS = ["Email tools", "Contacts", "Data & Settings", "Advanced applications"]


def render_more_page(
    applications: list[dict[str, Any]],
    *,
    render_advanced_applications: Callable[[list[dict]], None],
) -> None:
    current_section = st.session_state.get("more_section")
    if current_section not in MORE_SECTIONS:
        st.session_state["more_section"] = "Email tools"

    section = st.segmented_control(
        "Tools",
        MORE_SECTIONS,
        key="more_section",
        width="stretch",
        label_visibility="collapsed",
    )
    st.divider()

    if section == "Contacts":
        render_contacts(applications)
    elif section == "Data & Settings":
        render_data_tools(applications)
    elif section == "Advanced applications":
        st.caption("Bulk cleanup, duplicate review, company research, and full record management.")
        render_advanced_applications(applications)
    else:
        render_assistant_workspace(applications)
