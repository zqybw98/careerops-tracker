from __future__ import annotations

import re
from datetime import date
from typing import Any
from urllib.parse import urlparse

from src.config_loader import get_email_parser_config
from src.models import CLOSED_STATUSES

PARSER_CONFIG = get_email_parser_config()
MATCH_THRESHOLD = PARSER_CONFIG["match_thresholds"]["auto_match"]
SUGGESTED_MATCH_THRESHOLD = PARSER_CONFIG["match_thresholds"]["suggested_match"]
AMBIGUOUS_MATCH_MARGIN = PARSER_CONFIG["match_thresholds"]["ambiguous_margin"]
GENERIC_EMAIL_DOMAINS = set(PARSER_CONFIG["generic_email_domains"])
ROLE_STOP_WORDS = set(PARSER_CONFIG["role_stop_words"])
COMMON_LOCATIONS = PARSER_CONFIG["common_locations"]
MONTH_LOOKUP = PARSER_CONFIG["month_lookup"]
DEADLINE_KEYWORDS = tuple(PARSER_CONFIG["date_context_keywords"]["deadline"])
INTERVIEW_DATE_KEYWORDS = tuple(PARSER_CONFIG["date_context_keywords"]["interview"])


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
    sorted_matches = rank_application_matches_from_email(
        applications,
        subject=subject,
        body=body,
        extracted_details=extracted_details,
        limit=max(len(applications), 1),
        minimum_score=MATCH_THRESHOLD,
    )
    if not sorted_matches:
        return None

    if len(sorted_matches) > 1 and _is_ambiguous_match(sorted_matches[0], sorted_matches[1]):
        return None

    return sorted_matches[0]


def rank_application_matches_from_email(
    applications: list[dict[str, Any]],
    subject: str = "",
    body: str = "",
    extracted_details: dict[str, str] | None = None,
    limit: int = 3,
    minimum_score: int = SUGGESTED_MATCH_THRESHOLD,
) -> list[dict[str, Any]]:
    if not applications or limit <= 0:
        return []

    details = extracted_details or extract_application_details(subject, body)
    raw_email_text = _clean_text(f"{subject}\n{body}")
    normalized_text = _normalize_text(f"{raw_email_text} {details.get('company', '')} {details.get('role', '')}")
    scored_matches = [
        _score_application_match(application, raw_email_text, normalized_text, details) for application in applications
    ]
    suggested_matches = [match for match in scored_matches if match["score"] >= minimum_score]
    return sorted(suggested_matches, key=_match_sort_key, reverse=True)[:limit]


def _score_application_match(
    application: dict[str, Any],
    raw_email_text: str,
    normalized_email_text: str,
    details: dict[str, str],
) -> dict[str, Any]:
    company = str(application.get("company", ""))
    role = str(application.get("role", ""))
    score = 0
    company_signal = 0
    role_signal = 0
    domain_signal = 0
    status_signal = 0
    reasons: list[str] = []

    if _contains_phrase(normalized_email_text, company):
        company_signal = 6
        score += company_signal
        reasons.append("company name appears in email")
    elif details.get("company"):
        company_similarity = _token_similarity(details["company"], company)
        if _identity(details["company"]) == _identity(company):
            company_signal = 6
            score += company_signal
            reasons.append("extracted company matches existing application")
        elif company_similarity >= 0.6:
            company_signal = 4
            score += company_signal
            reasons.append("extracted company is similar to existing application")

    if _contains_phrase(normalized_email_text, role):
        role_signal = 7
        score += role_signal
        reasons.append("role title appears in email")
    elif details.get("role"):
        extracted_role_similarity = _role_similarity(details["role"], role)
        if extracted_role_similarity >= 0.8:
            role_signal = 6
            score += role_signal
            reasons.append("extracted role strongly matches existing role")
        elif extracted_role_similarity >= 0.5:
            role_signal = 4
            score += role_signal
            reasons.append("extracted role is similar to existing role")

    overlap = _role_similarity(role, normalized_email_text)
    if overlap >= 0.6:
        role_signal = max(role_signal, 4)
        score += 4
        reasons.append("strong role keyword overlap with email text")
    elif overlap >= 0.4:
        role_signal = max(role_signal, 2)
        score += 2
        reasons.append("role keywords overlap with email text")

    domain_score, domain_reasons = _score_domain_match(application, raw_email_text, details)
    domain_signal = domain_score
    score += domain_score
    reasons.extend(domain_reasons)

    status_score, status_reasons = _score_status_context(application, normalized_email_text, details)
    status_signal = status_score
    score += status_score
    reasons.extend(status_reasons)

    if details.get("location") and _identity(details["location"]) == _identity(str(application.get("location", ""))):
        score += 1
        reasons.append("location matches existing application")

    score = max(score, 0)
    confidence = min(0.95, round(score / 18, 2))
    strong_match = (company_signal >= 4 and role_signal >= 4) or (domain_signal >= 3 and role_signal >= 4)

    return {
        "application_id": application.get("id"),
        "company": company,
        "role": role,
        "score": score,
        "confidence": confidence,
        "reasons": reasons,
        "strong_match": strong_match,
        "signals": {
            "company": company_signal,
            "role": role_signal,
            "domain": domain_signal,
            "status": status_signal,
        },
    }


