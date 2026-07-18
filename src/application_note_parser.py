from __future__ import annotations

import json
import re
from datetime import date
from typing import Any
from urllib.parse import urlparse

from src.models import STATUS_OPTIONS, apply_status_business_rules, normalize_status

FIELD_ALIASES = {
    "application_date": {
        "date",
        "datum",
        "application_date",
        "application date",
        "applied date",
        "bewerbungsdatum",
        "bewerbung datum",
        "日期",
        "申请日期",
    },
    "company": {
        "company",
        "unternehmen",
        "firma",
        "employer",
        "arbeitgeber",
        "公司",
        "企业",
    },
    "role": {
        "position",
        "role",
        "job title",
        "title",
        "stelle",
        "job",
        "岗位",
        "职位",
    },
    "location": {
        "location",
        "standort",
        "ort",
        "city",
        "地点",
        "城市",
    },
    "status": {
        "status",
        "状态",
    },
    "source_link": {
        "source",
        "source_link",
        "source url",
        "source_url",
        "source link",
        "job url",
        "job link",
        "link",
        "quelle",
        "链接",
        "来源",
    },
    "contact": {
        "contact",
        "kontakt",
        "recruiter",
        "ansprechpartner",
        "联系人",
    },
    "next_action": {
        "next_action",
        "next step",
        "next action",
        "next",
        "to do",
        "todo",
        "nächster schritt",
        "naechster schritt",
        "下一步",
        "后续",
    },
    "follow_up_date": {
        "follow_up_date",
        "follow up date",
        "follow-up date",
        "followup date",
        "follow up",
        "follow-up",
        "next check date",
        "下次跟进",
        "跟进日期",
    },
    "rejection_reason": {
        "rejection_reason",
        "rejection reason",
        "reason",
        "reason for rejection",
        "absagegrund",
        "拒绝原因",
    },
}

NOTE_ALIASES = {
    "CV used": {
        "cv",
        "cv used",
        "cv_version",
        "cv version",
        "resume",
        "resume used",
        "lebenslauf",
        "简历",
    },
    "Cover letter": {
        "cover letter",
        "anschreiben",
        "motivation letter",
        "motivation",
        "求职信",
        "动机信",
    },
    "Notes": {
        "notes",
        "note",
        "remarks",
        "comment",
        "notizen",
        "备注",
    },
}

STATUS_PATTERNS = [
    ("Rejected", ["rejected", "rejection", "absage", "abgelehnt", "leider", "拒绝", "未通过"]),
    ("Interview / Assessment", ["interview", "vorstellungsgespräch", "gespräch", "面试"]),
    ("Interview / Assessment", ["assessment", "coding test", "testaufgabe", "aufgabe", "测评", "笔试"]),
    ("Action Needed", ["offer", "angebot", "录用", "offer"]),
    ("Waiting", ["confirmation", "bestätigung", "eingangsbestätigung", "确认邮件"]),
    (
        "Applied",
        [
            "applied",
            "submitted",
            "application sent",
            "bewerbung abgeschickt",
            "erfolgreich abgeschickt",
            "eingereicht",
            "申请已提交",
            "已经成功提交",
        ],
    ),
    ("Action Needed", ["follow-up needed", "follow up needed", "needs follow-up", "需要跟进"]),
    ("Waiting", ["no response", "keine rückmeldung", "keine rueckmeldung", "无回复"]),
    ("Applied", ["saved", "gespeichert", "收藏", "已保存"]),
]


def parse_application_note(text: str) -> dict[str, Any]:
    cleaned_text = _clean_text(text)
    fields: dict[str, str] = {}
    note_lines: list[str] = []
    matched_labels: list[str] = []

    json_mapping = _extract_json_mapping(cleaned_text)
    if json_mapping:
        _collect_mapping_values(json_mapping, fields, note_lines, matched_labels)
    else:
        for label, value in _iter_key_value_lines(cleaned_text):
            _collect_labeled_value(label, value, fields, note_lines, matched_labels)

    if not fields.get("source_link"):
        fields["source_link"] = _extract_first_url(cleaned_text)

    notes = "Structured note import"
    if note_lines:
        notes = f"{notes} | " + " | ".join(note_lines)

    return {
        "fields": fields,
        "notes": notes,
        "matched_labels": matched_labels,
        "missing_fields": [field for field in ["company", "role"] if not fields.get(field)],
        "summary": _summary(fields),
    }


def build_application_payload(
    parsed: dict[str, Any],
    *,
    default_application_date: date | None = None,
) -> dict[str, str]:
    fields = parsed.get("fields", {}) if isinstance(parsed, dict) else {}
    notes = str(parsed.get("notes", "") or "") if isinstance(parsed, dict) else ""
    fallback_date = default_application_date or date.today()
    payload = {
        "company": str(fields.get("company", "") or "").strip(),
        "role": str(fields.get("role", "") or "").strip(),
        "location": str(fields.get("location", "") or "").strip(),
        "application_date": str(fields.get("application_date", "") or "").strip() or fallback_date.isoformat(),
        "status": normalize_status(fields.get("status", "Applied")),
        "source_link": str(fields.get("source_link", "") or "").strip(),
        "contact": str(fields.get("contact", "") or "").strip(),
        "notes": "" if notes == "Structured note import" else notes,
        "rejection_reason": str(fields.get("rejection_reason", "") or "").strip(),
        "next_action": str(fields.get("next_action", "") or "").strip(),
        "follow_up_date": str(fields.get("follow_up_date", "") or "").strip(),
    }
    return apply_status_business_rules(payload)


