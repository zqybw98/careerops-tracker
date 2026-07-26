from __future__ import annotations

import base64
import binascii
import http.client
import json
import os
import re
import secrets
import socket
import sqlite3
import stat
import tempfile
import threading
import warnings
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from src.capture_service import (
    CaptureConflictError,
    CaptureDatabaseBusyError,
    CaptureNotFoundError,
    CaptureValidationError,
    preview_capture,
    save_capture,
)
from src.database import DEFAULT_DB_PATH

API_VERSION = "1"
SERVICE_NAME = "careerops-capture-bridge"
MAX_REQUEST_BYTES = 256 * 1024
CAPTURE_BRIDGE_HOST = "127.0.0.1"
CAPTURE_BRIDGE_PORT = 8765
DEFAULT_PAIRING_PATH = Path(os.getenv("CAREEROPS_CAPTURE_PAIRING_PATH", "data/capture_pairing.json"))

HEALTH_PATH = "/api/v1/health"
PAIR_PATH = "/api/v1/pair/confirm"
PREVIEW_PATH = "/api/v1/applications/preview"
APPLICATIONS_PATH = "/api/v1/applications"

_POST_PATHS = frozenset({PAIR_PATH, PREVIEW_PATH, APPLICATIONS_PATH})
_KNOWN_PATHS = frozenset({HEALTH_PATH, *_POST_PATHS})
_ALLOWED_CORS_METHODS = "POST, OPTIONS"
_ALLOWED_CORS_HEADERS = "Authorization, Content-Type, X-CareerOps-API-Version"
_ALLOWED_CORS_HEADER_NAMES = frozenset({"authorization", "content-type", "x-careerops-api-version"})
_EXTENSION_ORIGIN_PATTERN = re.compile(r"chrome-extension://[a-p]{32}")
_PAIRING_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
_PAIRING_LOCK = threading.Lock()
_BRIDGE_LOCK = threading.Lock()
_BRIDGE_SERVER: ThreadingHTTPServer | None = None
_BRIDGE_THREAD: threading.Thread | None = None
_BRIDGE_STATUS: CaptureBridgeStatus | None = None
_ALLOWED_CONFLICT_CODES = frozenset({"duplicate_conflict", "idempotency_conflict"})
_ALLOWED_NOT_FOUND_CODES = frozenset({"existing_application_not_found"})

_AuthorizationDecision = Literal["authorized", "unauthorized", "forbidden"]
_BridgeProbeResult = Literal["available", "external_bridge_detected", "port_conflict"]


@dataclass(frozen=True)
class CaptureBridgeStatus:
    state: str
    message: str
    port: int


class PairingStateError(RuntimeError):
    """Raised when local pairing state cannot be read or updated safely."""


class _PairingState(TypedDict):
    token: str
    paired_origin: str | None
    updated_at: str


class _CaptureHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        db_path: Path,
        pairing_path: Path,
    ) -> None:
        self.db_path = db_path
        self.pairing_path = pairing_path
        super().__init__(server_address, handler_class)


def get_or_create_pairing_token(path: Path) -> str:
    pairing_path = Path(path)
    with _PAIRING_LOCK:
        try:
            if pairing_path.exists():
                state = _read_pairing_state(pairing_path)
                _ensure_pairing_file_permissions(pairing_path)
                return state["token"]

            state = _new_pairing_state()
            _write_pairing_state(pairing_path, state)
            return state["token"]
        except PairingStateError:
            raise
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise PairingStateError("Unable to access local pairing state.") from error


def rotate_pairing_token(path: Path) -> str:
    pairing_path = Path(path)
    with _PAIRING_LOCK:
        state = _new_pairing_state()
        try:
            _write_pairing_state(pairing_path, state)
        except PairingStateError:
            raise
        except (OSError, ValueError, TypeError) as error:
            raise PairingStateError("Unable to update local pairing state.") from error
        return state["token"]