def _extract_company(text: str) -> str:
    patterns = PARSER_CONFIG["extraction_patterns"]["company"]
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


def _match_sort_key(match: dict[str, Any]) -> tuple[int, bool, int]:
    return (
        int(match["score"]),
        bool(match.get("strong_match")),
        int(match.get("application_id") or 0),
    )


def _is_ambiguous_match(top_match: dict[str, Any], second_match: dict[str, Any]) -> bool:
    margin = int(top_match["score"]) - int(second_match["score"])
    return margin < AMBIGUOUS_MATCH_MARGIN and not bool(top_match.get("strong_match"))


def _score_domain_match(
    application: dict[str, Any],
    raw_email_text: str,
    details: dict[str, str],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    email_domains = _email_domains(raw_email_text, details)
    application_domains = _application_domains(application)

    if email_domains and application_domains and email_domains & application_domains:
        score += 4
        reasons.append("email domain matches existing source or contact domain")

    company = str(application.get("company", ""))
    for domain in email_domains:
        if _domain_matches_company(domain, company):
            score += 3
            reasons.append("sender or source domain matches company identity")
            break

    return score, reasons


def _score_status_context(
    application: dict[str, Any],
    normalized_email_text: str,
    details: dict[str, str],
) -> tuple[int, list[str]]:
    intent = _infer_email_intent(normalized_email_text, details)
    status = str(application.get("status", "") or "Applied")
    if not intent:
        return 0, []

    if intent == "rejection":
        if status in CLOSED_STATUSES:
            return -1, ["application is already closed"]
        return 2, ["email outcome can close an active application"]

    if status in CLOSED_STATUSES:
        return -3, ["closed application is less likely for this email"]

    if intent == "interview" and status in {"Applied", "Confirmation Received", "Follow-up Needed"}:
        return 2, ["interview email fits an active application"]
    if intent == "assessment" and status in {"Applied", "Confirmation Received", "Follow-up Needed"}:
        return 2, ["assessment email fits an active application"]
    if intent == "confirmation" and status in {"Saved", "Applied"}:
        return 1, ["confirmation email fits an early-stage application"]
    return 0, []


def _infer_email_intent(normalized_email_text: str, details: dict[str, str]) -> str:
    intent_keywords = PARSER_CONFIG["intent_keywords"]
    if details.get("rejection_reason") or any(
        keyword in normalized_email_text for keyword in intent_keywords["rejection"]
    ):
        return "rejection"

    if details.get("interview_date") or any(
        keyword in normalized_email_text for keyword in intent_keywords["interview"]
    ):
        return "interview"

    if any(keyword in normalized_email_text for keyword in intent_keywords["assessment"]):
        return "assessment"

    if any(keyword in normalized_email_text for keyword in intent_keywords["confirmation"]):
        return "confirmation"

    return ""


def _extract_role(text: str) -> str:
    patterns = PARSER_CONFIG["extraction_patterns"]["role"]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = _trim_role(match.group(1))
            if candidate:
                return candidate
    return ""


def _extract_contact(text: str) -> str:
    from_match = re.search(r"(?:from|sender|von|发件人)\s*[:：]\s*([^\n<]+<[^>]+>|[^\n]+)", text, flags=re.IGNORECASE)
    if from_match:
        return _trim_contact(from_match.group(1))

    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    return email_match.group(0) if email_match else ""


def _extract_location(text: str) -> str:
    patterns = PARSER_CONFIG["extraction_patterns"]["location"]
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


def _email_domains(raw_email_text: str, details: dict[str, str]) -> set[str]:
    domains: set[str] = set()
    for value in [
        raw_email_text,
        details.get("contact", ""),
        details.get("source_link", ""),
    ]:
        domains.update(_extract_domains_from_value(value))
    return domains


def _application_domains(application: dict[str, Any]) -> set[str]:
    domains: set[str] = set()
    for key in ["contact", "source_link"]:
        domains.update(_extract_domains_from_value(str(application.get(key, "") or "")))
    return domains


def _extract_domains_from_value(value: str) -> set[str]:
    domains = {_normalize_domain(match.group(1)) for match in re.finditer(r"[\w.+-]+@([\w.-]+\.[A-Za-z]{2,})", value)}

    for match in re.finditer(r"https?://[^\s)>\]]+", value):
        parsed = urlparse(match.group(0).rstrip(".,"))
        if parsed.netloc:
            domains.add(_normalize_domain(parsed.netloc))

    return {domain for domain in domains if domain}


def _normalize_domain(domain: str) -> str:
    return domain.casefold().removeprefix("www.").split(":", 1)[0].strip()


def _domain_matches_company(domain: str, company: str) -> bool:
    domain_company = _domain_company_identity(domain)
    if not domain_company:
        return False

    company_identity = _identity(company)
    return domain_company in company_identity or _token_similarity(domain_company, company_identity) >= 0.5


def _domain_company_identity(domain: str) -> str:
    ignored_parts = {"com", "de", "net", "org", "io", "eu"}
    for part in domain.casefold().split("."):
        candidate = re.sub(r"[^a-z0-9]+", " ", part).strip()
        if candidate and candidate not in GENERIC_EMAIL_DOMAINS and candidate not in ignored_parts:
            return _identity(candidate)
    return ""


def _extract_context_date(text: str, keywords: tuple[str, ...]) -> str:
    candidates: list[tuple[int, int, str]] = []
    for iso_date, start, end in _find_dates(text):
        window_start = max(0, start - 100)
        context = text[window_start : min(len(text), end + 100)].casefold()
        for keyword in keywords:
            keyword_position_in_context = _keyword_position(context, keyword.casefold())
            if keyword_position_in_context is not None:
                keyword_position = window_start + keyword_position_in_context
                distance = start - keyword_position if keyword_position <= start else keyword_position - end + 50
                candidates.append((distance, start, iso_date))

    return sorted(candidates)[0][2] if candidates else ""


def _keyword_position(text: str, keyword: str) -> int | None:
    if re.search(r"[^\x00-\x7F]", keyword):
        position = text.find(keyword)
        return position if position >= 0 else None

    keyword_match = re.search(rf"\b{re.escape(keyword)}\b", text)
    return keyword_match.start() if keyword_match else None


def _extract_rejection_reason(text: str) -> str:
    normalized = _normalize_text(text)
    reason_rules = PARSER_CONFIG["rejection_reason_rules"]
    for rule in reason_rules:
        if any(pattern in normalized for pattern in rule["patterns"]):
            return rule["reason"]

    rejection_keywords = PARSER_CONFIG["rejection_sentence_keywords"]
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

    for match in re.finditer(r"(20\d{2})年(\d{1,2})月(\d{1,2})日?", text):
        iso_date = _safe_iso_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
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
    candidate = re.split(r"[\n\r.;。；]", candidate, maxsplit=1)[0]
    candidate = re.sub(r"\s+", " ", candidate).strip(" -")
    return candidate[:120]


def _trim_sentence(value: str) -> str:
    sentence = re.sub(r"\s+", " ", value).strip(" -")
    return sentence[:180]


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?。！？])\s*|\n+", text) if part.strip()]


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    return bool(normalized_phrase) and normalized_phrase in text


def _role_similarity(left: str, right: str) -> float:
    left_tokens = _important_tokens(left)
    right_tokens = _important_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def _token_similarity(left: str, right: str) -> float:
    left_tokens = _important_tokens(left)
    right_tokens = _important_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


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
