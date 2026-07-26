from __future__ import annotations

import base64
import http.client
import json
import socket
import sqlite3
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest
import src.capture_api as capture_api
from src.capture_api import (
    CaptureBridgeStatus,
    build_capture_server,
    get_or_create_pairing_token,
    rotate_pairing_token,
)
from src.capture_service import (
    CaptureConflictError,
    CaptureDatabaseBusyError,
    CaptureNotFoundError,
    CaptureValidationError,
)
from src.database import get_applications, init_db

EXTENSION_ID = "abcdefghijklmnopabcdefghijklmnop"
EXTENSION_ORIGIN = f"chrome-extension://{EXTENSION_ID}"
OTHER_EXTENSION_ID = "ponmlkjihgfedcbaponmlkjihgfedcba"
OTHER_EXTENSION_ORIGIN = f"chrome-extension://{OTHER_EXTENSION_ID}"
API_VERSION = "1"
MAX_BODY_BYTES = 256 * 1024

pytestmark = pytest.mark.filterwarnings(
    "ignore:Current-user-only permissions for local pairing state could not be confirmed"
)


@dataclass(frozen=True)
class RunningBridge:
    base_url: str
    host: str
    port: int
    token: str
    db_path: Path
    pairing_path: Path


@contextmanager
def _running_bridge(
    tmp_path: Path,
    *,
    initialize_database: bool = True,
) -> Iterator[RunningBridge]:
    db_path = tmp_path / "applications.db"
    pairing_path = tmp_path / "capture_pairing.json"
    if initialize_database:
        init_db(db_path)
    token = get_or_create_pairing_token(pairing_path)
    server = build_capture_server(
        host="127.0.0.1",
        port=0,
        db_path=db_path,
        pairing_path=pairing_path,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    bridge = RunningBridge(
        base_url=f"http://{host}:{port}",
        host=str(host),
        port=int(port),
        token=token,
        db_path=db_path,
        pairing_path=pairing_path,
    )
    try:
        yield bridge
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def _preview_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Example GmbH",
        "role": "QA Engineer",
        "location": "Berlin",
        "application_date": "2026-07-25",
        "status": "Applied",
        "source_link": "https://example.com/jobs/qa",
        "notes": "Captured from a reviewed job page.",
    }
    payload.update(overrides)
    return payload


def _valid_synthetic_pairing_token() -> str:
    return base64.urlsafe_b64encode(b"careerops-capture-token-bytes-000").decode("ascii").rstrip("=")


def _write_existing_pairing_state(
    path: Path,
    *,
    token: str | None = None,
    updated_at: str = "2026-07-25T12:00:00+00:00",
) -> str:
    stored_token = token or _valid_synthetic_pairing_token()
    path.write_text(
        json.dumps(
            {
                "token": stored_token,
                "paired_origin": None,
                "updated_at": updated_at,
            }
        ),
        encoding="utf-8",
    )
    return stored_token


def _confirmed_payload(**overrides: object) -> dict[str, object]:
    payload = _preview_payload(
        client_request_id=str(uuid4()),
        duplicate_resolution="none",
        edited_fields=[],
    )
    payload.update(overrides)
    return payload


