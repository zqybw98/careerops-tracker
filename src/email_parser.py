from __future__ import annotations

import re
from datetime import date
from typing import Any

GENERIC_EMAIL_DOMAINS = {
    "gmail",
    "googlemail",
    "outlook",
    "hotmail",
    "live",
    "yahoo",
    "icloud",
    "greenhouse",
    "lever",
    "workday",
    "successfactors",
    "smartrecruiters",
    "ashbyhq",
    "personio",
    "bamboohr",
}

ROLE_STOP_WORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "your",
    "our",
    "you",
    "application",
    "position",
    "role",
    "job",
    "working",
    "student",
    "intern",
}

COMMON_LOCATIONS = [
    "Berlin",
    "Munich",
    "Muenchen",
    "München",
    "Hamburg",
    "Stuttgart",
    "Frankfurt",
    "Cologne",
    "Köln",
    "Düsseldorf",
    "Dresden",
    "Leipzig",
    "Potsdam",
    "Walldorf",
    "Bonn",
    "Remote",
    "Hybrid",
]

MONTH_LOOKUP = {
    "jan": 1,
    "january": 1,
    "januar": 1,
    "feb": 2,
    "february": 2,
    "februar": 2,
    "mar": 3,
    "march": 3,
    "märz": 3,
    "maerz": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "june": 6,
    "juni": 6,
    "jul": 7,
    "july": 7,
    "juli": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "okt": 10,
    "oktober": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
    "dez": 12,
    "dezember": 12,
}

DEADLINE_KEYWORDS = (
    "deadline",
    "due",
    "complete by",
    "submit by",
    "until",
    "by",
    "bis",
    "spätestens",
    "spaetestens",
    "frist",
)

INTERVIEW_DATE_KEYWORDS = (
    "interview",
    "call",
    "meeting",
    "gespräch",
    "gespraech",
    "video interview",
    "phone interview",
    "technical interview",
    "teams",
    "zoom",
)


def extract_application_details(subject: str = "", body: str = "") -> dict[str, str]:
    text = _clean_text(f"{subject}\n{body}")
    deadline = _extract_context_date(text, DEADLINE_KEYWORDS)
    interview_date = _extract_context_date(text, INTERVIEW_DATE_KEYWORDS)
    return {
        "company": _extract_company(text),
        "role": _extract_role(text),
        "location": _extract_location(text),
        "contact": _extract_contact(text),
        "source_link": _extract_first_url(text),
        "deadline": deadline,
        "interview_date": interview_date,
        "suggested_follow_up_date": deadline or interview_date,
        "rejection_reason": _extract_rejection_reason(text),
    }


