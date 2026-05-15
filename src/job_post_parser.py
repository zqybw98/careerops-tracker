from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlparse

from src.config_loader import get_job_post_config

JOB_POST_CONFIG = get_job_post_config()
DEFAULT_STATUS = JOB_POST_CONFIG["default_status"]
JOB_BOARD_DOMAINS = set(JOB_POST_CONFIG["job_board_domains"])
COMMON_LOCATIONS = JOB_POST_CONFIG["common_locations"]
ROLE_KEYWORDS = tuple(JOB_POST_CONFIG["role_keywords"])
ROLE_STOP_LINES = set(JOB_POST_CONFIG["role_stop_lines"])
DEADLINE_KEYWORDS = tuple(JOB_POST_CONFIG["deadline_keywords"])
MONTH_LOOKUP = JOB_POST_CONFIG["month_lookup"]
NEXT_ACTIONS = JOB_POST_CONFIG["next_actions"]


def analyze_job_post(job_text: str = "", source_url: str = "") -> dict[str, Any]:
    text = _clean_text(f"{source_url}\n{job_text}")
    source_link = _valid_url(source_url) or _extract_first_url(text)
    details = {
        "company": _extract_company(text) or _company_from_url(source_link),
        "role": _extract_role(text),
        "location": _extract_location(text),
        "source_link": source_link,
        "contact": _extract_contact(text),
        "deadline": _extract_deadline(text),
    }
    next_action = _build_next_action(details)
    confidence = _confidence(details)

    return {
        "details": details,
        "status": DEFAULT_STATUS,
        "confidence": confidence,
        "confidence_label": f"{confidence:.0%}",
        "next_action": next_action,
        "follow_up_date": details["deadline"],
        "missing_fields": _missing_fields(details),
        "summary": _summary(details, confidence),
        "field_rows": _field_rows(details),
    }


def build_job_post_notes(analysis: dict[str, Any]) -> str:
    details = analysis["details"]
    extracted_parts = [
        f"{label}: {details[key]}"
        for label, key in [
            ("Company", "company"),
            ("Role", "role"),
            ("Location", "location"),
            ("Source", "source_link"),
            ("Contact", "contact"),
            ("Deadline", "deadline"),
        ]
        if details.get(key)
    ]
    note_parts = [
        f"Draft created from job post intake with {analysis['confidence_label']} extraction confidence.",
    ]
    if extracted_parts:
        note_parts.append("Extracted " + "; ".join(extracted_parts))
    if analysis.get("missing_fields"):
        note_parts.append("Needs manual review: " + ", ".join(analysis["missing_fields"]))
    return " ".join(note_parts)


def _extract_company(text: str) -> str:
    for pattern in JOB_POST_CONFIG["extraction_patterns"]["company"]:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            candidate = _trim_candidate(match.group(1))
            if candidate:
                return candidate
    return ""


def _extract_role(text: str) -> str:
    for pattern in JOB_POST_CONFIG["extraction_patterns"]["role"]:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            candidate = _trim_role(match.group(1))
            if candidate:
                return candidate

    for line in _candidate_lines(text):
        normalized = line.casefold()
        if any(keyword in normalized for keyword in ROLE_KEYWORDS):
            return _trim_role(line)
    return ""


def _extract_location(text: str) -> str:
    for pattern in JOB_POST_CONFIG["extraction_patterns"]["location"]:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = _trim_candidate(match.group(1))
            if candidate:
                return candidate

    for location in COMMON_LOCATIONS:
        if re.search(rf"\b{re.escape(location)}\b", text, flags=re.IGNORECASE):
            return location
    return ""


