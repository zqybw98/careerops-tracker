from __future__ import annotations

import streamlit as st

WORKSPACE_OPTIONS = ["Overview", "Applications", "Contacts", "Email Assistant", "Data & Settings"]


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