def _request(
    bridge: RunningBridge,
    method: str,
    path: str,
    *,
    body: object | bytes | None = None,
    origin: str | None = EXTENSION_ORIGIN,
    token: str | None = None,
    api_version: str | None = API_VERSION,
    content_type: str | None = "application/json",
    extra_headers: dict[str, str] | None = None,
    timeout: float = 3,
) -> tuple[int, dict[str, str], object | None]:
    data: bytes | None
    if isinstance(body, bytes):
        data = body
    elif body is None:
        data = None
    else:
        data = json.dumps(body).encode("utf-8")

    headers: dict[str, str] = {}
    if origin is not None:
        headers["Origin"] = origin
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if api_version is not None:
        headers["X-CareerOps-API-Version"] = api_version
    if content_type is not None and method == "POST":
        headers["Content-Type"] = content_type
    if extra_headers:
        headers.update(extra_headers)

    request = Request(
        f"{bridge.base_url}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as error:
        response = error

    raw_body = response.read()
    parsed_body = json.loads(raw_body.decode("utf-8")) if raw_body else None
    return int(response.status), dict(response.headers.items()), parsed_body


def _raw_post(
    bridge: RunningBridge,
    path: str,
    *,
    content_length: str | None,
    body: bytes = b"",
    close_write: bool = False,
    origin: str | None = EXTENSION_ORIGIN,
) -> tuple[int, dict[str, str], object | None]:
    connection = http.client.HTTPConnection(bridge.host, bridge.port, timeout=3)
    connection.putrequest("POST", path)
    if origin is not None:
        connection.putheader("Origin", origin)
    connection.putheader("Authorization", f"Bearer {bridge.token}")
    connection.putheader("X-CareerOps-API-Version", API_VERSION)
    connection.putheader("Content-Type", "application/json")
    if content_length is not None:
        connection.putheader("Content-Length", content_length)
    connection.endheaders()
    if body:
        connection.send(body)
    if close_write and connection.sock is not None:
        connection.sock.shutdown(socket.SHUT_WR)
    response = connection.getresponse()
    raw_body = response.read()
    headers = dict(response.headers.items())
    status = int(response.status)
    connection.close()
    parsed_body = json.loads(raw_body.decode("utf-8")) if raw_body else None
    return status, headers, parsed_body


def _pair(
    bridge: RunningBridge,
    *,
    origin: str = EXTENSION_ORIGIN,
    token: str | None = None,
) -> tuple[int, dict[str, str], object | None]:
    return _request(
        bridge,
        "POST",
        "/api/v1/pair/confirm",
        body={},
        origin=origin,
        token=token or bridge.token,
    )


def _error_code(body: object | None) -> str:
    assert isinstance(body, dict)
    error = body.get("error")
    assert isinstance(error, dict)
    code = error.get("code")
    assert isinstance(code, str)
    return code


def test_capture_bridge_status_is_frozen() -> None:
    status = CaptureBridgeStatus(state="ready", message="Bridge ready.", port=8765)

    with pytest.raises(FrozenInstanceError):
        status.state = "changed"  # type: ignore[misc]


def test_first_pairing_read_generates_strong_token_and_expected_file(tmp_path: Path) -> None:
    pairing_path = tmp_path / "state" / "capture_pairing.json"

    token = get_or_create_pairing_token(pairing_path)
    decoded = base64.urlsafe_b64decode(token + ("=" * (-len(token) % 4)))
    stored = json.loads(pairing_path.read_text(encoding="utf-8"))

    assert len(decoded) >= 32
    assert set(stored) == {"token", "paired_origin", "updated_at"}
    assert stored["token"] == token
    assert stored["paired_origin"] is None
    assert isinstance(stored["updated_at"], str)


def test_normal_pairing_read_reuses_token(tmp_path: Path) -> None:
    pairing_path = tmp_path / "capture_pairing.json"

    first = get_or_create_pairing_token(pairing_path)
    second = get_or_create_pairing_token(pairing_path)

    assert second == first


def test_existing_pairing_file_rejects_weak_token(tmp_path: Path) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    _write_existing_pairing_state(pairing_path, token="x")

    with pytest.raises(capture_api.PairingStateError, match="invalid"):
        get_or_create_pairing_token(pairing_path)


def test_existing_pairing_file_rejects_invalid_timestamp(tmp_path: Path) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    _write_existing_pairing_state(pairing_path, updated_at="not-a-date")

    with pytest.raises(capture_api.PairingStateError, match="invalid"):
        get_or_create_pairing_token(pairing_path)


@pytest.mark.skipif(
    capture_api._is_windows_platform(),
    reason="POSIX mode repair requires POSIX chmod semantics.",
)
def test_existing_pairing_file_repairs_posix_permissions(
    tmp_path: Path,
) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    token = _write_existing_pairing_state(pairing_path)
    pairing_path.chmod(0o644)

    returned_token = get_or_create_pairing_token(pairing_path)

    assert returned_token == token
    assert stat.S_IMODE(pairing_path.stat().st_mode) == 0o600


def test_existing_pairing_permission_warning_contains_no_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    token = _write_existing_pairing_state(pairing_path)
    monkeypatch.setattr(capture_api, "_restrict_pairing_file_permissions", lambda _path: False)
    monkeypatch.setattr(capture_api, "_is_windows_platform", lambda: True)

    with pytest.warns(RuntimeWarning) as warning:
        returned_token = get_or_create_pairing_token(pairing_path)

    warning_text = " ".join(str(item.message) for item in warning)
    assert returned_token == token
    assert token not in warning_text
    assert str(pairing_path) not in warning_text


def test_posix_permission_failure_rejects_existing_pairing_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    token = _write_existing_pairing_state(pairing_path)
    monkeypatch.setattr(capture_api, "_restrict_pairing_file_permissions", lambda _path: False)
    monkeypatch.setattr(capture_api, "_is_windows_platform", lambda: False)

    with pytest.raises(capture_api.PairingStateError, match="secure local pairing state") as error:
        get_or_create_pairing_token(pairing_path)

    assert token not in str(error.value)
    assert str(pairing_path) not in str(error.value)


def test_failed_posix_initial_creation_leaves_no_pairing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    token = _valid_synthetic_pairing_token()
    monkeypatch.setattr(capture_api.secrets, "token_urlsafe", lambda _size: token)
    monkeypatch.setattr(capture_api, "_restrict_pairing_file_permissions", lambda _path: False)
    monkeypatch.setattr(capture_api, "_is_windows_platform", lambda: False)

    with pytest.raises(capture_api.PairingStateError, match="secure local pairing state") as error:
        get_or_create_pairing_token(pairing_path)

    assert token not in str(error.value)
    assert str(pairing_path) not in str(error.value)
    assert not pairing_path.exists()
    assert not list(pairing_path.parent.glob(f".{pairing_path.name}.*.tmp"))


def test_failed_posix_server_start_leaves_no_pairing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    monkeypatch.setattr(capture_api, "_restrict_pairing_file_permissions", lambda _path: False)
    monkeypatch.setattr(capture_api, "_is_windows_platform", lambda: False)

    def fail_if_server_is_constructed(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Server construction must not follow insecure pairing state.")

    monkeypatch.setattr(capture_api, "_CaptureHTTPServer", fail_if_server_is_constructed)

    with pytest.raises(capture_api.PairingStateError, match="secure local pairing state"):
        build_capture_server(
            host="127.0.0.1",
            port=0,
            db_path=tmp_path / "applications.db",
            pairing_path=pairing_path,
        )

    assert not pairing_path.exists()
    assert not list(pairing_path.parent.glob(f".{pairing_path.name}.*.tmp"))


def test_windows_permission_failure_remains_warning_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    token = _write_existing_pairing_state(pairing_path)
    monkeypatch.setattr(capture_api, "_restrict_pairing_file_permissions", lambda _path: False)
    monkeypatch.setattr(capture_api, "_is_windows_platform", lambda: True)

    with pytest.warns(RuntimeWarning):
        returned_token = get_or_create_pairing_token(pairing_path)

    assert returned_token == token


def test_rotation_atomically_replaces_token_and_clears_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    old_token = get_or_create_pairing_token(pairing_path)
    state = json.loads(pairing_path.read_text(encoding="utf-8"))
    state["paired_origin"] = EXTENSION_ORIGIN
    pairing_path.write_text(json.dumps(state), encoding="utf-8")
    replace_calls: list[tuple[Path, Path]] = []
    original_replace = Path.replace

    def tracked_replace(source: Path, target: Path) -> Path:
        replace_calls.append((source, target))
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", tracked_replace)

    new_token = rotate_pairing_token(pairing_path)
    stored = json.loads(pairing_path.read_text(encoding="utf-8"))

    assert new_token != old_token
    assert stored["token"] == new_token
    assert stored["paired_origin"] is None
    assert set(stored) == {"token", "paired_origin", "updated_at"}
    assert replace_calls
    assert replace_calls[-1][1] == pairing_path
    assert not list(pairing_path.parent.glob(f".{pairing_path.name}.*.tmp"))


def test_failed_posix_rotation_preserves_existing_token_and_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    old_token = _write_existing_pairing_state(pairing_path)
    state = json.loads(pairing_path.read_text(encoding="utf-8"))
    state["paired_origin"] = EXTENSION_ORIGIN
    pairing_path.write_text(json.dumps(state), encoding="utf-8")
    original_contents = pairing_path.read_bytes()
    monkeypatch.setattr(capture_api, "_restrict_pairing_file_permissions", lambda _path: False)
    monkeypatch.setattr(capture_api, "_is_windows_platform", lambda: False)

    with pytest.raises(capture_api.PairingStateError, match="secure local pairing state"):
        rotate_pairing_token(pairing_path)

    stored = json.loads(pairing_path.read_text(encoding="utf-8"))
    assert pairing_path.read_bytes() == original_contents
    assert stored["token"] == old_token
    assert stored["paired_origin"] == EXTENSION_ORIGIN
    assert not list(pairing_path.parent.glob(f".{pairing_path.name}.*.tmp"))


def test_permission_restriction_failure_warns_without_token_or_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    synthetic_token = _valid_synthetic_pairing_token()
    monkeypatch.setattr(capture_api.secrets, "token_urlsafe", lambda _size: synthetic_token)
    monkeypatch.setattr(capture_api, "_restrict_pairing_file_permissions", lambda _path: False)
    monkeypatch.setattr(capture_api, "_is_windows_platform", lambda: True)

    with pytest.warns(RuntimeWarning) as warning:
        returned_token = get_or_create_pairing_token(pairing_path)

    warning_text = " ".join(str(item.message) for item in warning)
    assert returned_token == synthetic_token
    assert synthetic_token not in warning_text
    assert str(pairing_path) not in warning_text


def test_windows_permission_restriction_is_reported_as_unconfirmed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    pairing_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(capture_api, "_is_windows_platform", lambda: True)

    assert capture_api._restrict_pairing_file_permissions(pairing_path) is False


def test_pairing_write_failure_uses_generic_exception_without_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pairing_path = tmp_path / "capture_pairing.json"
    synthetic_token = "synthetic-local-capture-secret"
    monkeypatch.setattr(capture_api.secrets, "token_urlsafe", lambda _size: synthetic_token)

    def fail_replace(_source: Path, _target: Path) -> Path:
        raise OSError("synthetic low-level write failure")

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(RuntimeError) as error:
        get_or_create_pairing_token(pairing_path)

    assert synthetic_token not in str(error.value)
    assert str(pairing_path) not in str(error.value)


def test_build_server_rejects_non_loopback_host(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="127.0.0.1"):
        build_capture_server(
            host="0.0.0.0",
            port=0,
            db_path=tmp_path / "applications.db",
            pairing_path=tmp_path / "capture_pairing.json",
        )


def test_health_returns_only_public_identity_and_no_store(tmp_path: Path) -> None:
    with _running_bridge(tmp_path) as bridge:
        status, headers, body = _request(
            bridge,
            "GET",
            "/api/v1/health",
            origin=EXTENSION_ORIGIN,
            token=None,
            api_version=None,
            content_type=None,
        )

    assert status == 200
    assert body == {
        "service": "careerops-capture-bridge",
        "api_version": "1",
        "status": "ok",
    }
    assert headers["Cache-Control"] == "no-store"
    assert headers["Access-Control-Allow-Origin"] == EXTENSION_ORIGIN
    serialized = json.dumps(body)
    assert bridge.token not in serialized
    assert str(bridge.db_path) not in serialized
    assert str(bridge.pairing_path) not in serialized


def test_health_does_not_echo_invalid_origin(tmp_path: Path) -> None:
    with _running_bridge(tmp_path) as bridge:
        status, headers, _body = _request(
            bridge,
            "GET",
            "/api/v1/health",
            origin="https://example.com",
            token=None,
            api_version=None,
            content_type=None,
        )

    assert status == 200
    assert "Access-Control-Allow-Origin" not in headers


def test_first_origin_pairs_and_same_origin_reconnects(tmp_path: Path) -> None:
    with _running_bridge(tmp_path) as bridge:
        first_status, first_headers, first_body = _pair(bridge)
        second_status, second_headers, second_body = _pair(bridge)

    assert first_status == 200
    assert second_status == 200
    assert first_body == {"paired": True}
    assert second_body == {"paired": True}
    assert first_headers["Access-Control-Allow-Origin"] == EXTENSION_ORIGIN
    assert second_headers["Access-Control-Allow-Origin"] == EXTENSION_ORIGIN
    stored = json.loads(bridge.pairing_path.read_text(encoding="utf-8"))
    assert stored["paired_origin"] == EXTENSION_ORIGIN
    assert bridge.token not in json.dumps(first_body)


def test_different_origin_is_rejected_until_rotation(tmp_path: Path) -> None:
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        rejected_status, rejected_headers, rejected_body = _pair(
            bridge,
            origin=OTHER_EXTENSION_ORIGIN,
        )
        new_token = rotate_pairing_token(bridge.pairing_path)
        old_token_status, _headers, old_token_body = _pair(
            bridge,
            origin=OTHER_EXTENSION_ORIGIN,
            token=bridge.token,
        )
        repaired_status, _headers, repaired_body = _pair(
            bridge,
            origin=OTHER_EXTENSION_ORIGIN,
            token=new_token,
        )

    assert rejected_status == 403
    assert rejected_headers["Access-Control-Allow-Origin"] == OTHER_EXTENSION_ORIGIN
    assert _error_code(rejected_body) == "forbidden_origin"
    assert old_token_status == 401
    assert _error_code(old_token_body) == "unauthorized"
    assert repaired_status == 200
    assert repaired_body == {"paired": True}


def test_rotation_cannot_leave_old_token_paired_to_new_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compare_started = threading.Event()
    allow_compare = threading.Event()
    original_compare_digest = capture_api.secrets.compare_digest

    def blocking_compare_digest(left: str, right: str) -> bool:
        compare_started.set()
        assert allow_compare.wait(timeout=3)
        return original_compare_digest(left, right)

    monkeypatch.setattr(capture_api.secrets, "compare_digest", blocking_compare_digest)

    with _running_bridge(tmp_path) as bridge:
        pair_results: list[tuple[int, dict[str, str], object | None]] = []
        rotated_tokens: list[str] = []
        pair_thread = threading.Thread(target=lambda: pair_results.append(_pair(bridge)))
        pair_thread.start()
        assert compare_started.wait(timeout=3)

        rotation_thread = threading.Thread(
            target=lambda: rotated_tokens.append(rotate_pairing_token(bridge.pairing_path))
        )
        rotation_thread.start()
        rotation_thread.join(timeout=0.2)
        rotation_was_blocked = rotation_thread.is_alive()

        allow_compare.set()
        pair_thread.join(timeout=3)
        rotation_thread.join(timeout=3)

    assert rotation_was_blocked
    assert not pair_thread.is_alive()
    assert not rotation_thread.is_alive()
    assert pair_results[0][0] in {200, 401}
    stored = json.loads(bridge.pairing_path.read_text(encoding="utf-8"))
    assert stored["token"] == rotated_tokens[0]
    assert stored["paired_origin"] is None


def test_rotation_rejects_old_token_after_request_body_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_authorization_complete = threading.Event()
    original_authorize = capture_api._authorize_paired_request

    def tracked_authorize(
        path: Path,
        origin: str,
        authorization: str | None,
    ) -> capture_api._AuthorizationDecision:
        decision = original_authorize(path, origin, authorization)
        first_authorization_complete.set()
        return decision

    monkeypatch.setattr(capture_api, "_authorize_paired_request", tracked_authorize)

    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        request_body = json.dumps(_confirmed_payload()).encode("utf-8")
        connection = http.client.HTTPConnection(bridge.host, bridge.port, timeout=3)
        connection.putrequest("POST", "/api/v1/applications")
        connection.putheader("Origin", EXTENSION_ORIGIN)
        connection.putheader("Authorization", f"Bearer {bridge.token}")
        connection.putheader("X-CareerOps-API-Version", API_VERSION)
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(len(request_body)))
        connection.endheaders()

        assert first_authorization_complete.wait(timeout=3)
        rotate_pairing_token(bridge.pairing_path)
        connection.send(request_body)
        response = connection.getresponse()
        response_body = json.loads(response.read().decode("utf-8"))
        connection.close()

    assert response.status in {401, 403}
    assert _error_code(response_body) in {"unauthorized", "forbidden_origin"}
    assert get_applications(bridge.db_path) == []


def test_rotation_waits_for_already_authorized_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_started = threading.Event()
    allow_save = threading.Event()
    save_finished = threading.Event()

    def blocking_save(_payload: object, _db_path: Path) -> dict[str, object]:
        save_started.set()
        assert allow_save.wait(timeout=3)
        save_finished.set()
        return {
            "result": "created",
            "application_id": 42,
            "replayed": False,
            "open_url": "?workspace=Applications&application_id=42",
        }

    monkeypatch.setattr(capture_api, "save_capture", blocking_save)

    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        request_results: list[tuple[int, dict[str, str], object | None]] = []
        request_thread = threading.Thread(
            target=lambda: request_results.append(
                _request(
                    bridge,
                    "POST",
                    "/api/v1/applications",
                    body=_confirmed_payload(),
                    token=bridge.token,
                )
            )
        )
        request_thread.start()
        assert save_started.wait(timeout=3)

        rotated_tokens: list[str] = []
        rotation_thread = threading.Thread(
            target=lambda: rotated_tokens.append(rotate_pairing_token(bridge.pairing_path))
        )
        rotation_thread.start()
        rotation_thread.join(timeout=0.2)
        rotation_was_blocked = rotation_thread.is_alive()

        allow_save.set()
        request_thread.join(timeout=3)
        rotation_thread.join(timeout=3)

    assert rotation_was_blocked
    assert save_finished.is_set()
    assert not request_thread.is_alive()
    assert not rotation_thread.is_alive()
    assert request_results[0][0] == 201
    stored = json.loads(bridge.pairing_path.read_text(encoding="utf-8"))
    assert stored["token"] == rotated_tokens[0]
    assert stored["paired_origin"] is None


def test_completed_rotation_prevents_old_token_save(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_called = False

    def tracked_save(_payload: object, _db_path: Path) -> dict[str, object]:
        nonlocal save_called
        save_called = True
        return {}

    monkeypatch.setattr(capture_api, "save_capture", tracked_save)

    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        rotate_pairing_token(bridge.pairing_path)
        status, _headers, body = _request(
            bridge,
            "POST",
            "/api/v1/applications",
            body=_confirmed_payload(),
            token=bridge.token,
        )

    assert status in {401, 403}
    assert _error_code(body) in {"unauthorized", "forbidden_origin"}
    assert save_called is False


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "null",
        "http://example.com",
        "https://example.com",
        "file://example",
        f"{EXTENSION_ORIGIN}/path",
        f"{EXTENSION_ORIGIN}?query=1",
        f"{EXTENSION_ORIGIN}#fragment",
        f"chrome-extension://user@{EXTENSION_ID}",
        f"{EXTENSION_ORIGIN}:8765",
        f"chrome-extension://{EXTENSION_ID.upper()}",
        f"{EXTENSION_ORIGIN} ",
    ],
)
def test_pair_confirmation_rejects_noncanonical_origin(
    tmp_path: Path,
    origin: str | None,
) -> None:
    with _running_bridge(tmp_path) as bridge:
        status, _headers, body = _raw_post(
            bridge,
            "/api/v1/pair/confirm",
            content_length="2",
            origin=origin,
        )

    assert status == 403
    assert _error_code(body) == "forbidden_origin"