def _iter_key_value_lines(text: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw_line).strip()
        match = re.match(r"^([^:：]{1,48})\s*[:：]\s*(.+)$", line)
        if match:
            entries.append((match.group(1), match.group(2)))
    return entries


def _parse_field_value(field_name: str, value: str) -> str:
    cleaned_value = _trim_value(value)
    if field_name in {"application_date", "follow_up_date"}:
        return _parse_date(cleaned_value)
    if field_name == "status":
        return _normalize_status(cleaned_value)
    if field_name == "source_link":
        return _valid_url(cleaned_value) or _extract_first_url(cleaned_value) or cleaned_value
    return cleaned_value


def _parse_date(value: str) -> str:
    patterns = [
        (r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", "ymd"),
        (r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", "dmy"),
        (r"\b(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日?\b", "ymd"),
    ]
    for pattern, order in patterns:
        match = re.search(pattern, value)
        if not match:
            continue
        first, second, third = (int(match.group(index)) for index in range(1, 4))
        year, month, day = (first, second, third) if order == "ymd" else (third, second, first)
        iso_date = _safe_iso_date(year, month, day)
        if iso_date:
            return iso_date
    return ""


def _normalize_status(value: str) -> str:
    normalized = _normalize_text(value)
    for status in STATUS_OPTIONS:
        if _normalize_text(status) in normalized:
            return status
    for status, patterns in STATUS_PATTERNS:
        if any(_normalize_text(pattern) in normalized for pattern in patterns):
            return status
    return normalize_status(value)


def _field_for_label(normalized_label: str) -> str:
    for field_name, aliases in FIELD_ALIASES.items():
        if normalized_label in {_normalize_label(alias) for alias in aliases}:
            return field_name
    return ""


def _note_label_for_label(normalized_label: str) -> str:
    for note_label, aliases in NOTE_ALIASES.items():
        if normalized_label in {_normalize_label(alias) for alias in aliases}:
            return note_label
    return ""


def _extract_json_mapping(text: str) -> dict[str, Any]:
    candidates: list[str] = []
    for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.IGNORECASE | re.DOTALL):
        candidates.append(match.group(1))

    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)

    object_match = re.search(r"(\{.*\})", text, flags=re.DOTALL)
    if object_match:
        candidates.append(object_match.group(1))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _collect_mapping_values(
    mapping: dict[str, Any],
    fields: dict[str, str],
    note_lines: list[str],
    matched_labels: list[str],
) -> None:
    for key, value in mapping.items():
        if isinstance(value, dict | list):
            string_value = _stringify_value(value)
        else:
            string_value = "" if value is None else str(value)
        _collect_labeled_value(str(key), string_value, fields, note_lines, matched_labels)


def _collect_labeled_value(
    label: str,
    value: str,
    fields: dict[str, str],
    note_lines: list[str],
    matched_labels: list[str],
) -> None:
    normalized_label = _normalize_label(label)
    field_name = _field_for_label(normalized_label)
    if field_name:
        parsed_value = _parse_field_value(field_name, value)
        if parsed_value:
            fields[field_name] = parsed_value
            matched_labels.append(label.strip())
        return

    note_label = _note_label_for_label(normalized_label)
    if note_label:
        cleaned_value = _trim_value(value)
        if cleaned_value:
            note_lines.append(f"{note_label}: {cleaned_value}")
            matched_labels.append(label.strip())


def _stringify_value(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(_stringify_value(item) for item in value if item is not None)
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_stringify_value(item)}" for key, item in value.items())
    return str(value)


def _summary(fields: dict[str, str]) -> str:
    company = fields.get("company", "")
    role = fields.get("role", "")
    if company and role:
        return f"Ready to add {company} / {role}."
    return "Review the extracted fields before adding the application."


def _extract_first_url(text: str) -> str:
    match = re.search(r"https?://[^\s)>\]]+", text)
    return match.group(0).rstrip(".,") if match else ""


def _valid_url(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    parsed = urlparse(text)
    return text if parsed.scheme in {"http", "https"} and bool(parsed.netloc) else ""


def _safe_iso_date(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat() if 1 <= year <= 2100 else ""
    except ValueError:
        return ""


def _trim_value(value: str) -> str:
    candidate = re.split(r"[\n\r<>]", value.strip(), maxsplit=1)[0]
    return re.sub(r"\s+", " ", candidate).strip(" -:,\"'")


def _normalize_label(value: str) -> str:
    prepared = value.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", prepared.casefold().strip().strip(":：\"'"))


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().strip())


def _clean_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")