def build_capture_server(
    *,
    host: str,
    port: int,
    db_path: Path,
    pairing_path: Path,
) -> ThreadingHTTPServer:
    if host != "127.0.0.1":
        raise ValueError("CareerOps Capture Bridge must bind to 127.0.0.1.")
    if not 0 <= port <= 65535:
        raise ValueError("Capture Bridge port must be between 0 and 65535.")

    normalized_pairing_path = Path(pairing_path)
    server = _CaptureHTTPServer(
        (host, port),
        _CaptureRequestHandler,
        db_path=Path(db_path),
        pairing_path=normalized_pairing_path,
    )
    try:
        get_or_create_pairing_token(normalized_pairing_path)
    except Exception:
        with suppress(OSError):
            server.server_close()
        raise
    return server


def ensure_capture_bridge_started() -> CaptureBridgeStatus:
    if _is_streamlit_cloud_environment():
        return CaptureBridgeStatus(
            state="hosted_disabled",
            message="Browser Capture is unavailable in the hosted demo.",
            port=CAPTURE_BRIDGE_PORT,
        )
    if os.getenv("CAREEROPS_CAPTURE_ENABLED", "").strip() != "1":
        return CaptureBridgeStatus(
            state="disabled",
            message="Browser Capture is disabled. Start CareerOps with start.bat to enable it.",
            port=CAPTURE_BRIDGE_PORT,
        )

    global _BRIDGE_SERVER, _BRIDGE_STATUS, _BRIDGE_THREAD
    with _BRIDGE_LOCK:
        if _owned_bridge_is_live():
            if _BRIDGE_STATUS is None:
                raise RuntimeError("Process-owned Capture Bridge has no lifecycle status.")
            return _BRIDGE_STATUS
        _clear_dead_bridge_state()

        probe_result = _probe_capture_bridge_port()
        if probe_result == "external_bridge_detected":
            return CaptureBridgeStatus(
                state=probe_result,
                message=(
                    "Another CareerOps process owns the Capture Bridge. Close it or use that process's pairing UI."
                ),
                port=CAPTURE_BRIDGE_PORT,
            )
        if probe_result == "port_conflict":
            return CaptureBridgeStatus(
                state=probe_result,
                message="Port 8765 is used by another application. Close it before enabling Browser Capture.",
                port=CAPTURE_BRIDGE_PORT,
            )

        server: ThreadingHTTPServer | None = None
        try:
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always", RuntimeWarning)
                server = build_capture_server(
                    host=CAPTURE_BRIDGE_HOST,
                    port=CAPTURE_BRIDGE_PORT,
                    db_path=DEFAULT_DB_PATH,
                    pairing_path=DEFAULT_PAIRING_PATH,
                )
            thread = threading.Thread(
                target=server.serve_forever,
                daemon=True,
                name="careerops-capture-bridge",
            )
            thread.start()
        except PairingStateError:
            return CaptureBridgeStatus(
                state="startup_error",
                message="Capture Bridge could not secure its local pairing state.",
                port=CAPTURE_BRIDGE_PORT,
            )
        except OSError:
            race_probe_result = _probe_capture_bridge_port()
            if race_probe_result == "external_bridge_detected":
                return CaptureBridgeStatus(
                    state=race_probe_result,
                    message=(
                        "Another CareerOps process owns the Capture Bridge. Close it or use that process's pairing UI."
                    ),
                    port=CAPTURE_BRIDGE_PORT,
                )
            return CaptureBridgeStatus(
                state="port_conflict",
                message="Port 8765 is unavailable. Close the application using it and try again.",
                port=CAPTURE_BRIDGE_PORT,
            )
        except RuntimeError:
            if server is not None:
                with suppress(OSError):
                    server.server_close()
            return CaptureBridgeStatus(
                state="startup_error",
                message="Capture Bridge could not start.",
                port=CAPTURE_BRIDGE_PORT,
            )

        has_permission_warning = any(issubclass(item.category, RuntimeWarning) for item in caught_warnings)
        state = "running_with_warning" if has_permission_warning else "running"
        message = (
            "Capture Bridge is running, but Windows permissions could not be confirmed."
            if has_permission_warning
            else "Capture Bridge is running."
        )
        _BRIDGE_SERVER = server
        _BRIDGE_THREAD = thread
        _BRIDGE_STATUS = CaptureBridgeStatus(
            state=state,
            message=message,
            port=CAPTURE_BRIDGE_PORT,
        )
        return _BRIDGE_STATUS