def test_authentication_uses_compare_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    original_compare_digest = capture_api.secrets.compare_digest

    def tracked_compare_digest(left: str, right: str) -> bool:
        calls.append((left, right))
        return original_compare_digest(left, right)

    monkeypatch.setattr(capture_api.secrets, "compare_digest", tracked_compare_digest)

    with _running_bridge(tmp_path) as bridge:
        status, _headers, _body = _pair(bridge)

    assert status == 200
    assert calls
    assert all(call == (bridge.token, bridge.token) for call in calls)


def test_missing_and_invalid_tokens_return_same_generic_error(tmp_path: Path) -> None:
    with _running_bridge(tmp_path) as bridge:
        missing_status, _headers, missing_body = _request(
            bridge,
            "POST",
            "/api/v1/pair/confirm",
            body={},
            token=None,
        )
        invalid_status, _headers, invalid_body = _pair(
            bridge,
            token="synthetic-wrong-local-secret",
        )

    assert missing_status == invalid_status == 401
    assert missing_body == invalid_body
    assert _error_code(missing_body) == "unauthorized"
    assert bridge.token not in json.dumps(missing_body)


def test_preview_requires_exact_paired_origin_and_token(tmp_path: Path) -> None:
    with _running_bridge(tmp_path) as bridge:
        unpaired_status, _headers, unpaired_body = _request(
            bridge,
            "POST",
            "/api/v1/applications/preview",
            body=_preview_payload(),
            token=bridge.token,
        )
        assert _pair(bridge)[0] == 200
        wrong_origin_status, _headers, wrong_origin_body = _request(
            bridge,
            "POST",
            "/api/v1/applications/preview",
            body=_preview_payload(),
            origin=OTHER_EXTENSION_ORIGIN,
            token=bridge.token,
        )
        wrong_token_status, _headers, wrong_token_body = _request(
            bridge,
            "POST",
            "/api/v1/applications/preview",
            body=_preview_payload(),
            token="synthetic-wrong-local-secret",
        )

    assert unpaired_status == 403
    assert _error_code(unpaired_body) == "forbidden_origin"
    assert wrong_origin_status == 403
    assert _error_code(wrong_origin_body) == "forbidden_origin"
    assert wrong_token_status == 401
    assert _error_code(wrong_token_body) == "unauthorized"


