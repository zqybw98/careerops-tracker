from __future__ import annotations

import warnings

import streamlit as st

from src.capture_api import (
    CAPTURE_BRIDGE_HOST,
    CAPTURE_BRIDGE_PORT,
    CaptureBridgeStatus,
    PairingStateError,
    ensure_capture_bridge_started,
    get_owned_capture_pairing_token,
    is_local_capture_run,
    rotate_owned_capture_pairing_token,
)

_OWNED_BRIDGE_STATES = frozenset({"running", "running_with_warning"})


def pairing_ui_state(
    *,
    local_run: bool,
    bridge_status: CaptureBridgeStatus,
) -> dict[str, bool | str]:
    owns_bridge = local_run and bridge_status.state in _OWNED_BRIDGE_STATES
    return {
        "message": bridge_status.message,
        "show_pairing_instructions": owns_bridge,
        "can_reveal_token": owns_bridge,
        "can_rotate_token": owns_bridge,
        "show_warning": bridge_status.state
        in {"running_with_warning", "external_bridge_detected", "port_conflict", "startup_error"},
    }


def render_capture_pairing() -> None:
    rotation_completed = bool(st.session_state.pop("capture_pairing_rotation_completed", False))
    if rotation_completed:
        st.session_state["capture_pairing_reveal_token"] = False
        st.session_state["capture_pairing_confirm_rotation"] = False

    bridge_status = ensure_capture_bridge_started()
    ui_state = pairing_ui_state(
        local_run=is_local_capture_run(),
        bridge_status=bridge_status,
    )
    st.caption(f"Local endpoint: http://{CAPTURE_BRIDGE_HOST}:{CAPTURE_BRIDGE_PORT}")

    message = str(ui_state["message"])
    if ui_state["show_warning"]:
        st.warning(message)
    elif bridge_status.state == "running":
        st.success(message)
    else:
        st.info(message)

    if rotation_completed:
        st.success("Pairing token rotated. Update the token in the extension.")

    if not ui_state["show_pairing_instructions"]:
        return

    st.markdown(
        "1. Open the CareerOps Capture extension options.\n"
        "2. Grant the optional loopback permission.\n"
        "3. Reveal this local token and paste it into the extension.\n"
        "4. Confirm pairing from the extension."
    )

    reveal_token = st.toggle(
        "Reveal pairing token",
        value=False,
        key="capture_pairing_reveal_token",
    )
    if reveal_token and ui_state["can_reveal_token"]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                token = get_owned_capture_pairing_token()
            st.code(token, language="text")
        except (PairingStateError, RuntimeError):
            st.error("The local pairing token could not be read safely.")

    confirm_rotation = st.checkbox(
        "I understand that rotating the token disconnects the current extension.",
        key="capture_pairing_confirm_rotation",
    )
    if st.button(
        "Rotate pairing token",
        disabled=not confirm_rotation or not bool(ui_state["can_rotate_token"]),
        key="capture_pairing_rotate_token",
    ):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                rotate_owned_capture_pairing_token()
            st.session_state["capture_pairing_rotation_completed"] = True
            st.rerun()
        except (PairingStateError, RuntimeError):
            st.error("The pairing token could not be rotated safely.")
