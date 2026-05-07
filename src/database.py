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
                next_action TEXT,
                follow_up_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.commit()


def create_application(payload: dict[str, Any], db_path: Path | str = DEFAULT_DB_PATH) -> int:
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
        connection.commit()
        return int(cursor.lastrowid)


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
) -> None:
    cleaned = _clean_payload(payload)
    assignments = ", ".join([f"{column} = ?" for column in APPLICATION_COLUMNS])
    values = [cleaned.get(column) for column in APPLICATION_COLUMNS]
    values.extend([_now(), application_id])

    with get_connection(db_path) as connection:
        connection.execute(
            f"""
            UPDATE applications
            SET {assignments}, updated_at = ?
            WHERE id = ?
            """,
            values,
        )
        connection.commit()


def delete_application(application_id: int, db_path: Path | str = DEFAULT_DB_PATH) -> None:
    with get_connection(db_path) as connection:
        connection.execute("DELETE FROM applications WHERE id = ?", (application_id,))
        connection.commit()


def bulk_create_applications(
    rows: list[dict[str, Any]],
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    created = 0
    for row in rows:
        if row.get("company") and row.get("role"):
            create_application(row, db_path=db_path)
            created += 1
    return created


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


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