def test_preview_calls_service_without_writing_database(tmp_path: Path) -> None:
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        status, headers, body = _request(
            bridge,
            "POST",
            "/api/v1/applications/preview",
            body=_preview_payload(),
            token=bridge.token,
        )

    assert status == 200
    assert headers["Cache-Control"] == "no-store"
    assert isinstance(body, dict)
    assert body["normalized"]["company"] == "Example GmbH"
    assert body["duplicates"] == []
    assert get_applications(bridge.db_path) == []


def test_save_returns_created_result_and_idempotent_replay(tmp_path: Path) -> None:
    payload = _confirmed_payload()
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        first_status, first_headers, first_body = _request(
            bridge,
            "POST",
            "/api/v1/applications",
            body=payload,
            token=bridge.token,
        )
        replay_status, replay_headers, replay_body = _request(
            bridge,
            "POST",
            "/api/v1/applications",
            body=payload,
            token=bridge.token,
        )

    assert first_status == 201
    assert replay_status == 200
    assert first_headers["Cache-Control"] == replay_headers["Cache-Control"] == "no-store"
    assert isinstance(first_body, dict)
    assert isinstance(replay_body, dict)
    assert set(first_body) == {"result", "application_id", "replayed", "open_url"}
    assert first_body["result"] == "created"
    assert first_body["replayed"] is False
    assert replay_body["application_id"] == first_body["application_id"]
    assert replay_body["replayed"] is True
    assert len(get_applications(bridge.db_path)) == 1


