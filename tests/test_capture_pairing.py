from __future__ import annotations

import pytest
from src.capture_api import CaptureBridgeStatus
from src.ui.capture_pairing import pairing_ui_state


@pytest.mark.parametrize("state", ["running", "running_with_warning"])
def test_local_process_owned_bridge_enables_pairing_controls(state: str) -> None:
    ui_state = pairing_ui_state(
        local_run=True,
        bridge_status=CaptureBridgeStatus(
            state=state,
            message="Capture Bridge is running.",
            port=8765,
        ),
    )

    assert ui_state["show_pairing_instructions"] is True
    assert ui_state["can_reveal_token"] is True
    assert ui_state["can_rotate_token"] is True


@pytest.mark.parametrize(
    "local_run,state",
    [
        (False, "running"),
        (False, "running_with_warning"),
        (True, "disabled"),
        (True, "hosted_disabled"),
        (True, "external_bridge_detected"),
        (True, "port_conflict"),
        (True, "startup_error"),
    ],
)
def test_non_owned_or_non_local_bridge_disables_pairing_controls(
    local_run: bool,
    state: str,
) -> None:
    ui_state = pairing_ui_state(
        local_run=local_run,
        bridge_status=CaptureBridgeStatus(
            state=state,
            message="Pairing controls are unavailable.",
            port=8765,
        ),
    )

    assert ui_state["show_pairing_instructions"] is False
    assert ui_state["can_reveal_token"] is False
    assert ui_state["can_rotate_token"] is False


def test_windows_permission_warning_is_visible_without_sensitive_details() -> None:
    token = "synthetic-token-must-not-appear"
    path = "C:/Users/example/private/capture_pairing.json"
    message = "Capture Bridge is running, but Windows permissions could not be confirmed."

    ui_state = pairing_ui_state(
        local_run=True,
        bridge_status=CaptureBridgeStatus(
            state="running_with_warning",
            message=message,
            port=8765,
        ),
    )

    assert ui_state["show_warning"] is True
    assert ui_state["message"] == message
    assert token not in str(ui_state)
    assert path not in str(ui_state)