def is_local_capture_run() -> bool:
    return not _is_streamlit_cloud_environment()


def get_owned_capture_pairing_token() -> str:
    with _BRIDGE_LOCK:
        pairing_path = _owned_bridge_pairing_path()
        return get_or_create_pairing_token(pairing_path)


def rotate_owned_capture_pairing_token() -> str:
    with _BRIDGE_LOCK:
        pairing_path = _owned_bridge_pairing_path()
        return rotate_pairing_token(pairing_path)


def _owned_bridge_pairing_path() -> Path:
    if not _owned_bridge_is_live() or _BRIDGE_SERVER is None:
        raise RuntimeError("Pairing controls require a process-owned Capture Bridge.")
    pairing_path = getattr(_BRIDGE_SERVER, "pairing_path", None)
    if not isinstance(pairing_path, Path):
        raise RuntimeError("Process-owned Capture Bridge has no pairing state.")
    return pairing_path


def _owned_bridge_is_live() -> bool:
    return _BRIDGE_SERVER is not None and _BRIDGE_THREAD is not None and _BRIDGE_THREAD.is_alive()


def _clear_dead_bridge_state() -> None:
    global _BRIDGE_SERVER, _BRIDGE_STATUS, _BRIDGE_THREAD
    if _BRIDGE_SERVER is not None:
        with suppress(OSError):
            _BRIDGE_SERVER.server_close()
    _BRIDGE_SERVER = None
    _BRIDGE_THREAD = None
    _BRIDGE_STATUS = None


def _probe_capture_bridge_port() -> _BridgeProbeResult:
    connection = http.client.HTTPConnection(
        CAPTURE_BRIDGE_HOST,
        CAPTURE_BRIDGE_PORT,
        timeout=0.5,
    )
    try:
        connection.request("GET", HEALTH_PATH)
        response = connection.getresponse()
        body = response.read(4097)
    except ConnectionRefusedError:
        return "available"
    except TimeoutError:
        return "available" if _capture_bridge_port_is_bindable() else "port_conflict"
    except http.client.HTTPException:
        return "port_conflict"
    except OSError as error:
        if getattr(error, "winerror", None) == 10061 or error.errno in {61, 111}:
            return "available"
        return "available" if _capture_bridge_port_is_bindable() else "port_conflict"
    finally:
        connection.close()

    if response.status != 200 or len(body) > 4096:
        return "port_conflict"
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return "port_conflict"
    if payload == {
        "service": SERVICE_NAME,
        "api_version": API_VERSION,
        "status": "ok",
    }:
        return "external_bridge_detected"
    return "port_conflict"


def _capture_bridge_port_is_bindable() -> bool:
    # Some Windows setups time out when connecting to an unused loopback port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        try:
            candidate.bind((CAPTURE_BRIDGE_HOST, CAPTURE_BRIDGE_PORT))
        except OSError:
            return False
    return True


def _is_streamlit_cloud_environment() -> bool:
    sharing_mode = os.getenv("STREAMLIT_SHARING_MODE", "").strip().lower()
    cloud_flag = os.getenv("STREAMLIT_CLOUD", "").strip().lower()
    return sharing_mode in {"cloud", "streamlit"} or cloud_flag in {"1", "true", "yes"}


def _reset_capture_bridge_for_tests() -> None:
    global _BRIDGE_SERVER, _BRIDGE_STATUS, _BRIDGE_THREAD
    with _BRIDGE_LOCK:
        server = _BRIDGE_SERVER
        thread = _BRIDGE_THREAD
        _BRIDGE_SERVER = None
        _BRIDGE_THREAD = None
        _BRIDGE_STATUS = None
    if server is not None:
        with suppress(OSError):
            server.shutdown()
        with suppress(OSError):
            server.server_close()
    if thread is not None:
        thread.join(timeout=3)