@pytest.mark.parametrize("api_version", [None, "", "2"])
def test_unsupported_api_version_precedes_service_and_database_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    api_version: str | None,
) -> None:
    service_calls: list[object] = []

    def tracked_preview(payload: object, db_path: Path) -> dict[str, object]:
        service_calls.append((payload, db_path))
        return {}

    monkeypatch.setattr(capture_api, "preview_capture", tracked_preview)
    with _running_bridge(tmp_path, initialize_database=False) as bridge:
        assert _pair(bridge)[0] == 200
        status, _headers, body = _request(
            bridge,
            "POST",
            "/api/v1/applications/preview",
            body=_preview_payload(),
            token=bridge.token,
            api_version=api_version,
        )

    assert status == 400
    assert _error_code(body) == "unsupported_api_version"
    assert service_calls == []
    assert not bridge.db_path.exists()


def test_early_post_rejection_closes_connection(tmp_path: Path) -> None:
    with _running_bridge(tmp_path) as bridge:
        status, headers, body = _request(
            bridge,
            "POST",
            "/api/v1/pair/confirm",
            body={"marker": "must-not-be-read"},
            token="synthetic-invalid-token",
        )

    assert status == 401
    assert _error_code(body) == "unauthorized"
    assert headers["Connection"] == "close"


