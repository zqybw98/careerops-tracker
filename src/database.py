from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.models import APPLICATION_COLUMNS, STATUS_OPTIONS

DEFAULT_DB_PATH = Path("data/applications.db")
MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path


def get_connection(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    with get_connection(db_path) as connection:
        _apply_migrations(connection)
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


def create_email_feedback(
    payload: dict[str, Any],
    db_path: Path | str = DEFAULT_DB_PATH,
    source: str = "manual_feedback",
) -> int:
    now = _now()
    fields = [
        "email_signature",
        "subject",
        "predicted_category",
        "predicted_status",
        "corrected_category",
        "corrected_status",
        "corrected_application_id",
        "corrected_company",
        "corrected_role",
        "source",
        "created_at",
    ]
    values = [
        str(payload.get("email_signature", "") or "").strip(),
        str(payload.get("subject", "") or "").strip(),
        str(payload.get("predicted_category", "") or "").strip(),
        str(payload.get("predicted_status", "") or "").strip(),
        str(payload.get("corrected_category", "") or "").strip(),
        str(payload.get("corrected_status", "") or "").strip(),
        int(payload["corrected_application_id"]) if payload.get("corrected_application_id") else None,
        str(payload.get("corrected_company", "") or "").strip(),
        str(payload.get("corrected_role", "") or "").strip(),
        source,
        now,
    ]

    if not values[0]:
        raise ValueError("Email feedback requires an email signature.")

    with get_connection(db_path) as connection:
        cursor = connection.execute(
            f"""
            INSERT INTO email_feedback ({", ".join(fields)})
            VALUES ({", ".join(["?"] * len(fields))})
            """,
            values,
        )
        if cursor.lastrowid is None:
            raise RuntimeError("Failed to create email feedback record.")
        connection.commit()
        return cursor.lastrowid


def get_email_feedback(
    db_path: Path | str = DEFAULT_DB_PATH,
    limit: int = 100,
) -> list[dict[str, Any]]:
    with get_connection(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM email_feedback
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
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


def _apply_migrations(connection: sqlite3.Connection) -> None:
    _ensure_schema_version_table(connection)
    applied_versions = _get_applied_migration_versions(connection)
    for migration in _load_migrations():
        if migration.version in applied_versions:
            continue
        if not _migration_is_satisfied(connection, migration.version):
            connection.executescript(migration.path.read_text(encoding="utf-8"))
        _record_migration(connection, migration)
        applied_versions.add(migration.version)


def _ensure_schema_version_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _get_applied_migration_versions(connection: sqlite3.Connection) -> set[int]:
    rows = connection.execute("SELECT version FROM schema_version").fetchall()
    return {int(row["version"]) for row in rows}


def _load_migrations() -> list[Migration]:
    migrations = [
        Migration(
            version=_parse_migration_version(path),
            name=path.stem,
            path=path,
        )
        for path in sorted(MIGRATIONS_DIR.glob("*.sql"))
    ]
    if not migrations:
        raise RuntimeError(f"No database migrations found in {MIGRATIONS_DIR}.")
    return migrations


def _parse_migration_version(path: Path) -> int:
    version_text = path.stem.split("_", 1)[0]
    try:
        return int(version_text)
    except ValueError as error:
        raise RuntimeError(f"Invalid migration filename: {path.name}") from error


def _migration_is_satisfied(connection: sqlite3.Connection, version: int) -> bool:
    if version == 1:
        return _table_exists(connection, "applications") and _table_exists(connection, "application_events")
    if version == 2:
        return _column_exists(connection, "applications", "rejection_reason")
    if version == 3:
        return _table_exists(connection, "email_feedback")
    return False


def _record_migration(connection: sqlite3.Connection, migration: Migration) -> None:
    connection.execute(
        """
        INSERT INTO schema_version (version, name, applied_at)
        VALUES (?, ?, ?)
        """,
        (migration.version, migration.name, _now()),
    )


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(str(row["name"]) == column_name for row in rows)


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
