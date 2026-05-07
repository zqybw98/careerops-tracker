from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from src.database import DEFAULT_DB_PATH, bulk_create_applications, get_applications
from src.models import APPLICATION_COLUMNS


DEFAULT_SAMPLE_PATH = Path("samples/sample_applications.csv")


def read_sample_applications(csv_path: Path | str = DEFAULT_SAMPLE_PATH) -> list[dict[str, Any]]:
    path = Path(csv_path)
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return [
            {column: (row.get(column) or "").strip() for column in APPLICATION_COLUMNS}
            for row in reader
        ]


def seed_sample_applications(
    csv_path: Path | str = DEFAULT_SAMPLE_PATH,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> int:
    sample_rows = read_sample_applications(csv_path)
    existing_keys = {_application_key(application) for application in get_applications(db_path)}
    rows_to_create = [
        row
        for row in sample_rows
        if row.get("company")
        and row.get("role")
        and _application_key(row) not in existing_keys
    ]
    return bulk_create_applications(rows_to_create, db_path=db_path, source="demo_data")


def _application_key(application: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(application.get("company", "")).strip().lower(),
        str(application.get("role", "")).strip().lower(),
        str(application.get("application_date", "")).strip(),
    )