@pytest.mark.parametrize(
    "content_type",
    [
        None,
        "text/plain",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
        "application/json; charset=latin-1",
        "application/json; extra=value",
    ],
)
def test_post_rejects_unsupported_content_type(
    tmp_path: Path,
    content_type: str | None,
) -> None:
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        status, _headers, body = _request(
            bridge,
            "POST",
            "/api/v1/applications/preview",
            body=_preview_payload(),
            token=bridge.token,
            content_type=content_type,
        )

    assert status == 415
    assert _error_code(body) == "unsupported_media_type"


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "application/json; charset=utf-8", "application/json; charset=UTF-8"],
)
def test_post_accepts_supported_json_content_type(tmp_path: Path, content_type: str) -> None:
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        status, _headers, _body = _request(
            bridge,
            "POST",
            "/api/v1/applications/preview",
            body=_preview_payload(),
            token=bridge.token,
            content_type=content_type,
        )

    assert status == 200


def test_oversized_body_is_rejected_before_reading_or_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_calls: list[object] = []
    monkeypatch.setattr(
        capture_api,
        "preview_capture",
        lambda payload, db_path: service_calls.append((payload, db_path)),
    )
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        status, _headers, body = _raw_post(
            bridge,
            "/api/v1/applications/preview",
            content_length=str(MAX_BODY_BYTES + 1),
        )

    assert status == 413
    assert _error_code(body) == "request_too_large"
    assert service_calls == []


@pytest.mark.parametrize("content_length", [None, "", "not-a-number", "-1"])
def test_invalid_content_length_is_rejected(
    tmp_path: Path,
    content_length: str | None,
) -> None:
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        status, _headers, body = _raw_post(
            bridge,
            "/api/v1/applications/preview",
            content_length=content_length,
        )

    assert status == 400
    assert _error_code(body) == "invalid_content_length"


def test_body_shorter_than_content_length_is_rejected(tmp_path: Path) -> None:
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        status, _headers, body = _raw_post(
            bridge,
            "/api/v1/applications/preview",
            content_length="10",
            body=b"{}",
            close_write=True,
        )

    assert status == 400
    assert _error_code(body) == "invalid_content_length"


@pytest.mark.parametrize("body", [b"{not json}", b"\xff"])
def test_invalid_json_or_utf8_returns_generic_error(tmp_path: Path, body: bytes) -> None:
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        status, _headers, response_body = _request(
            bridge,
            "POST",
            "/api/v1/applications/preview",
            body=body,
            token=bridge.token,
        )

    assert status == 400
    assert _error_code(response_body) == "invalid_json"
    assert body.hex() not in json.dumps(response_body)


def test_pairing_preflight_accepts_valid_pending_origin(tmp_path: Path) -> None:
    with _running_bridge(tmp_path) as bridge:
        status, headers, body = _request(
            bridge,
            "OPTIONS",
            "/api/v1/pair/confirm",
            origin=EXTENSION_ORIGIN,
            token=None,
            api_version=None,
            content_type=None,
            extra_headers={
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": ("Authorization, Content-Type, X-CareerOps-API-Version"),
            },
        )

    assert status == 204
    assert body is None
    assert headers["Access-Control-Allow-Origin"] == EXTENSION_ORIGIN
    assert headers["Access-Control-Allow-Methods"] == "POST, OPTIONS"
    assert headers["Access-Control-Allow-Headers"] == ("Authorization, Content-Type, X-CareerOps-API-Version")
    assert headers["Cache-Control"] == "no-store"
    assert "Access-Control-Allow-Credentials" not in headers
    assert headers["Access-Control-Allow-Origin"] != "*"


def test_application_preflight_requires_paired_origin(tmp_path: Path) -> None:
    request_headers = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": ("authorization, content-type, x-careerops-api-version"),
    }
    with _running_bridge(tmp_path) as bridge:
        unpaired_status, _headers, unpaired_body = _request(
            bridge,
            "OPTIONS",
            "/api/v1/applications/preview",
            origin=EXTENSION_ORIGIN,
            token=None,
            api_version=None,
            content_type=None,
            extra_headers=request_headers,
        )
        assert _pair(bridge)[0] == 200
        paired_status, paired_headers, paired_body = _request(
            bridge,
            "OPTIONS",
            "/api/v1/applications/preview",
            origin=EXTENSION_ORIGIN,
            token=None,
            api_version=None,
            content_type=None,
            extra_headers=request_headers,
        )

    assert unpaired_status == 403
    assert _error_code(unpaired_body) == "forbidden_origin"
    assert paired_status == 204
    assert paired_body is None
    assert paired_headers["Access-Control-Allow-Origin"] == EXTENSION_ORIGIN