def _new_pairing_state() -> _PairingState:
    return {
        "token": secrets.token_urlsafe(32),
        "paired_origin": None,
        "updated_at": datetime.now(UTC).isoformat(),
    }


def _read_pairing_state(path: Path) -> _PairingState:
    try:
        raw_state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PairingStateError("Unable to read local pairing state.") from error

    if not isinstance(raw_state, dict) or set(raw_state) != {
        "token",
        "paired_origin",
        "updated_at",
    }:
        raise PairingStateError("Local pairing state is invalid.")

    token = raw_state.get("token")
    paired_origin = raw_state.get("paired_origin")
    updated_at = raw_state.get("updated_at")
    if not _is_valid_pairing_token(token):
        raise PairingStateError("Local pairing state is invalid.")
    if paired_origin is not None and not _is_canonical_extension_origin(paired_origin):
        raise PairingStateError("Local pairing state is invalid.")
    if not _is_valid_pairing_timestamp(updated_at):
        raise PairingStateError("Local pairing state is invalid.")

    return {
        "token": cast(str, token),
        "paired_origin": cast(str | None, paired_origin),
        "updated_at": cast(str, updated_at),
    }


def _write_pairing_state(path: Path, state: _PairingState) -> None:
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(
            state,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary_file:
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_path = Path(temporary_file.name)

        _ensure_pairing_file_permissions(temporary_path)
        temporary_path.replace(path)
        temporary_path = None
    except (OSError, UnicodeError, TypeError, ValueError) as error:
        raise PairingStateError("Unable to update local pairing state.") from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def _restrict_pairing_file_permissions(path: Path) -> bool:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        if _is_windows_platform():
            return False
        return stat.S_IMODE(path.stat().st_mode) == (stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        return False


def _ensure_pairing_file_permissions(path: Path) -> None:
    if _restrict_pairing_file_permissions(path):
        return
    if _is_windows_platform():
        warnings.warn(
            "Current-user-only permissions for local pairing state could not be confirmed.",
            RuntimeWarning,
            stacklevel=2,
        )
        return
    raise PairingStateError("Unable to secure local pairing state permissions.")


def _is_valid_pairing_token(token: object) -> bool:
    if not isinstance(token, str) or _PAIRING_TOKEN_PATTERN.fullmatch(token) is None:
        return False
    padded_token = token + ("=" * (-len(token) % 4))
    try:
        decoded = base64.b64decode(padded_token, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError):
        return False
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    return len(decoded) >= 32 and canonical == token


def _is_valid_pairing_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _is_windows_platform() -> bool:
    return os.name == "nt"


def _is_canonical_extension_origin(origin: object) -> bool:
    return isinstance(origin, str) and _EXTENSION_ORIGIN_PATTERN.fullmatch(origin) is not None


def _paired_origin(path: Path) -> str | None:
    with _PAIRING_LOCK:
        return cast(str | None, _read_pairing_state(path)["paired_origin"])


def _supplied_bearer_token(authorization: str | None) -> str:
    if authorization is None or not authorization.startswith("Bearer "):
        return ""
    return authorization.removeprefix("Bearer ")


def _authenticate(path: Path, authorization: str | None) -> bool:
    supplied_token = _supplied_bearer_token(authorization)
    with _PAIRING_LOCK:
        state = _read_pairing_state(path)
        return secrets.compare_digest(state["token"], supplied_token)


def _authenticate_and_confirm_pairing(
    path: Path,
    origin: str,
    authorization: str | None,
) -> _AuthorizationDecision:
    supplied_token = _supplied_bearer_token(authorization)
    with _PAIRING_LOCK:
        state = _read_pairing_state(path)
        if not secrets.compare_digest(state["token"], supplied_token):
            return "unauthorized"
        if state["paired_origin"] not in {None, origin}:
            return "forbidden"
        if state["paired_origin"] is None:
            state["paired_origin"] = origin
            state["updated_at"] = datetime.now(UTC).isoformat()
            _write_pairing_state(path, state)
        return "authorized"


def _authorize_paired_request(
    path: Path,
    origin: str,
    authorization: str | None,
) -> _AuthorizationDecision:
    with _PAIRING_LOCK:
        state = _read_pairing_state(path)
        return _authorize_paired_state(state, origin, authorization)


def _authorize_paired_state(
    state: _PairingState,
    origin: str,
    authorization: str | None,
) -> _AuthorizationDecision:
    if state["paired_origin"] != origin:
        return "forbidden"
    supplied_token = _supplied_bearer_token(authorization)
    if not secrets.compare_digest(state["token"], supplied_token):
        return "unauthorized"
    return "authorized"


def _is_sqlite_busy_error(error: sqlite3.OperationalError) -> bool:
    error_code = getattr(error, "sqlite_errorcode", None)
    if not isinstance(error_code, int):
        return False
    primary_error_code = error_code & 0xFF
    return primary_error_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


class _CaptureRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "CareerOpsCaptureBridge"
    sys_version = ""

    def do_GET(self) -> None:
        self._handle_safely(self._dispatch_get)

    def do_POST(self) -> None:
        self._handle_safely(self._dispatch_post)

    def do_OPTIONS(self) -> None:
        self._handle_safely(self._dispatch_options)

    def do_HEAD(self) -> None:
        self._handle_safely(self._dispatch_unsupported_method)

    def do_PUT(self) -> None:
        self._handle_safely(self._dispatch_unsupported_method)

    def do_PATCH(self) -> None:
        self._handle_safely(self._dispatch_unsupported_method)

    def do_DELETE(self) -> None:
        self._handle_safely(self._dispatch_unsupported_method)

    def do_TRACE(self) -> None:
        self._handle_safely(self._dispatch_unsupported_method)

    def do_CONNECT(self) -> None:
        self._handle_safely(self._dispatch_unsupported_method)

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        self.close_connection = True
        if code == 501 and getattr(self, "path", None):
            self._handle_safely(self._dispatch_unsupported_method)
            return
        super().send_error(code, message, explain)

    def log_message(self, _format: str, *args: object) -> None:
        del args

    def log_error(self, _format: str, *args: object) -> None:
        del args

    @property
    def _capture_server(self) -> _CaptureHTTPServer:
        return cast(_CaptureHTTPServer, self.server)

    @property
    def _request_origin(self) -> str | None:
        return self.headers.get("Origin")

    def _handle_safely(self, handler: Callable[[], None]) -> None:
        try:
            handler()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            try:
                self._send_error(
                    500,
                    "internal_error",
                    "The local Capture Bridge could not complete the request.",
                    cors_origin=self._cors_origin_for_error(),
                )
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                self.close_connection = True

    def _dispatch_get(self) -> None:
        if self.path not in _KNOWN_PATHS:
            self._send_route_not_found()
            return
        if self.path != HEALTH_PATH:
            self._send_method_not_allowed()
            return

        origin = self._request_origin
        cors_origin = origin if _is_canonical_extension_origin(origin) else None
        self._send_json(
            200,
            {
                "service": SERVICE_NAME,
                "api_version": API_VERSION,
                "status": "ok",
            },
            cors_origin=cors_origin,
        )

    def _dispatch_post(self) -> None:
        self.close_connection = True
        if self.path not in _KNOWN_PATHS:
            self._send_route_not_found()
            return
        if self.path not in _POST_PATHS:
            self._send_method_not_allowed()
            return
        if not self._validate_api_version():
            return
        if not self._validate_content_type():
            return

        body_length = self._validated_content_length()
        if body_length is None:
            return

        origin = self._request_origin
        authorization_header = self.headers.get("Authorization")
        if self.path == PAIR_PATH:
            if not _is_canonical_extension_origin(origin):
                self._send_forbidden_origin()
                return
            cors_origin = cast(str, origin)
            if not _authenticate(
                self._capture_server.pairing_path,
                authorization_header,
            ):
                self._send_unauthorized(cors_origin=cors_origin)
                return
        else:
            if not _is_canonical_extension_origin(origin):
                self._send_forbidden_origin()
                return
            cors_origin = cast(str, origin)
            if not self._authorize_existing_pair(cors_origin, authorization_header):
                return

        payload = self._read_json_body(body_length, cors_origin=cors_origin)
        if payload is None:
            return

        if self.path == PAIR_PATH:
            self._handle_pair_confirmation(
                payload,
                cors_origin,
                authorization_header,
            )
        elif self.path == PREVIEW_PATH:
            self._handle_preview(payload, cors_origin, authorization_header)
        else:
            self._handle_save(payload, cors_origin, authorization_header)

    def _dispatch_options(self) -> None:
        if self.path not in _POST_PATHS:
            if self.path in _KNOWN_PATHS:
                self._send_method_not_allowed()
            else:
                self._send_route_not_found()
            return

        requested_method = self.headers.get("Access-Control-Request-Method")
        if requested_method != "POST":
            self._send_method_not_allowed()
            return

        requested_headers = self.headers.get("Access-Control-Request-Headers")
        parsed_headers = (
            {header.strip().lower() for header in requested_headers.split(",") if header.strip()}
            if requested_headers is not None
            else set()
        )
        if parsed_headers != _ALLOWED_CORS_HEADER_NAMES:
            self._send_error(
                400,
                "invalid_cors_request",
                "The CORS preflight request is not supported.",
                cors_origin=self._cors_origin_for_error(),
            )
            return

        origin = self._request_origin
        if self.path == PAIR_PATH:
            if not _is_canonical_extension_origin(origin):
                self._send_forbidden_origin()
                return
        elif not self._is_paired_request_origin(origin):
            self._send_forbidden_origin()
            return

        self._send_json(
            204,
            None,
            cors_origin=cast(str, origin),
            include_preflight_headers=True,
        )

    def _dispatch_unsupported_method(self) -> None:
        self.close_connection = True
        if self.path not in _KNOWN_PATHS:
            self._send_route_not_found()
        else:
            self._send_method_not_allowed()

    def _authorize_existing_pair(
        self,
        cors_origin: str,
        authorization_header: str | None,
    ) -> bool:
        authorization = _authorize_paired_request(
            self._capture_server.pairing_path,
            cors_origin,
            authorization_header,
        )
        if authorization == "forbidden":
            self._send_forbidden_origin()
            return False
        if authorization == "unauthorized":
            self._send_unauthorized(cors_origin=cors_origin)
            return False
        return True

    def _validate_api_version(self) -> bool:
        if self.headers.get("X-CareerOps-API-Version") != API_VERSION:
            self._send_error(
                400,
                "unsupported_api_version",
                "X-CareerOps-API-Version must be 1.",
                cors_origin=self._cors_origin_for_error(),
            )
            return False
        return True

    def _validate_content_type(self) -> bool:
        raw_content_type = self.headers.get("Content-Type")
        if raw_content_type is None:
            self._send_unsupported_media_type()
            return False

        parts = [part.strip().lower() for part in raw_content_type.split(";")]
        supported = parts == ["application/json"] or parts == [
            "application/json",
            "charset=utf-8",
        ]
        if not supported:
            self._send_unsupported_media_type()
            return False
        return True

    def _validated_content_length(self) -> int | None:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None or not raw_length.isascii() or not raw_length.isdigit():
            self.close_connection = True
            self._send_error(
                400,
                "invalid_content_length",
                "A valid Content-Length header is required.",
                cors_origin=self._cors_origin_for_error(),
            )
            return None

        length = int(raw_length)
        if length > MAX_REQUEST_BYTES:
            self.close_connection = True
            self._send_error(
                413,
                "request_too_large",
                "The JSON request body exceeds the 256 KiB limit.",
                cors_origin=self._cors_origin_for_error(),
            )
            return None
        return length

    def _read_json_body(
        self,
        body_length: int,
        *,
        cors_origin: str,
    ) -> object | None:
        raw_body = self.rfile.read(body_length)
        if len(raw_body) != body_length:
            self.close_connection = True
            self._send_error(
                400,
                "invalid_content_length",
                "The request body does not match Content-Length.",
                cors_origin=cors_origin,
            )
            return None

        try:
            decoded = raw_body.decode("utf-8")
            if not decoded:
                raise ValueError
            parsed: object = json.loads(decoded)
            return parsed
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._send_error(
                400,
                "invalid_json",
                "The request body must contain valid UTF-8 JSON.",
                cors_origin=cors_origin,
            )
            return None

    def _handle_pair_confirmation(
        self,
        payload: object,
        cors_origin: str,
        authorization_header: str | None,
    ) -> None:
        if not isinstance(payload, dict) or payload:
            self._send_error(
                422,
                "validation_error",
                "Pair confirmation requires an empty JSON object.",
                cors_origin=cors_origin,
            )
            return
        authorization = _authenticate_and_confirm_pairing(
            self._capture_server.pairing_path,
            cors_origin,
            authorization_header,
        )
        if authorization == "unauthorized":
            self._send_unauthorized(cors_origin=cors_origin)
            return
        if authorization == "forbidden":
            self._send_forbidden_origin(cors_origin=cors_origin)
            return
        self._send_json(200, {"paired": True}, cors_origin=cors_origin)

    def _run_authorized_capture_service(
        self,
        payload: object,
        cors_origin: str,
        authorization_header: str | None,
        service: Callable[[object, Path], dict[str, Any]],
    ) -> tuple[_AuthorizationDecision, dict[str, Any] | None]:
        with _PAIRING_LOCK:
            state = _read_pairing_state(self._capture_server.pairing_path)
            authorization = _authorize_paired_state(
                state,
                cors_origin,
                authorization_header,
            )
            if authorization != "authorized":
                return authorization, None
            return authorization, service(payload, self._capture_server.db_path)

    def _handle_preview(
        self,
        payload: object,
        cors_origin: str,
        authorization_header: str | None,
    ) -> None:
        try:
            authorization, result = self._run_authorized_capture_service(
                payload,
                cors_origin,
                authorization_header,
                preview_capture,
            )
        except CaptureValidationError as error:
            self._send_validation_error(error, cors_origin)
            return
        except CaptureConflictError as error:
            self._send_conflict_error(error, cors_origin)
            return
        except CaptureNotFoundError as error:
            self._send_not_found_error(error, cors_origin)
            return
        except CaptureDatabaseBusyError:
            self._send_database_busy(cors_origin)
            return
        except sqlite3.OperationalError as error:
            if _is_sqlite_busy_error(error):
                self._send_database_busy(cors_origin)
                return
            raise
        if authorization == "forbidden":
            self._send_forbidden_origin()
            return
        if authorization == "unauthorized":
            self._send_unauthorized(cors_origin=cors_origin)
            return
        if result is None:
            raise RuntimeError("Authorized capture preview returned no result.")
        self._send_json(200, result, cors_origin=cors_origin)

    def _handle_save(
        self,
        payload: object,
        cors_origin: str,
        authorization_header: str | None,
    ) -> None:
        try:
            authorization, result = self._run_authorized_capture_service(
                payload,
                cors_origin,
                authorization_header,
                save_capture,
            )
        except CaptureValidationError as error:
            self._send_validation_error(error, cors_origin)
            return
        except CaptureConflictError as error:
            self._send_conflict_error(error, cors_origin)
            return
        except CaptureNotFoundError as error:
            self._send_not_found_error(error, cors_origin)
            return
        except CaptureDatabaseBusyError:
            self._send_database_busy(cors_origin)
            return
        except sqlite3.OperationalError as error:
            if _is_sqlite_busy_error(error):
                self._send_database_busy(cors_origin)
                return
            raise

        if authorization == "forbidden":
            self._send_forbidden_origin()
            return
        if authorization == "unauthorized":
            self._send_unauthorized(cors_origin=cors_origin)
            return
        if result is None:
            raise RuntimeError("Authorized capture save returned no result.")
        status = 200 if bool(result.get("replayed")) else 201
        self._send_json(status, result, cors_origin=cors_origin)

    def _send_validation_error(
        self,
        error: CaptureValidationError,
        cors_origin: str,
    ) -> None:
        self._send_error(
            422,
            "validation_error",
            error.message,
            field=error.field,
            cors_origin=cors_origin,
        )

    def _send_conflict_error(
        self,
        error: CaptureConflictError,
        cors_origin: str,
    ) -> None:
        if error.code not in _ALLOWED_CONFLICT_CODES:
            raise error
        self._send_error(
            409,
            error.code,
            "The request conflicts with current CareerOps data.",
            details=error.details,
            cors_origin=cors_origin,
        )

    def _send_not_found_error(
        self,
        error: CaptureNotFoundError,
        cors_origin: str,
    ) -> None:
        if error.code not in _ALLOWED_NOT_FOUND_CODES:
            raise error
        self._send_error(
            404,
            error.code,
            "The selected application no longer exists.",
            cors_origin=cors_origin,
        )

    def _send_database_busy(self, cors_origin: str) -> None:
        self._send_error(
            503,
            "database_busy",
            "The CareerOps database is busy. Retry this request.",
            retryable=True,
            cors_origin=cors_origin,
        )

    def _is_paired_request_origin(self, origin: object) -> bool:
        if not _is_canonical_extension_origin(origin):
            return False
        return _paired_origin(self._capture_server.pairing_path) == origin

    def _cors_origin_for_error(self) -> str | None:
        origin = self._request_origin
        if not _is_canonical_extension_origin(origin):
            return None
        if self.path == PAIR_PATH:
            return cast(str, origin)
        if self.path in {PREVIEW_PATH, APPLICATIONS_PATH}:
            try:
                if _paired_origin(self._capture_server.pairing_path) == origin:
                    return cast(str, origin)
            except PairingStateError:
                return None
        return None

    def _send_unauthorized(self, *, cors_origin: str | None = None) -> None:
        self._send_error(
            401,
            "unauthorized",
            "Valid local pairing authentication is required.",
            cors_origin=cors_origin,
        )

    def _send_forbidden_origin(self, *, cors_origin: str | None = None) -> None:
        self._send_error(
            403,
            "forbidden_origin",
            "This extension origin is not paired with CareerOps.",
            cors_origin=cors_origin,
        )

    def _send_unsupported_media_type(self) -> None:
        self._send_error(
            415,
            "unsupported_media_type",
            "Content-Type must be application/json with optional UTF-8 charset.",
            cors_origin=self._cors_origin_for_error(),
        )

    def _send_route_not_found(self) -> None:
        self._send_error(
            404,
            "route_not_found",
            "The requested Capture Bridge route does not exist.",
        )

    def _send_method_not_allowed(self) -> None:
        allow_methods = "GET" if self.path == HEALTH_PATH else _ALLOWED_CORS_METHODS
        self._send_error(
            405,
            "method_not_allowed",
            "The HTTP method is not allowed for this route.",
            cors_origin=self._cors_origin_for_error(),
            allow_methods=allow_methods,
        )

    def _send_error(
        self,
        status: int,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        field: str | None = None,
        details: dict[str, Any] | None = None,
        cors_origin: str | None = None,
        allow_methods: str | None = None,
    ) -> None:
        self._send_json(
            status,
            {
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                    "field": field,
                    "details": details or {},
                }
            },
            cors_origin=cors_origin,
            allow_methods=allow_methods,
        )

    def _send_json(
        self,
        status: int,
        payload: object | None,
        *,
        cors_origin: str | None = None,
        include_preflight_headers: bool = False,
        allow_methods: str | None = None,
    ) -> None:
        response_body = (
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if payload is not None
            else b""
        )
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(response_body)))
        if self.close_connection:
            self.send_header("Connection", "close")
        if payload is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        if cors_origin is not None:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
            self.send_header("Vary", "Origin")
        if include_preflight_headers:
            self.send_header("Access-Control-Allow-Methods", _ALLOWED_CORS_METHODS)
            self.send_header("Access-Control-Allow-Headers", _ALLOWED_CORS_HEADERS)
        if allow_methods is not None:
            self.send_header("Allow", allow_methods)
        self.end_headers()
        if response_body and self.command != "HEAD":
            self.wfile.write(response_body)
