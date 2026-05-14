from __future__ import annotations

import re
from typing import Any

MIN_FEEDBACK_SIMILARITY = 0.45

TOKEN_STOP_WORDS = {
    "about",
    "application",
    "bewerbung",
    "career",
    "hello",
    "ihre",
    "regarding",
    "recruiting",
    "subject",
    "thank",
    "thanks",
    "their",
    "there",
    "update",
    "with",
    "your",
}


def build_email_signature(subject: str, body: str, details: dict[str, str] | None = None) -> str:
    detail_text = ""
    if details:
        detail_text = " ".join(
            [
                details.get("company", ""),
                details.get("role", ""),
                details.get("contact", ""),
                details.get("source_link", ""),
            ]
        )
    tokens = _important_tokens(f"{subject} {body} {detail_text}")
    return " ".join(sorted(tokens))


def find_best_email_feedback(
    subject: str,
    body: str,
    details: dict[str, str],
    feedback_rows: list[dict[str, Any]],
    minimum_similarity: float = MIN_FEEDBACK_SIMILARITY,
) -> dict[str, Any] | None:
    signature = build_email_signature(subject, body, details)
    if not signature:
        return None

    signature_tokens = set(signature.split())
    best_feedback: dict[str, Any] | None = None
    best_similarity = 0.0

    for row in feedback_rows:
        row_signature = str(row.get("email_signature", "") or "")
        row_tokens = set(row_signature.split())
        similarity = _jaccard_similarity(signature_tokens, row_tokens)
        if similarity > best_similarity:
            best_feedback = {**row, "similarity": similarity}
            best_similarity = similarity

    if best_feedback is None or best_similarity < minimum_similarity:
        return None
    return best_feedback


def apply_feedback_to_classification(
    classification: dict[str, Any],
    feedback: dict[str, Any] | None,
) -> dict[str, Any]:
    if not feedback:
        return classification

    corrected_category = str(feedback.get("corrected_category") or "").strip()
    corrected_status = str(feedback.get("corrected_status") or "").strip()
    if not corrected_category and not corrected_status:
        return classification

    updated = {**classification}
    if corrected_category:
        updated["category"] = corrected_category
    if corrected_status:
        updated["suggested_status"] = corrected_status
    updated["confidence"] = max(float(updated.get("confidence") or 0), 0.96)
    updated["matched_keywords"] = _feedback_keywords(updated)
    updated["feedback_override"] = True
    updated["feedback_similarity"] = round(float(feedback.get("similarity") or 0), 2)
    updated["feedback_id"] = feedback.get("id")
    return updated


def apply_feedback_to_match(
    match: dict[str, Any] | None,
    match_candidates: list[dict[str, Any]],
    feedback: dict[str, Any] | None,
    applications: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not feedback or not feedback.get("corrected_application_id"):
        return match, match_candidates

    application_id = int(feedback["corrected_application_id"])
    application = next((item for item in applications if int(item.get("id") or 0) == application_id), None)
    if not application:
        return match, match_candidates

    feedback_match = {
        "application_id": application_id,
        "company": application.get("company", ""),
        "role": application.get("role", ""),
        "score": 99,
        "confidence": 0.98,
        "reasons": [
            "manual feedback matched a similar previous email",
            f"feedback similarity {float(feedback.get('similarity') or 0):.0%}",
        ],
        "strong_match": True,
        "feedback_override": True,
        "signals": {"company": 6, "role": 7, "domain": 0, "status": 2},
    }

    other_candidates = [
        candidate for candidate in match_candidates if int(candidate.get("application_id") or 0) != application_id
    ]
    return feedback_match, [feedback_match, *other_candidates]


def _feedback_keywords(classification: dict[str, Any]) -> list[str]:
    existing = [str(keyword) for keyword in classification.get("matched_keywords", [])]
    marker = "manual feedback override"
    return [marker, *[keyword for keyword in existing if keyword != marker]]


def _important_tokens(value: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[\w-]+", value.casefold()):
        cleaned = re.sub(r"(^[^\w]+|[^\w]+$)", "", token).strip("_-")
        if len(cleaned) >= 3 and cleaned not in TOKEN_STOP_WORDS:
            tokens.add(cleaned)
    return tokens


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
