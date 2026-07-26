from __future__ import annotations

from typing import Any

import streamlit as st

from src.database import DEFAULT_DB_PATH, get_applications

_SUPPORTED_WORKSPACE = "Applications"
_WORKSPACE_REQUEST_KEY = "_workspace_nav_request"
_DETAIL_REQUEST_KEY = "applications_pending_detail_id"


def consume_application_deep_link() -> int | None:
    workspace = _single_query_value(st.query_params.get("workspace"))
    raw_application_id = _single_query_value(st.query_params.get("application_id"))
    has_capture_parameters = "workspace" in st.query_params or "application_id" in st.query_params
    if not has_capture_parameters:
        return None

    try:
        if workspace != _SUPPORTED_WORKSPACE:
            return None

        st.session_state[_WORKSPACE_REQUEST_KEY] = _SUPPORTED_WORKSPACE
        application_id = _positive_integer(raw_application_id)
        if application_id is None or not _application_exists(application_id):
            return None

        st.session_state[_DETAIL_REQUEST_KEY] = application_id
        return application_id
    finally:
        for parameter in ("workspace", "application_id"):
            if parameter in st.query_params:
                del st.query_params[parameter]


def _single_query_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return ""


def _positive_integer(value: str) -> int | None:
    if not value.isdigit():
        return None
    application_id = int(value)
    return application_id if application_id > 0 else None


def _application_exists(application_id: int) -> bool:
    return any(int(application.get("id") or 0) == application_id for application in get_applications(DEFAULT_DB_PATH))
