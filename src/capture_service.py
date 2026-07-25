from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from src.database import (
    DEFAULT_DB_PATH,
    _create_application_in_transaction,
    _update_application_in_transaction,
    get_applications,
    get_connection,
)
from src.duplicates import (
    COMPANY_NOISE_WORDS,
    ROLE_NOISE_WORDS,
    find_likely_duplicate_applications,
)
from src.models import (
    APPLICATION_COLUMNS,
    LEGACY_STATUS_MAP,
    STATUS_KEYWORD_MAP,
    STATUS_OPTIONS,
    apply_status_business_rules,
    normalize_status,
)

CAPTURE_FIELD_ORDER = (
    "company",
    "role",
    "location",
    "application_date",
    "status",
    "source_link",
    "notes",
)
CAPTURE_FIELDS = frozenset(CAPTURE_FIELD_ORDER)
EDITABLE_FIELDS = CAPTURE_FIELDS
RESOLUTIONS = frozenset({"none", "create_anyway", "use_existing"})
CONFIRMED_FIELDS = CAPTURE_FIELDS | {
    "client_request_id",
    "duplicate_resolution",
    "existing_application_id",
    "edited_fields",
}
FIELD_LIMITS = {
    "company": 200,
    "role": 300,
    "location": 300,
    "source_link": 2_000,
    "notes": 4_000,
}
CAPTURE_SOURCE = "chrome_capture"
LOCAL_APPLICATION_URL = "http://localhost:8501/?workspace=Applications&application_id={application_id}"


class CaptureValidationError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(message)


class CaptureConflictError(RuntimeError):
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


class CaptureNotFoundError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CaptureDatabaseBusyError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("CareerOps database is busy.")


def validate_preview_payload(payload: object) -> dict[str, Any]:
    request = _require_request_object(payload)
    _reject_unknown_fields(request, CAPTURE_FIELDS)
    return _validate_application_fields(request)


def validate_confirmed_payload(payload: object) -> dict[str, Any]:
    request = _require_request_object(payload)
    _reject_unknown_fields(request, CONFIRMED_FIELDS)
    cleaned = _validate_application_fields(request)

    client_request_id = request.get("client_request_id")
    if not isinstance(client_request_id, str):
        raise CaptureValidationError("client_request_id", "A UUID v4 client_request_id is required.")
    try:
        parsed_request_id = UUID(client_request_id)
    except ValueError as error:
        raise CaptureValidationError("client_request_id", "client_request_id must be a UUID v4.") from error
    if parsed_request_id.version != 4:
        raise CaptureValidationError("client_request_id", "client_request_id must be a UUID v4.")

    resolution = request.get("duplicate_resolution")
    if not isinstance(resolution, str) or resolution not in RESOLUTIONS:
        raise CaptureValidationError(
            "duplicate_resolution",
            "duplicate_resolution must be none, create_anyway, or use_existing.",
        )

    existing_application_id = request.get("existing_application_id")
    if existing_application_id is not None and (
        isinstance(existing_application_id, bool)
        or not isinstance(existing_application_id, int)
        or existing_application_id <= 0
    ):
        raise CaptureValidationError(
            "existing_application_id",
            "existing_application_id must be a positive integer.",
        )
    if resolution == "use_existing" and existing_application_id is None:
        raise CaptureValidationError(
            "existing_application_id",
            "existing_application_id is required for use_existing.",
        )

    edited_fields = _validate_edited_fields(request.get("edited_fields", []))
    cleaned.update(
        {
            "client_request_id": str(parsed_request_id),
            "duplicate_resolution": resolution,
            "existing_application_id": existing_application_id,
            "edited_fields": edited_fields,
        }
    )
    return cleaned


