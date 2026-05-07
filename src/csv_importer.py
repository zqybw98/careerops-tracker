from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

from src.models import APPLICATION_COLUMNS, STATUS_OPTIONS


@dataclass(frozen=True)
class CsvImportResult:
    rows: list[dict[str, str]]
    skipped_count: int
    source_columns: list[str]


COLUMN_ALIASES = {
    "company": [
        "company",
        "company name",
        "公司",
        "公司名称",
        "公司名称 (company)",
    ],
    "role": [
        "role",
        "position",
        "job title",
        "职位",
        "职位名称",
        "申请职位",
        "职位名称 (position)",
    ],
    "application_date": [
        "application_date",
        "application date",
        "date applied",
        "申请日期",
        "申请日期 (date applied)",
    ],
    "status": [
        "status",
        "latest status",
        "最新状态",
        "最新状态 (status)",
    ],
    "notes": [
        "notes",
        "remark",
        "remarks",
        "source",
        "备注",
        "备注/来源",
        "备注/来源 (notes)",
    ],
    "follow_up_date": [
        "follow_up_date",
        "follow up date",
        "follow-up date",
        "状态更新日期",
    ],
}


def normalize_import_rows(records: Iterable[Mapping[str, Any]]) -> CsvImportResult:
    materialized_records = list(records)
    source_columns = _source_columns(materialized_records)
    column_mapping = _infer_column_mapping(source_columns)
    normalized_rows: list[dict[str, str]] = []
    skipped_count = 0
    seen_keys: set[tuple[str, str, str]] = set()

    for record in materialized_records:
        cleaned_record = _clean_record(record)
        if _is_blank_record(cleaned_record):
            skipped_count += 1
            continue

        parsed = (
            _parse_pipe_record(cleaned_record)
            or _parse_numbered_table_record(cleaned_record)
            or _parse_standard_record(cleaned_record, column_mapping)
        )

        if parsed is None or _is_header_like_row(parsed):
            skipped_count += 1
            continue

        finalized = _finalize_row(parsed)
        if not finalized["company"] or not finalized["role"]:
            skipped_count += 1
            continue

        key = _row_key(finalized)
        if key in seen_keys:
            skipped_count += 1
            continue
        seen_keys.add(key)
        normalized_rows.append(finalized)

    return CsvImportResult(
        rows=normalized_rows,
        skipped_count=skipped_count,
        source_columns=source_columns,
    )


def _source_columns(records: list[Mapping[str, Any]]) -> list[str]:
    if not records:
        return []
    return [str(column) for column in records[0].keys()]