@pytest.mark.parametrize(
    ("path", "origin", "requested_method", "requested_headers", "expected_status", "expected_code"),
    [
        (
            "/api/v1/pair/confirm",
            "https://example.com",
            "POST",
            "Authorization, Content-Type, X-CareerOps-API-Version",
            403,
            "forbidden_origin",
        ),
        (
            "/api/v1/unknown",
            EXTENSION_ORIGIN,
            "POST",
            "Authorization, Content-Type, X-CareerOps-API-Version",
            404,
            "route_not_found",
        ),
        (
            "/api/v1/pair/confirm",
            EXTENSION_ORIGIN,
            "PUT",
            "Authorization, Content-Type, X-CareerOps-API-Version",
            405,
            "method_not_allowed",
        ),
        (
            "/api/v1/pair/confirm",
            EXTENSION_ORIGIN,
            "POST",
            "Authorization, Content-Type, X-CareerOps-API-Version, X-Extra",
            400,
            "invalid_cors_request",
        ),
    ],
)
def test_preflight_rejects_invalid_contract(
    tmp_path: Path,
    path: str,
    origin: str,
    requested_method: str,
    requested_headers: str,
    expected_status: int,
    expected_code: str,
) -> None:
    with _running_bridge(tmp_path) as bridge:
        status, headers, body = _request(
            bridge,
            "OPTIONS",
            path,
            origin=origin,
            token=None,
            api_version=None,
            content_type=None,
            extra_headers={
                "Access-Control-Request-Method": requested_method,
                "Access-Control-Request-Headers": requested_headers,
            },
        )

    assert status == expected_status
    assert _error_code(body) == expected_code
    assert headers.get("Access-Control-Allow-Origin") != "*"


@pytest.mark.parametrize(
    ("method", "path", "expected_status", "expected_code"),
    [
        ("GET", "/api/v1/applications/preview", 405, "method_not_allowed"),
        ("POST", "/api/v1/health", 405, "method_not_allowed"),
        ("PUT", "/api/v1/applications", 405, "method_not_allowed"),
        ("GET", "/api/v1/unknown", 404, "route_not_found"),
        ("POST", "/api/v1/unknown", 404, "route_not_found"),
    ],
)
def test_route_and_method_allowlist(
    tmp_path: Path,
    method: str,
    path: str,
    expected_status: int,
    expected_code: str,
) -> None:
    with _running_bridge(tmp_path) as bridge:
        status, _headers, body = _request(
            bridge,
            method,
            path,
            body={} if method == "POST" else None,
            token=bridge.token if method == "POST" else None,
        )

    assert status == expected_status
    assert _error_code(body) == expected_code


@pytest.mark.parametrize(
    ("method", "path", "expected_allow"),
    [
        ("POST", "/api/v1/health", "GET"),
        ("GET", "/api/v1/pair/confirm", "POST, OPTIONS"),
        ("GET", "/api/v1/applications/preview", "POST, OPTIONS"),
        ("GET", "/api/v1/applications", "POST, OPTIONS"),
    ],
)
def test_method_not_allowed_returns_route_allow_header(
    tmp_path: Path,
    method: str,
    path: str,
    expected_allow: str,
) -> None:
    with _running_bridge(tmp_path) as bridge:
        status, headers, body = _request(
            bridge,
            method,
            path,
            body={} if method == "POST" else None,
            token=bridge.token if method == "POST" else None,
        )

    assert status == 405
    assert headers["Allow"] == expected_allow
    assert _error_code(body) == "method_not_allowed"


def test_unlisted_http_method_uses_json_method_error(tmp_path: Path) -> None:
    with _running_bridge(tmp_path) as bridge:
        status, headers, body = _request(
            bridge,
            "PROPFIND",
            "/api/v1/applications",
            origin=EXTENSION_ORIGIN,
            token=None,
            api_version=None,
            content_type=None,
        )

    assert status == 405
    assert headers["Content-Type"].startswith("application/json")
    assert headers["Cache-Control"] == "no-store"
    assert headers["Connection"] == "close"
    assert _error_code(body) == "method_not_allowed"


def test_malformed_http_request_does_not_emit_traceback_or_local_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        _running_bridge(tmp_path) as bridge,
        socket.create_connection((bridge.host, bridge.port), timeout=3) as connection,
    ):
        connection.sendall(b"BADREQUEST\r\n\r\n")
        connection.shutdown(socket.SHUT_WR)
        response = connection.recv(4096)

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert response
    assert "Traceback" not in combined_output
    assert str(Path.cwd()) not in combined_output


