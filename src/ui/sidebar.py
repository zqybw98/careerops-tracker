from __future__ import annotations

import streamlit as st

WORKSPACE_OPTIONS = ["Applications", "Analytics", "More"]


def normalize_workspace(value: object) -> str:
    workspace = str(value or "").strip()
    if workspace in WORKSPACE_OPTIONS:
        return workspace
    if workspace == "Overview":
        return "Analytics"
    if workspace in {"Contacts", "Email Assistant", "Assistant", "Data & Settings"}:
        return "More"
    return "Applications"


def render_sidebar_navigation(applications: list[dict], reminders: list[dict]) -> str:
    with st.sidebar:
        st.title("CareerOps")
        st.caption("Job search operations tracker")
        current_workspace = st.session_state.get("workspace_nav")
        if current_workspace is not None and current_workspace not in WORKSPACE_OPTIONS:
            st.session_state["workspace_nav"] = normalize_workspace(current_workspace)
        workspace = st.radio(
            "Workspace",
            WORKSPACE_OPTIONS,
            key="workspace_nav",
            label_visibility="collapsed",
        )
        st.divider()
        st.caption(f"{len(applications)} tracked applications")
        st.caption("Local data stays in SQLite. Gmail sync is optional and read-only.")
    return workspace