def preview_capture(
    payload: object,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    cleaned = validate_preview_payload(payload)
    candidates = _duplicate_candidates(
        cleaned,
        get_applications(db_path),
        limit=3,
    )
    return {
        "normalized": cleaned,
        "duplicates": [_serialize_duplicate(candidate) for candidate in candidates],
    }


def save_capture(
    payload: object,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    cleaned = validate_confirmed_payload(payload)
    payload_sha256 = _canonical_payload_hash(cleaned)

    try:
        with get_connection(db_path) as connection:
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("BEGIN IMMEDIATE")
            try:
                replay = _idempotency_result(
                    connection,
                    client_request_id=cleaned["client_request_id"],
                    payload_sha256=payload_sha256,
                )
                if replay is not None:
                    connection.rollback()
                    return replay

                resolution = cleaned["duplicate_resolution"]
                if resolution == "use_existing":
                    application_id, result = _update_existing_capture(connection, cleaned)
                else:
                    if resolution == "none":
                        _reject_blocking_duplicate(connection, cleaned)
                    application_id = _create_application_in_transaction(
                        connection,
                        _application_payload(cleaned),
                        CAPTURE_SOURCE,
                    )
                    result = "created"

                _insert_capture_request(
                    connection,
                    client_request_id=cleaned["client_request_id"],
                    payload_sha256=payload_sha256,
                    application_id=application_id,
                    result=result,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
    except sqlite3.OperationalError as error:
        if _is_database_busy_error(error):
            raise CaptureDatabaseBusyError() from error
        raise

    return _save_result(result, application_id, replayed=False)


def _require_request_object(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise CaptureValidationError("payload", "Request payload must be a JSON object.")
    return payload


def _reject_unknown_fields(payload: dict[str, Any], allowed_fields: frozenset[str]) -> None:
    unknown_fields = sorted(str(field) for field in payload if field not in allowed_fields)
    if unknown_fields:
        field = unknown_fields[0]
        raise CaptureValidationError(field, f"Unknown request field: {field}.")


def _validate_application_fields(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, str] = {}
    for field in CAPTURE_FIELD_ORDER:
        value = payload.get(field, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise CaptureValidationError(field, f"{field} must be a string.")
        if field == "source_link" and _contains_control_character(value):
            raise CaptureValidationError(
                "source_link",
                "source_link must not contain control characters.",
            )
        cleaned[field] = value.strip()

    for field in ("company", "role"):
        if not cleaned[field]:
            raise CaptureValidationError(field, f"{field} is required.")

    for field, limit in FIELD_LIMITS.items():
        if len(cleaned[field]) > limit:
            raise CaptureValidationError(field, f"{field} must be at most {limit} characters.")

    application_date = cleaned["application_date"]
    if application_date:
        try:
            parsed_date = date.fromisoformat(application_date)
        except ValueError as error:
            raise CaptureValidationError(
                "application_date",
                "application_date must use ISO YYYY-MM-DD.",
            ) from error
        if parsed_date.isoformat() != application_date:
            raise CaptureValidationError(
                "application_date",
                "application_date must use ISO YYYY-MM-DD.",
            )

    cleaned["status"] = _validated_status(cleaned["status"])
    _validate_source_link(cleaned["source_link"])
    cleaned["next_action"] = ""
    cleaned["follow_up_date"] = ""
    return apply_status_business_rules(cleaned)


def _validated_status(value: str) -> str:
    if not value:
        return "Applied"
    if value in STATUS_OPTIONS or value in LEGACY_STATUS_MAP:
        return normalize_status(value)

    normalized_value = _normalize_status_text(value)
    known_exact_values = [*STATUS_OPTIONS, *LEGACY_STATUS_MAP]
    if any(normalized_value == _normalize_status_text(candidate) for candidate in known_exact_values):
        return normalize_status(value)
    for mapped_status, keywords in STATUS_KEYWORD_MAP.items():
        if any(_status_keyword_matches(normalized_value, keyword) for keyword in keywords):
            return mapped_status
    raise CaptureValidationError("status", "Unknown CareerOps status.")


def _normalize_status_text(value: object) -> str:
    return " ".join(str(value or "").casefold().replace("_", " ").replace("-", " ").split())


def _status_keyword_matches(normalized_value: str, keyword: str) -> bool:
    normalized_keyword = _normalize_status_text(keyword)
    if not normalized_keyword:
        return False
    value_tokens = re.findall(r"[^\W_]+", normalized_value)
    keyword_tokens = re.findall(r"[^\W_]+", normalized_keyword)
    keyword_length = len(keyword_tokens)
    return any(
        value_tokens[index : index + keyword_length] == keyword_tokens
        for index in range(len(value_tokens) - keyword_length + 1)
    )


def _validate_source_link(value: str) -> None:
    if not value:
        return
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as error:
        raise CaptureValidationError(
            "source_link",
            "source_link must be an http or https URL.",
        ) from error
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or any(character.isspace() or _is_control_character(character) for character in hostname)
    ):
        raise CaptureValidationError("source_link", "source_link must be an http or https URL.")


def _contains_control_character(value: str) -> bool:
    return any(_is_control_character(character) for character in value)


def _is_control_character(character: str) -> bool:
    codepoint = ord(character)
    return codepoint < 32 or codepoint == 127


def _validate_edited_fields(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(field, str) for field in value):
        raise CaptureValidationError("edited_fields", "edited_fields must be an array of strings.")
    unknown_fields = sorted({field for field in value if field not in EDITABLE_FIELDS})
    if unknown_fields:
        raise CaptureValidationError(
            "edited_fields",
            f"Unknown edited field: {unknown_fields[0]}.",
        )
    return sorted(set(value))


def _serialize_duplicate(candidate: dict[str, Any]) -> dict[str, Any]:
    application = candidate["application"]
    return {
        "application_id": int(application["id"]),
        "company": str(application.get("company", "") or ""),
        "role": str(application.get("role", "") or ""),
        "score": round(float(candidate.get("score", 0.0)), 6),
        "reason": str(candidate.get("reason", "") or ""),
    }


def _canonical_payload_hash(payload: dict[str, Any]) -> str:
    canonical = {
        "application": {
            **{field: str(payload.get(field, "") or "") for field in CAPTURE_FIELD_ORDER},
            "next_action": str(payload.get("next_action", "") or ""),
            "follow_up_date": str(payload.get("follow_up_date", "") or ""),
        },
        "duplicate_resolution": payload["duplicate_resolution"],
        "existing_application_id": payload.get("existing_application_id"),
        "edited_fields": sorted(set(payload.get("edited_fields", []))),
    }
    serialized = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _idempotency_result(
    connection: sqlite3.Connection,
    *,
    client_request_id: str,
    payload_sha256: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT payload_sha256, application_id, result
        FROM capture_requests
        WHERE client_request_id = ?
        """,
        (client_request_id,),
    ).fetchone()
    if row is None:
        return None
    if str(row["payload_sha256"]) != payload_sha256:
        raise CaptureConflictError(
            "idempotency_conflict",
            {"client_request_id": client_request_id},
        )
    return _save_result(
        str(row["result"]),
        int(row["application_id"]),
        replayed=True,
    )


def _update_existing_capture(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
) -> tuple[int, str]:
    application_id = int(payload["existing_application_id"])
    applications = _get_applications(connection)
    existing = next(
        (application for application in applications if int(application["id"]) == application_id),
        None,
    )
    if existing is None:
        raise CaptureNotFoundError("existing_application_not_found")

    candidates = _duplicate_candidates(
        payload,
        applications,
        limit=max(3, len(applications)),
    )
    candidate_ids = {int(candidate["application"]["id"]) for candidate in candidates}
    if application_id not in candidate_ids:
        latest_candidates = _duplicate_candidates(payload, applications, limit=3)
        raise CaptureConflictError(
            "duplicate_conflict",
            {"duplicates": [_serialize_duplicate(candidate) for candidate in latest_candidates]},
        )

    merged = _merge_existing_application(existing, payload)
    _update_application_in_transaction(
        connection,
        application_id,
        merged,
        CAPTURE_SOURCE,
    )
    return application_id, "updated"


def _reject_blocking_duplicate(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
) -> None:
    applications = _get_applications(connection)
    candidates = _duplicate_candidates(payload, applications, limit=3)
    if not candidates:
        return

    serialized = [_serialize_duplicate(candidate) for candidate in candidates]
    raise CaptureConflictError("duplicate_conflict", {"duplicates": serialized})


def _duplicate_candidates(
    payload: dict[str, Any],
    applications: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    likely_candidates = find_likely_duplicate_applications(
        payload,
        applications,
        limit=max(limit, len(applications)),
    )
    candidates_by_id = {int(candidate["application"]["id"]): candidate for candidate in likely_candidates}
    exact_ids: set[int] = set()
    for application in applications:
        if not _is_exact_normalized_duplicate(payload, application):
            continue
        application_id = int(application["id"])
        exact_ids.add(application_id)
        candidates_by_id.setdefault(
            application_id,
            {
                "application": application,
                "score": 1.0,
                "reason": "exact normalized company, role, and source match",
            },
        )

    prioritized = sorted(
        candidates_by_id.values(),
        key=lambda candidate: (
            int(candidate["application"]["id"]) not in exact_ids,
            -float(candidate.get("score", 0.0)),
            int(candidate["application"]["id"]),
        ),
    )
    return prioritized[:limit]


def _get_applications(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM applications
        ORDER BY id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _is_exact_normalized_duplicate(
    incoming: dict[str, Any],
    existing: dict[str, Any],
) -> bool:
    return (
        _normalize_company(incoming.get("company")) == _normalize_company(existing.get("company"))
        and _normalize_role(incoming.get("role")) == _normalize_role(existing.get("role"))
        and _normalize_source(incoming.get("source_link")) == _normalize_source(existing.get("source_link"))
    )


def _normalize_company(value: object) -> str:
    tokens = _tokens(value)
    return " ".join(token.rstrip("s") for token in tokens if token not in COMPANY_NOISE_WORDS)


def _normalize_role(value: object) -> str:
    return " ".join(token for token in _tokens(value) if token not in ROLE_NOISE_WORDS)


def _tokens(value: object) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(value or "").casefold())


def _normalize_source(value: object) -> str:
    source = str(value or "").strip()
    if not source:
        return ""
    parsed = urlsplit(source)
    path = parsed.path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            path,
            parsed.query,
            "",
        )
    )


def _merge_existing_application(
    existing: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, str]:
    merged = {column: str(existing.get(column, "") or "").strip() for column in APPLICATION_COLUMNS}
    edited_fields = set(incoming.get("edited_fields", []))

    for field in ("company", "role", "location", "source_link", "application_date"):
        incoming_value = str(incoming.get(field, "") or "").strip()
        if field in edited_fields or not merged[field]:
            merged[field] = incoming_value

    incoming_status = str(incoming.get("status", "") or "").strip()
    if "status" in edited_fields or not merged["status"]:
        merged["status"] = incoming_status

    merged["notes"] = _append_unique_note(
        merged["notes"],
        str(incoming.get("notes", "") or "").strip(),
    )
    return apply_status_business_rules(merged)


def _append_unique_note(existing: str, incoming: str) -> str:
    if not incoming:
        return existing
    if not existing:
        return incoming

    existing_normalized = {_normalize_note(part) for part in re.split(r"\n\s*\n", existing) if part.strip()}
    unique_incoming: list[str] = []
    for part in re.split(r"\n\s*\n", incoming):
        cleaned_part = part.strip()
        normalized_part = _normalize_note(cleaned_part)
        if not cleaned_part or normalized_part in existing_normalized:
            continue
        existing_normalized.add(normalized_part)
        unique_incoming.append(cleaned_part)

    if not unique_incoming:
        return existing
    return f"{existing.rstrip()}\n\n{'\n\n'.join(unique_incoming)}"


def _normalize_note(value: str) -> str:
    return " ".join(value.split())


def _application_payload(payload: dict[str, Any]) -> dict[str, str]:
    return {column: str(payload.get(column, "") or "").strip() for column in APPLICATION_COLUMNS}


def _insert_capture_request(
    connection: sqlite3.Connection,
    *,
    client_request_id: str,
    payload_sha256: str,
    application_id: int,
    result: str,
) -> None:
    connection.execute(
        """
        INSERT INTO capture_requests (
            client_request_id,
            payload_sha256,
            application_id,
            result,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            client_request_id,
            payload_sha256,
            application_id,
            result,
            datetime.now(UTC).replace(microsecond=0).isoformat(),
        ),
    )


def _save_result(
    result: str,
    application_id: int,
    *,
    replayed: bool,
) -> dict[str, Any]:
    return {
        "result": result,
        "application_id": application_id,
        "replayed": replayed,
        "open_url": LOCAL_APPLICATION_URL.format(application_id=application_id),
    }


def _is_database_busy_error(error: sqlite3.OperationalError) -> bool:
    message = str(error).casefold()
    return "locked" in message or "busy" in message
