from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

COMPANY_NOISE_WORDS = {
    "ag",
    "gmbh",
    "logo",
    "inc",
    "ltd",
    "llc",
    "se",
    "kg",
    "co",
    "company",
    "group",
}

ROLE_NOISE_WORDS = {
    "m",
    "w",
    "d",
    "f",
    "div",
    "all",
    "gender",
}


def find_likely_duplicate_applications(
    payload: dict[str, Any],
    applications: list[dict[str, Any]],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    company = str(payload.get("company", "") or "")
    role = str(payload.get("role", "") or "")
    if not company or not role:
        return []

    candidates: list[dict[str, Any]] = []
    for application in applications:
        score, reason = _duplicate_score(company, role, application)
        if score >= 0.78:
            candidates.append({"application": application, "score": score, "reason": reason})

    return sorted(candidates, key=_candidate_score, reverse=True)[:limit]


def format_duplicate_candidate(candidate: dict[str, Any]) -> str:
    application = candidate["application"]
    score = float(candidate["score"])
    return f"{application.get('company', '')} / {application.get('role', '')} (#{application.get('id')}, {score:.0%})"


def _candidate_score(candidate: dict[str, Any]) -> float:
    return float(candidate.get("score") or 0.0)


def _duplicate_score(company: str, role: str, application: dict[str, Any]) -> tuple[float, str]:
    company_score = _text_similarity(_normalize_company(company), _normalize_company(application.get("company", "")))
    role_score = _token_similarity(_normalize_role(role), _normalize_role(application.get("role", "")))
    score = company_score * 0.55 + role_score * 0.45

    reason = f"company similarity {company_score:.0%}, position similarity {role_score:.0%}"
    return score, reason


def _normalize_company(value: object) -> str:
    tokens = _tokens(value)
    cleaned = [token.rstrip("s") for token in tokens if token not in COMPANY_NOISE_WORDS]
    return " ".join(cleaned)


def _normalize_role(value: object) -> str:
    tokens = _tokens(value)
    return " ".join(token for token in tokens if token not in ROLE_NOISE_WORDS)


def _tokens(value: object) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(value or "").casefold())


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right or left in right or right in left:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _token_similarity(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(None, left, right).ratio()
    return max(overlap, sequence)
