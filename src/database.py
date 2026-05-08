from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.models import APPLICATION_COLUMNS, STATUS_OPTIONS

DEFAULT_DB_PATH = Path("data/applications.db")


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    with get_connection(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                location TEXT,
                application_date TEXT,
                status TEXT NOT NULL DEFAULT 'Applied',
                source_link TEXT,
                contact TEXT,
                notes TEXT,
                rejection_reason TEXT,
                next_action TEXT,
                follow_up_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _ensure_application_columns(connection)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS application_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def create_application(
    payload: dict[str, Any],
    db_path: Path | str = DEFAULT_DB_PATH,
    source: str = "manual",
) -> int:
    cleaned = _clean_payload(payload)
    now = _now()
    columns = APPLICATION_COLUMNS + ["created_at", "updated_at"]
    values = [cleaned.get(column) for column in APPLICATION_COLUMNS] + [now, now]
    placeholders = ", ".join(["?"] * len(columns))

    with get_connection(db_path) as connection:
        cursor = connection.execute(
            f"INSERT INTO applications ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        if cursor.lastrowid is None:
            raise RuntimeError("Failed to create application record.")
        application_id = cursor.lastrowid
        _insert_event(
            connection,
            application_id=application_id,
            event_type="application_created",
            old_value="",
            new_value=_summarize_application(cleaned),
            source=source,
        )
        connection.commit()
        return application_id


def get_applications(db_path: Path | str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM applications
            ORDER BY
                COALESCE(application_date, '') DESC,
                id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def update_application(
    application_id: int,
    payload: dict[str, Any],
    db_path: Path | str = DEFAULT_DB_PATH,
    source: str = "manual",
) -> None:
    cleaned = _clean_payload(payload)
    assignments = ", ".join([f"{column} = ?" for column in APPLICATION_COLUMNS])
    values = [cleaned.get(column) for column in APPLICATION_COLUMNS]
    values.extend([_now(), application_id])

    with get_connection(db_path) as connection:
        existing = _get_application_by_id(connection, application_id)
        connection.execute(
            f"""
            UPDATE applications
            SET {assignments}, updated_at = ?
            WHERE id = ?
            """,
            values,
        )
        if existing is not None:
            for column in APPLICATION_COLUMNS:
                old_value = str(existing.get(column, "") or "").strip()
                new_value = str(cleaned.get(column, "") or "").strip()
                if old_value != new_value:
                    _insert_event(
                        connection,
                        application_id=application_id,
                        event_type=f"{column}_changed",
                        old_value=old_value,
                        new_value=new_value,
                        source=source,
                    )
        connection.commit()


def delete_application(
    application_id: int,
    db_path: Path | str = DEFAULT_DB_PATH,
    source: str = "manual",
) -> None:
    with get_connection(db_path) as connection:
        existing = _get_application_by_id(connection, application_id)
        connection.execute("DELETE FROM applications WHERE id = ?", (application_id,))
        if existing is not None:
            _insert_event(
                connection,
                application_id=application_id,
                event_type="application_deleted",
                old_value=_summarize_application(existing),
                new_value="",
                source=source,
            )
        connection.commit()


def bulk_create_applications(
    rows: list[dict[str, Any]],
    db_path: Path | str = DEFAULT_DB_PATH,
    source: str = "csv_import",
) -> int:
    created = 0
    for row in rows:
        if row.get("company") and row.get("role"):
            create_application(row, db_path=db_path, source=source)
            created += 1
    return created


def sync_applications(
    rows: list[dict[str, Any]],
    db_path: Path | str = DEFAULT_DB_PATH,
    source: str = "csv_import",
) -> dict[str, int]:
    existing_applications = get_applications(db_path)
    exact_index, fallback_index = _build_application_indexes(existing_applications)

    created = 0
    updated = 0
    skipped = 0

    for row in rows:
        cleaned = _clean_payload(row)
        if not cleaned["company"] or not cleaned["role"]:
            skipped += 1
            continue

        existing = _find_existing_application(cleaned, exact_index, fallback_index)
        if existing is None:
            new_id = create_application(cleaned, db_path=db_path, source=source)
            indexed = {**cleaned, "id": new_id}
            _add_to_indexes(indexed, exact_index, fallback_index)
            created += 1
            continue

        merged = _merge_application(existing, cleaned)
        if _has_application_changes(existing, merged):
            update_application(int(existing["id"]), merged, db_path=db_path, source=source)
            updated += 1
        else:
            skipped += 1

    return {"created": created, "updated": updated, "skipped": skipped}


def deduplicate_applications(db_path: Path | str = DEFAULT_DB_PATH) -> int:
    applications = get_applications(db_path)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for application in applications:
        groups.setdefault(_application_exact_key(application), []).append(application)

    removed = 0
    for duplicates in groups.values():
        if len(duplicates) <= 1:
            continue

        keeper = max(duplicates, key=lambda item: (str(item.get("updated_at", "")), int(item["id"])))
        merged = keeper
        for duplicate in duplicates:
            if duplicate["id"] != keeper["id"]:
                merged = _merge_application(merged, duplicate)

        update_application(int(keeper["id"]), merged, db_path=db_path, source="duplicate_cleanup")
        for duplicate in duplicates:
            if duplicate["id"] != keeper["id"]:
                delete_application(int(duplicate["id"]), db_path=db_path, source="duplicate_cleanup")
                removed += 1

    return removed


def get_application_events(
    application_id: int | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    query = """
        SELECT *
        FROM application_events
    """
    params: tuple[Any, ...] = ()
    if application_id is not None:
        query += " WHERE application_id = ?"
        params = (application_id,)
    query += " ORDER BY created_at DESC, id DESC"

    with get_connection(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def _clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for column in APPLICATION_COLUMNS:
        value = payload.get(column, "")
        if value is None:
            cleaned[column] = ""
        else:
            cleaned[column] = str(value).strip()

    if not cleaned["status"]:
        cleaned["status"] = "Applied"
    if cleaned["status"] not in STATUS_OPTIONS:
        cleaned["status"] = "Applied"
    return cleaned


def _ensure_application_columns(connection: sqlite3.Connection) -> None:
    existing_columns = {
        str(row["name"])
        for row in connection.execute(
            """
            PRAGMA table_info(applications)
            """
        ).fetchall()
    }
    if "rejection_reason" not in existing_columns:
        connection.execute("ALTER TABLE applications ADD COLUMN rejection_reason TEXT")


def _get_application_by_id(connection: sqlite3.Connection, application_id: int) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT *
        FROM applications
        WHERE id = ?
        """,
        (application_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _insert_event(
    connection: sqlite3.Connection,
    application_id: int,
    event_type: str,
    old_value: str,
    new_value: str,
    source: str,
) -> None:
    connection.execute(
        """
        INSERT INTO application_events (
            application_id,
            event_type,
            old_value,
            new_value,
            source,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            application_id,
            event_type,
            old_value,
            new_value,
            source,
            _now(),
        ),
    )


def _summarize_application(application: dict[str, Any]) -> str:
    company = str(application.get("company", "") or "").strip()
    role = str(application.get("role", "") or "").strip()
    status = str(application.get("status", "") or "").strip()
    return f"{company} / {role} ({status})".strip()


def _build_application_indexes(
    applications: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], dict[tuple[str, str], list[dict[str, Any]]]]:
    exact_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    fallback_index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for application in applications:
        _add_to_indexes(application, exact_index, fallback_index)
    return exact_index, fallback_index


def _add_to_indexes(
    application: dict[str, Any],
    exact_index: dict[tuple[str, str, str], dict[str, Any]],
    fallback_index: dict[tuple[str, str], list[dict[str, Any]]],
) -> None:
    exact_index[_application_exact_key(application)] = application
    fallback_index.setdefault(_application_fallback_key(application), []).append(application)


def _find_existing_application(
    application: dict[str, Any],
    exact_index: dict[tuple[str, str, str], dict[str, Any]],
    fallback_index: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any] | None:
    exact_match = exact_index.get(_application_exact_key(application))
    if exact_match is not None:
        return exact_match

    fallback_matches = fallback_index.get(_application_fallback_key(application), [])
    if len(fallback_matches) == 1:
        return fallback_matches[0]
    return None


def _merge_application(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = {column: str(existing.get(column, "") or "") for column in APPLICATION_COLUMNS}
    for column in APPLICATION_COLUMNS:
        incoming_value = str(incoming.get(column, "") or "").strip()
        if incoming_value:
            merged[column] = incoming_value

    merged["notes"] = _merge_notes(
        str(existing.get("notes", "") or ""),
        str(incoming.get("notes", "") or ""),
    )
    return merged


def _merge_notes(existing_notes: str, incoming_notes: str) -> str:
    note_parts: list[str] = []
    for note in [existing_notes, incoming_notes]:
        for part in note.split(" | "):
            cleaned = part.strip()
            if cleaned and cleaned not in note_parts:
                note_parts.append(cleaned)
    return " | ".join(note_parts)


def _has_application_changes(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    return any(
        str(existing.get(column, "") or "").strip() != str(incoming.get(column, "") or "").strip()
        for column in APPLICATION_COLUMNS
    )


def _application_exact_key(application: dict[str, Any]) -> tuple[str, str, str]:
    return (
        _normalize_identity(application.get("company", "")),
        _normalize_identity(application.get("role", "")),
        str(application.get("application_date", "") or "").strip(),
    )


def _application_fallback_key(application: dict[str, Any]) -> tuple[str, str]:
    return (
        _normalize_identity(application.get("company", "")),
        _normalize_identity(application.get("role", "")),
    )


def _normalize_identity(value: Any) -> str:
    return " ".join(str(value or "").casefold().strip().split())


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