def match_application_from_email(
    applications: list[dict[str, Any]],
    subject: str = "",
    body: str = "",
    extracted_details: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if not applications:
        return None

    details = extracted_details or extract_application_details(subject, body)
    text = _normalize_text(f"{subject}\n{body} {details.get('company', '')} {details.get('role', '')}")
    scored_matches = [_score_application_match(application, text, details) for application in applications]
    scored_matches = [match for match in scored_matches if match["score"] >= 3]
    if not scored_matches:
        return None

    return max(scored_matches, key=lambda match: match["score"])


def _score_application_match(
    application: dict[str, Any],
    normalized_email_text: str,
    details: dict[str, str],
) -> dict[str, Any]:
    company = str(application.get("company", ""))
    role = str(application.get("role", ""))
    score = 0
    reasons: list[str] = []

    if _contains_phrase(normalized_email_text, company):
        score += 5
        reasons.append("company name appears in email")
    elif details.get("company") and _identity(details["company"]) == _identity(company):
        score += 5
        reasons.append("extracted company matches existing application")

    if _contains_phrase(normalized_email_text, role):
        score += 6
        reasons.append("role title appears in email")
    elif details.get("role") and _role_similarity(details["role"], role) >= 0.5:
        score += 4
        reasons.append("extracted role is similar to existing role")

    overlap = _role_similarity(role, normalized_email_text)
    if overlap >= 0.4:
        score += 2
        reasons.append("role keywords overlap with email text")

    return {
        "application_id": application.get("id"),
        "company": company,
        "role": role,
        "score": score,
        "reasons": reasons,
    }


def _extract_company(text: str) -> str:
    patterns = [
        r"(?:company|employer|arbeitgeber|unternehmen)\s*:\s*([A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9&.+\- ]{1,60})",
        r"(?:applying|applied|application)\s+(?:to|at)\s+([A-Z][A-Za-z0-9&.+\- ]{1,60})",
        r"(?:position|role|job)\s+(?:at|with)\s+([A-Z][A-Za-z0-9&.+\- ]{1,60})",
        r"(?:interview|assessment|application).{0,80}\s+at\s+([A-Z][A-Za-z0-9&.+\- ]{1,60})",
        r"from:\s?.*?@([A-Za-z0-9.-]+\.[A-Za-z]{2,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        candidate = match.group(1)
        if "@" in match.group(0):
            candidate = _company_from_domain(candidate)
        candidate = _trim_candidate(candidate)
        if candidate:
            return candidate

    return ""


def _extract_role(text: str) -> str:
    patterns = [
        r"(?:role|position|job title|stelle|positionstitel)\s*:\s*(.{3,120})",
        r"(?:application|applied)\s+(?:for|as)\s+(.{3,120})",
        r"(?:position|role|job)\s+(?:of|as|for)\s+(.{3,120})",
        r"betreff:\s*(?:bewerbung|application)\s+(.{3,120})",
        r"subject:\s*(?:application|interview|update).{0,40}\s+for\s+(.{3,120})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = _trim_role(match.group(1))
            if candidate:
                return candidate
    return ""


def _extract_contact(text: str) -> str:
    from_match = re.search(r"from:\s*([^\n<]+<[^>]+>|[^\n]+)", text, flags=re.IGNORECASE)
    if from_match:
        return _trim_contact(from_match.group(1))

    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    return email_match.group(0) if email_match else ""


def _extract_location(text: str) -> str:
    patterns = [
        r"(?:location|standort|ort|city)\s*:\s*([A-ZÄÖÜ][A-Za-zÄÖÜäöüß .\-]{2,60})",
        r"(?:office|büro|buero)\s+(?:in|at)\s+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß .\-]{2,60})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = _trim_candidate(match.group(1))
            if candidate:
                return candidate

    for location in COMMON_LOCATIONS:
        if re.search(rf"\b{re.escape(location)}\b", text, flags=re.IGNORECASE):
            return location
    return ""


def _extract_first_url(text: str) -> str:
    match = re.search(r"https?://[^\s)>\]]+", text)
    return match.group(0).rstrip(".,") if match else ""


def _extract_context_date(text: str, keywords: tuple[str, ...]) -> str:
    candidates: list[tuple[int, int, str]] = []
    for iso_date, start, end in _find_dates(text):
        window_start = max(0, start - 100)
        context = text[window_start : min(len(text), end + 100)].casefold()
        for keyword in keywords:
            keyword_match = re.search(rf"\b{re.escape(keyword.casefold())}\b", context)
            if keyword_match:
                keyword_position = window_start + keyword_match.start()
                distance = min(abs(keyword_position - start), abs(keyword_position - end))
                candidates.append((distance, start, iso_date))

    return sorted(candidates)[0][2] if candidates else ""


def _extract_rejection_reason(text: str) -> str:
    normalized = _normalize_text(text)
    reason_rules = [
        ("Position closed or filled.", ("position has been filled", "position is filled", "position closed")),
        (
            "Other candidates were selected.",
            ("other candidates", "another candidate", "more suitable candidates", "more closely match"),
        ),
        (
            "Experience mismatch.",
            (
                "lack of experience",
                "not enough experience",
                "experience does not match",
                "does not meet our requirements",
            ),
        ),
        ("Language requirement mismatch.", ("german language", "language requirements", "sprachkenntnisse")),
        ("Visa or work authorization mismatch.", ("visa", "work permit", "work authorization", "arbeitserlaubnis")),
    ]
    for reason, patterns in reason_rules:
        if any(pattern in normalized for pattern in patterns):
            return reason

    rejection_keywords = (
        "unfortunately",
        "not proceed",
        "not moving forward",
        "decided not to continue",
        "we regret",
        "leider",
        "absage",
    )
    for sentence in _split_sentences(text):
        if any(keyword in sentence.casefold() for keyword in rejection_keywords):
            return _trim_sentence(sentence)
    return ""


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

    return sorted(set(matches), key=lambda value: value[1])


def _safe_iso_date(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat() if 1 <= year <= 2100 else ""
    except ValueError:
        return ""


def _company_from_domain(domain: str) -> str:
    domain_parts = domain.lower().split(".")
    candidate = ""
    for part in domain_parts:
        if part and part not in GENERIC_EMAIL_DOMAINS and part not in {"com", "de", "net", "org", "io", "eu"}:
            candidate = part
            break
    return candidate.upper() if len(candidate) <= 3 else candidate.title()


def _trim_candidate(value: str) -> str:
    candidate = re.split(r"[\n\r|,.;:<>]", value.strip())[0].strip(" -")
    candidate = re.sub(r"\s+", " ", candidate)
    return candidate[:80]


def _trim_contact(value: str) -> str:
    contact = re.split(r"[\n\r]", value.strip(), maxsplit=1)[0]
    contact = re.sub(r"\s+", " ", contact)
    return contact[:120]


def _trim_role(value: str) -> str:
    candidate = re.split(
        r"\s+(?:at|with|in|for our|bei)\s+[A-Z][A-Za-z0-9&.+\- ]{1,60}",
        value.strip(),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    candidate = re.split(r"[\n\r.;]", candidate, maxsplit=1)[0]
    candidate = re.sub(r"\s+", " ", candidate).strip(" -")
    return candidate[:120]


def _trim_sentence(value: str) -> str:
    sentence = re.sub(r"\s+", " ", value).strip(" -")
    return sentence[:180]


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    return bool(normalized_phrase) and normalized_phrase in text


def _role_similarity(left: str, right: str) -> float:
    left_tokens = _important_tokens(left)
    right_tokens = _important_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _important_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z0-9]+", _normalize_text(value))
        if len(token) >= 3 and token not in ROLE_STOP_WORDS
    }


def _identity(value: str) -> str:
    return " ".join(re.findall(r"[a-zA-Z0-9]+", value.casefold()))


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _clean_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")