def _infer_column_mapping(columns: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    normalized_columns = {_normalize_label(column): column for column in columns}
    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            source = normalized_columns.get(_normalize_label(alias))
            if source:
                mapping[target] = source
                break
    return mapping


def _parse_standard_record(
    record: dict[str, str],
    column_mapping: dict[str, str],
) -> dict[str, str] | None:
    if "company" not in column_mapping or "role" not in column_mapping:
        return None

    row = _empty_application_row()
    for target, source in column_mapping.items():
        if target in row:
            row[target] = record.get(source, "")
    return row


def _parse_numbered_table_record(record: dict[str, str]) -> dict[str, str] | None:
    columns = list(record.keys())
    if len(columns) < 5:
        return None

    first_value = record.get(columns[0], "")
    if not first_value.isdigit():
        return None

    row = _empty_application_row()
    row["company"] = record.get(columns[1], "")
    row["role"] = record.get(columns[2], "")
    row["application_date"] = record.get(columns[3], "")
    row["status"] = record.get(columns[4], "")
    row["notes"] = _join_notes(
        [
            record.get(columns[6], "") if len(columns) > 6 else "",
            record.get(columns[5], "") if len(columns) > 5 else "",
        ]
    )
    return row


def _parse_pipe_record(record: dict[str, str]) -> dict[str, str] | None:
    values = list(record.values())
    non_empty_values = [value for value in values if value]
    if len(non_empty_values) != 1 or " | " not in non_empty_values[0]:
        return None

    parts = [part.strip() for part in non_empty_values[0].split("|")]
    if len(parts) < 4 or not _normalize_date(parts[0]):
        return None

    row = _empty_application_row()
    row["application_date"] = parts[0]
    row["company"] = parts[1]
    row["role"] = parts[2]
    row["status"] = parts[3]
    row["notes"] = " | ".join(parts[4:])
    return row


def _finalize_row(row: dict[str, str]) -> dict[str, str]:
    finalized = _empty_application_row()
    for column in APPLICATION_COLUMNS:
        finalized[column] = _clean_value(row.get(column, ""))

    raw_status = finalized["status"]
    finalized["application_date"] = _normalize_date(finalized["application_date"])
    finalized["follow_up_date"] = _normalize_date(finalized["follow_up_date"])
    finalized["status"] = _normalize_status(raw_status)
    finalized["next_action"] = finalized["next_action"] or _suggest_next_action(finalized["status"])

    if raw_status and raw_status not in STATUS_OPTIONS and raw_status != finalized["status"]:
        finalized["notes"] = _join_notes([finalized["notes"], f"Original status: {raw_status}"])
    return finalized


def _normalize_status(value: str) -> str:
    text = _clean_value(value).lower()
    if not text:
        return "Applied"

    if any(keyword in text for keyword in ["rejected", "拒信", "已收到拒信", "absage"]):
        return "Rejected"
    if any(keyword in text for keyword in ["assessment", "coding test", "online test", "在线测评", "测评"]):
        return "Assessment"
    if any(keyword in text for keyword in ["interview", "面试"]):
        return "Interview Scheduled"
    if any(keyword in text for keyword in ["confirmation received", "确认收到", "已确认收到", "收到申请确认"]):
        return "Confirmation Received"
    if any(keyword in text for keyword in ["follow-up", "follow up", "待跟进"]):
        return "Follow-up Needed"
    if any(keyword in text for keyword in ["offer", "录用"]):
        return "Offer"
    if any(keyword in text for keyword in ["submitted", "applied", "email sent", "已申请", "投递"]):
        return "Applied"
    if any(keyword in text for keyword in ["岗位取消", "cancelled", "canceled", "withdrawn"]):
        return "No Response"

    return value if value in STATUS_OPTIONS else "Applied"


def _normalize_date(value: str) -> str:
    text = _clean_value(value)
    if not text:
        return ""

    for date_format in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, date_format).date().isoformat()
        except ValueError:
            continue
    return ""


def _suggest_next_action(status: str) -> str:
    suggestions = {
        "Saved": "Decide whether to apply.",
        "Applied": "Wait for response and follow up if needed.",
        "Confirmation Received": "Wait for the next response and follow up if needed.",
        "Interview Scheduled": "Prepare interview notes and confirm logistics.",
        "Assessment": "Complete assessment and check the deadline.",
        "Offer": "Review offer details and decide next step.",
        "Rejected": "Capture lessons learned.",
        "No Response": "Consider follow-up or archive the application.",
        "Follow-up Needed": "Send or prepare a polite follow-up.",
    }
    return suggestions.get(status, "")


def _is_header_like_row(row: dict[str, str]) -> bool:
    company = _normalize_label(row.get("company", ""))
    role = _normalize_label(row.get("role", ""))
    application_date = _normalize_label(row.get("application_date", ""))
    return (
        company in {"company", "company name", "公司", "公司名称", "序号"}
        or role in {"role", "position", "job title", "职位", "职位名称", "申请职位", "公司名称"}
        or application_date in {"application date", "date applied", "申请日期", "申请职位"}
    )


def _row_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        row.get("company", "").lower(),
        row.get("role", "").lower(),
        row.get("application_date", ""),
    )


def _clean_record(record: Mapping[str, Any]) -> dict[str, str]:
    return {str(key): _clean_value(value) for key, value in record.items()}


def _empty_application_row() -> dict[str, str]:
    return {column: "" for column in APPLICATION_COLUMNS}


def _is_blank_record(record: dict[str, str]) -> bool:
    return not any(record.values())


def _clean_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.lower() == "nan":
        return ""
    return " ".join(text.strip().split())


def _join_notes(values: list[str]) -> str:
    return " | ".join(value for value in values if value)


def _normalize_label(value: str) -> str:
    text = _clean_value(value).lower()
    text = text.replace("_", " ").replace("-", " ")
    return " ".join(text.split())