@pytest.mark.parametrize(
    ("service_error", "expected_status", "expected_code", "expected_retryable"),
    [
        (
            CaptureValidationError("role", "Role is invalid."),
            422,
            "validation_error",
            False,
        ),
        (
            CaptureConflictError(
                "duplicate_conflict",
                {"duplicates": [{"application_id": 42}]},
            ),
            409,
            "duplicate_conflict",
            False,
        ),
        (
            CaptureConflictError(
                "idempotency_conflict",
                {"client_request_id": "synthetic-request-id"},
            ),
            409,
            "idempotency_conflict",
            False,
        ),
        (
            CaptureNotFoundError("existing_application_not_found"),
            404,
            "existing_application_not_found",
            False,
        ),
        (
            CaptureDatabaseBusyError(),
            503,
            "database_busy",
            True,
        ),
    ],
)
def test_service_exception_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    service_error: Exception,
    expected_status: int,
    expected_code: str,
    expected_retryable: bool,
) -> None:
    def fail_preview(_payload: object, _db_path: Path) -> dict[str, object]:
        raise service_error

    monkeypatch.setattr(capture_api, "preview_capture", fail_preview)
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        status, headers, body = _request(
            bridge,
            "POST",
            "/api/v1/applications/preview",
            body=_preview_payload(),
            token=bridge.token,
        )

    assert status == expected_status
    assert headers["Content-Type"].startswith("application/json")
    assert headers["Cache-Control"] == "no-store"
    assert isinstance(body, dict)
    error = body["error"]
    assert error["code"] == expected_code
    assert error["retryable"] is expected_retryable
    assert set(error) == {"code", "message", "retryable", "field", "details"}
    if not isinstance(service_error, CaptureConflictError):
        assert error["details"] == {}
    if isinstance(service_error, CaptureValidationError):
        assert error["field"] == "role"
        assert error["message"] == "Role is invalid."
    if isinstance(service_error, CaptureConflictError):
        assert error["details"] == service_error.details


def test_real_locked_preview_database_maps_to_retryable_503(tmp_path: Path) -> None:
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        with sqlite3.connect(bridge.db_path) as locking_connection:
            locking_connection.execute("BEGIN EXCLUSIVE")
            status, _headers, body = _request(
                bridge,
                "POST",
                "/api/v1/applications/preview",
                body=_preview_payload(),
                token=bridge.token,
                timeout=8,
            )

    assert status == 503
    assert _error_code(body) == "database_busy"
    assert isinstance(body, dict)
    assert body["error"]["retryable"] is True


def test_sqlite_error_message_does_not_control_busy_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_preview(_payload: object, _db_path: Path) -> dict[str, object]:
        raise sqlite3.OperationalError("database is locked synthetic private marker")

    monkeypatch.setattr(capture_api, "preview_capture", fail_preview)
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        status, _headers, body = _request(
            bridge,
            "POST",
            "/api/v1/applications/preview",
            body=_preview_payload(),
            token=bridge.token,
        )

    assert status == 500
    assert _error_code(body) == "internal_error"
    assert "synthetic private marker" not in json.dumps(body)


@pytest.mark.parametrize(
    "service_error",
    [
        CaptureConflictError(
            "synthetic-undocumented-conflict",
            {"private_marker": "must-not-be-returned"},
        ),
        CaptureNotFoundError("synthetic-undocumented-not-found"),
    ],
)
def test_unknown_typed_service_error_returns_generic_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    service_error: Exception,
) -> None:
    def fail_preview(_payload: object, _db_path: Path) -> dict[str, object]:
        raise service_error

    monkeypatch.setattr(capture_api, "preview_capture", fail_preview)
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        status, headers, body = _request(
            bridge,
            "POST",
            "/api/v1/applications/preview",
            body=_preview_payload(),
            token=bridge.token,
        )

    serialized = json.dumps(body)
    assert status == 500
    assert headers["Access-Control-Allow-Origin"] == EXTENSION_ORIGIN
    assert _error_code(body) == "internal_error"
    assert "synthetic-undocumented" not in serialized
    assert "must-not-be-returned" not in serialized


def test_unexpected_exception_returns_generic_500_without_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_marker = "synthetic-private-exception-details"

    def fail_preview(_payload: object, _db_path: Path) -> dict[str, object]:
        raise RuntimeError(private_marker)

    monkeypatch.setattr(capture_api, "preview_capture", fail_preview)
    with _running_bridge(tmp_path) as bridge:
        assert _pair(bridge)[0] == 200
        status, _headers, body = _request(
            bridge,
            "POST",
            "/api/v1/applications/preview",
            body=_preview_payload(),
            token=bridge.token,
        )

    serialized = json.dumps(body)
    assert status == 500
    assert _error_code(body) == "internal_error"
    assert _headers["Access-Control-Allow-Origin"] == EXTENSION_ORIGIN
    assert private_marker not in serialized
    assert "RuntimeError" not in serialized
    assert "Traceback" not in serialized


def test_authorization_and_body_are_not_logged(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    synthetic_token = "synthetic-token-that-must-not-be-logged"
    private_body_marker = "synthetic-body-that-must-not-be-logged"
    with _running_bridge(tmp_path) as bridge:
        status, _headers, _body = _request(
            bridge,
            "POST",
            "/api/v1/pair/confirm",
            body={"marker": private_body_marker},
            token=synthetic_token,
        )

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert status == 401
    assert synthetic_token not in combined_output
    assert private_body_marker not in combined_output
    assert str(bridge.pairing_path) not in combined_output


def test_failed_posix_pair_confirmation_does_not_bind_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _running_bridge(tmp_path) as bridge:
        original_contents = bridge.pairing_path.read_bytes()
        monkeypatch.setattr(capture_api, "_restrict_pairing_file_permissions", lambda _path: False)
        monkeypatch.setattr(capture_api, "_is_windows_platform", lambda: False)

        status, _headers, body = _pair(bridge)
        stored = json.loads(bridge.pairing_path.read_text(encoding="utf-8"))
        temporary_files = list(bridge.pairing_path.parent.glob(f".{bridge.pairing_path.name}.*.tmp"))

    serialized_body = json.dumps(body)
    assert status == 500
    assert _error_code(body) == "internal_error"
    assert bridge.pairing_path.read_bytes() == original_contents
    assert stored["token"] == bridge.token
    assert stored["paired_origin"] is None
    assert bridge.token not in serialized_body
    assert str(bridge.pairing_path) not in serialized_body
    assert temporary_files == []
