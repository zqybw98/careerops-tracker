from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

EXPORT_FORMAT_VERSION = 1

APPROVED_TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "applications": (
        "id",
        "company",
        "role",
        "location",
        "application_date",
        "status",
        "source_link",
        "contact",
        "notes",
        "rejection_reason",
        "next_action",
        "follow_up_date",
        "created_at",
        "updated_at",
    ),
    "application_events": (
        "id",
        "application_id",
        "event_type",
        "old_value",
        "new_value",
        "source",
        "created_at",
    ),
    "email_feedback": (
        "id",
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
    ),
    "schema_version": ("version", "name", "applied_at"),
    "company_research_notes": (
        "id",
        "company",
        "checked_at",
        "decision",
        "relevant_roles",
        "skipped_roles",
        "summary",
        "notes",
        "source_link",
        "created_at",
        "updated_at",
    ),
}

REQUIRED_TABLES = {"applications", "application_events", "email_feedback", "schema_version"}
CSV_EXPORT_TABLES = ("applications", "application_events", "email_feedback", "company_research_notes")
APPROVED_INDEXES = (
    "idx_application_events_application_id",
    "idx_email_feedback_signature",
    "idx_company_research_company",
    "idx_company_research_checked_at",
)
CONTACT_COLUMNS = (
    "application_id",
    "company",
    "role",
    "status",
    "contact",
    "source_link",
    "updated_at",
)


class ExportPolicyError(RuntimeError):
    """Raised when the database schema exceeds the approved export boundary."""


@dataclass(frozen=True)
class ExportResult:
    files: tuple[Path, ...]
    row_counts: dict[str, int]
    fingerprint: str


def export_private_data(db_path: Path, destination: Path) -> ExportResult:
    source = Path(db_path)
    target = Path(destination)
    if not source.is_file():
        raise FileNotFoundError(f"CareerOps database not found: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="careerops-export-", dir=target.parent) as temp_dir:
        staging = Path(temp_dir)
        rows_by_table, schema_by_table, indexes = _read_approved_snapshot(source)
        row_counts = _write_staged_export(staging, rows_by_table, schema_by_table, indexes)
        fingerprint = _content_fingerprint(staging)
        manifest = {
            "export_format_version": EXPORT_FORMAT_VERSION,
            "fingerprint": fingerprint,
            "row_counts": row_counts,
            "tables": list(APPROVED_TABLE_COLUMNS),
        }
        _write_text(staging / "sync_manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        relative_files = tuple(sorted(path.relative_to(staging) for path in staging.rglob("*") if path.is_file()))
        _publish_staged_files(staging, target, relative_files)

    return ExportResult(
        files=tuple(target / relative_path for relative_path in relative_files),
        row_counts=row_counts,
        fingerprint=fingerprint,
    )


def _read_approved_snapshot(
    db_path: Path,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str], list[str]]:
    uri_path = quote(db_path.resolve().as_posix(), safe="/:")
    connection = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN")
        rows_by_table: dict[str, list[dict[str, Any]]] = {}
        schema_by_table: dict[str, str] = {}
        for table, approved_columns in APPROVED_TABLE_COLUMNS.items():
            table_sql = _table_sql(connection, table)
            if table_sql is None:
                if table in REQUIRED_TABLES:
                    raise ExportPolicyError(f"Required table is missing: {table}")
                rows_by_table[table] = []
                continue

            actual_columns = _table_columns(connection, table)
            approved_set = set(approved_columns)
            actual_set = set(actual_columns)
            extra_columns = sorted(actual_set - approved_set)
            missing_columns = sorted(approved_set - actual_set)
            if extra_columns:
                raise ExportPolicyError(f"Table {table} has unapproved columns: {', '.join(extra_columns)}")
            if missing_columns:
                raise ExportPolicyError(f"Table {table} is missing approved columns: {', '.join(missing_columns)}")

            schema_by_table[table] = table_sql.rstrip().rstrip(";") + ";"
            rows_by_table[table] = _ordered_rows(connection, table, approved_columns)

        indexes = _approved_index_sql(connection)
        connection.rollback()
        return rows_by_table, schema_by_table, indexes
    finally:
        connection.close()


def _table_sql(connection: sqlite3.Connection, table: str) -> str | None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def _table_columns(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
    quoted_table = _quote_identifier(table)
    return tuple(str(row[1]) for row in connection.execute(f"PRAGMA table_info({quoted_table})"))


def _ordered_rows(
    connection: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
) -> list[dict[str, Any]]:
    quoted_table = _quote_identifier(table)
    quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
    primary_keys = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({quoted_table})") if int(row[5]) > 0]
    sort_columns = primary_keys or list(columns)
    order_by = ", ".join(_quote_identifier(column) for column in sort_columns)
    rows = connection.execute(f"SELECT {quoted_columns} FROM {quoted_table} ORDER BY {order_by}").fetchall()
    return [dict(row) for row in rows]


def _approved_index_sql(connection: sqlite3.Connection) -> list[str]:
    statements: list[str] = []
    for index_name in APPROVED_INDEXES:
        row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (index_name,),
        ).fetchone()
        if row and row[0]:
            statements.append(str(row[0]).rstrip().rstrip(";") + ";")
    return statements


def _write_staged_export(
    staging: Path,
    rows_by_table: dict[str, list[dict[str, Any]]],
    schema_by_table: dict[str, str],
    indexes: list[str],
) -> dict[str, int]:
    row_counts: dict[str, int] = {}
    for table in CSV_EXPORT_TABLES:
        rows = rows_by_table.get(table, [])
        _write_csv(
            staging / "exports" / f"{table}.csv",
            APPROVED_TABLE_COLUMNS[table],
            rows,
        )
        row_counts[table] = len(rows)

    contact_rows = _contact_rows(rows_by_table.get("applications", []))
    _write_csv(staging / "exports" / "contacts.csv", CONTACT_COLUMNS, contact_rows)
    row_counts["contacts"] = len(contact_rows)

    sql_text = _build_sql_dump(rows_by_table, schema_by_table, indexes)
    _write_text(staging / "snapshot" / "careerops.sql", sql_text)
    return row_counts


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _contact_rows(applications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for application in applications:
        contact = str(application.get("contact") or "").strip()
        source_link = str(application.get("source_link") or "").strip()
        if not contact and not source_link:
            continue
        rows.append(
            {
                "application_id": application.get("id"),
                "company": application.get("company"),
                "role": application.get("role"),
                "status": application.get("status"),
                "contact": contact,
                "source_link": source_link,
                "updated_at": application.get("updated_at"),
            }
        )
    return rows


def _build_sql_dump(
    rows_by_table: dict[str, list[dict[str, Any]]],
    schema_by_table: dict[str, str],
    indexes: list[str],
) -> str:
    lines = ["PRAGMA foreign_keys=OFF;", "BEGIN TRANSACTION;"]
    for table, columns in APPROVED_TABLE_COLUMNS.items():
        if table not in schema_by_table:
            continue
        lines.append(schema_by_table[table])
        quoted_table = _quote_identifier(table)
        quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
        for row in rows_by_table[table]:
            values = ", ".join(_sql_literal(row.get(column)) for column in columns)
            lines.append(f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({values});")
    lines.extend(indexes)
    lines.extend(["COMMIT;", ""])
    return "\n".join(lines)


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bytes):
        return f"X'{value.hex()}'"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _content_fingerprint(staging: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(path for path in staging.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(staging).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(value)


def _publish_staged_files(staging: Path, target: Path, relative_files: tuple[Path, ...]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for relative_path in relative_files:
        destination = target / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging / relative_path, destination)