def _extract_contact(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    return match.group(0) if match else ""


def _extract_deadline(text: str) -> str:
    candidates: list[tuple[int, int, str]] = []
    for iso_date, start, end in _find_dates(text):
        window_start = max(0, start - 120)
        window_end = min(len(text), end + 120)
        context = text[window_start:window_end].casefold()
        for keyword in DEADLINE_KEYWORDS:
            keyword_position_in_context = _keyword_position(context, keyword.casefold())
            if keyword_position_in_context is None:
                continue
            keyword_position = window_start + keyword_position_in_context
            distance = abs(start - keyword_position)
            candidates.append((distance, start, iso_date))
    return sorted(candidates)[0][2] if candidates else ""


def _find_dates(text: str) -> list[tuple[str, int, int]]:
    matches: list[tuple[str, int, int]] = []

    for match in re.finditer(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", text):
        iso_date = _safe_iso_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if iso_date:
            matches.append((iso_date, match.start(), match.end()))

    for match in re.finditer(r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", text):
        iso_date = _safe_iso_date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
        if iso_date:
            matches.append((iso_date, match.start(), match.end()))

    month_names = "|".join(sorted((re.escape(month) for month in MONTH_LOOKUP), key=len, reverse=True))
    for match in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\.?\s+({month_names})\s+(20\d{{2}})\b", text, re.I):
        iso_date = _safe_iso_date(
            int(match.group(3)),
            MONTH_LOOKUP[match.group(2).casefold()],
            int(match.group(1)),
        )
        if iso_date:
            matches.append((iso_date, match.start(), match.end()))

    for match in re.finditer(rf"\b({month_names})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,)?\s+(20\d{{2}})\b", text, re.I):
        iso_date = _safe_iso_date(
            int(match.group(3)),
            MONTH_LOOKUP[match.group(1).casefold()],
            int(match.group(2)),
        )
        if iso_date:
            matches.append((iso_date, match.start(), match.end()))

    for match in re.finditer(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日?", text):
        iso_date = _safe_iso_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if iso_date:
            matches.append((iso_date, match.start(), match.end()))

    return sorted(set(matches), key=lambda value: value[1])


def _keyword_position(text: str, keyword: str) -> int | None:
    if re.search(r"[^\x00-\x7F]", keyword):
        position = text.find(keyword)
        return position if position >= 0 else None
    match = re.search(rf"\b{re.escape(keyword)}\b", text)
    return match.start() if match else None


def _safe_iso_date(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat() if 1 <= year <= 2100 else ""
    except ValueError:
        return ""


def _build_next_action(details: dict[str, str]) -> str:
    if details.get("deadline"):
        return NEXT_ACTIONS["with_deadline"].format(deadline=details["deadline"])
    if details.get("source_link"):
        return NEXT_ACTIONS["with_source"]
    return NEXT_ACTIONS["default"]


def _confidence(details: dict[str, str]) -> float:
    score = 0.0
    score += 0.3 if details.get("company") else 0.0
    score += 0.35 if details.get("role") else 0.0
    score += 0.15 if details.get("location") else 0.0
    score += 0.1 if details.get("source_link") else 0.0
    score += 0.1 if details.get("deadline") or details.get("contact") else 0.0
    return min(0.95, round(score, 2))


def _missing_fields(details: dict[str, str]) -> list[str]:
    return [field for field in ["company", "role"] if not details.get(field)]


def _summary(details: dict[str, str], confidence: float) -> str:
    if details.get("company") and details.get("role"):
        return (
            f"Ready to create a Saved application for {details['company']} / "
            f"{details['role']} ({confidence:.0%} confidence)."
        )
    return "Review missing required fields before creating a Saved application."


def _field_rows(details: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"Field": label, "Value": details.get(key, "") or "-"}
        for label, key in [
            ("Company", "company"),
            ("Role", "role"),
            ("Location", "location"),
            ("Source link", "source_link"),
            ("Contact", "contact"),
            ("Deadline", "deadline"),
        ]
    ]


def _candidate_lines(text: str) -> list[str]:
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"^[#*\-•\s]+", "", raw_line).strip()
        normalized = line.casefold().rstrip(":")
        if not line or len(line) > 140:
            continue
        if _valid_url(line) or normalized in ROLE_STOP_LINES:
            continue
        if re.match(r"^(company|unternehmen|firma|location|standort|contact|kontakt)\s*[:：]", normalized):
            continue
        lines.append(line)
    return lines


def _extract_first_url(text: str) -> str:
    match = re.search(r"https?://[^\s)>\]]+", text)
    return match.group(0).rstrip(".,") if match else ""


def _valid_url(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    parsed = urlparse(text)
    return text if parsed.scheme in {"http", "https"} and bool(parsed.netloc) else ""


def _company_from_url(source_link: str) -> str:
    if not source_link:
        return ""
    parsed = urlparse(source_link)
    parts = [part for part in parsed.netloc.casefold().removeprefix("www.").split(".") if part]
    ignored = JOB_BOARD_DOMAINS | {"career", "careers", "com", "de", "eu", "jobs", "net", "org"}
    for part in parts:
        cleaned = re.sub(r"[^a-z0-9-]+", "", part)
        if cleaned and cleaned not in ignored:
            return _format_company_name(cleaned)
    return ""


def _format_company_name(value: str) -> str:
    words = [part for part in re.split(r"[-_]+", value) if part]
    if len(value) <= 3:
        return value.upper()
    return " ".join(word.upper() if len(word) <= 3 else word.title() for word in words)


def _trim_candidate(value: str) -> str:
    candidate = re.split(r"[\n\r|;<>]", value.strip(), maxsplit=1)[0]
    candidate = re.sub(r"\s+", " ", candidate).strip(" -:,")
    return candidate[:100]


def _trim_role(value: str) -> str:
    candidate = re.split(r"[\n\r|;<>]", value.strip(), maxsplit=1)[0]
    candidate = re.sub(r"\s+", " ", candidate).strip(" -:,")
    return candidate[:140]


def _clean_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")
