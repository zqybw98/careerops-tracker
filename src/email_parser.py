from __future__ import annotations

import re
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


def extract_application_details(subject: str = "", body: str = "") -> dict[str, str]:
    text = _clean_text(f"{subject}\n{body}")
    return {
        "company": _extract_company(text),
        "role": _extract_role(text),
        "contact": _extract_contact(text),
        "source_link": _extract_first_url(text),
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
        r"(?:application|applied)\s+(?:for|as)\s+(.{3,120})",
        r"(?:position|role|job)\s+(?:of|as|for)\s+(.{3,120})",
        r"(?:position|role|job)\s*:\s*(.{3,120})",
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


def _extract_first_url(text: str) -> str:
    match = re.search(r"https?://[^\s)>\]]+", text)
    return match.group(0).rstrip(".,") if match else ""


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
