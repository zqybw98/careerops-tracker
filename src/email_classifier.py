from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, TypedDict

from src.config_loader import EmailCategoryRule, get_email_classification_config
from src.models import EmailClassification


class ClassificationMatch(TypedDict):
    rule: EmailCategoryRule
    matched_keywords: list[str]
    score: int


CLASSIFICATION_CONFIG = get_email_classification_config()
CATEGORY_RULES = CLASSIFICATION_CONFIG["category_rules"]


def classify_email(subject: str = "", body: str = "") -> dict[str, Any]:
    text = _normalize_text(f"{subject}\n{body}")
    subject_text = _normalize_text(subject)

    best_result: ClassificationMatch | None = None
    for rule in CATEGORY_RULES:
        matched = _matched_keywords(text, rule["keywords"])
        if not matched:
            continue

        score = len(matched)
        score += sum(1 for keyword in matched if keyword in subject_text)
        score += sum(1 for keyword in matched if len(keyword.split()) >= 3)

        result: ClassificationMatch = {
            "rule": rule,
            "matched_keywords": matched,
            "score": score,
        }
        if best_result is None or _is_better_result(result, best_result):
            best_result = result

    if best_result is None:
        default = CLASSIFICATION_CONFIG["default_classification"]
        return asdict(
            EmailClassification(
                category=default["category"],
                confidence=default["confidence"],
                suggested_status=default["suggested_status"],
                suggested_next_action=default["suggested_next_action"],
                suggested_follow_up_days=default["suggested_follow_up_days"],
                matched_keywords=[],
            )
        )

    rule = best_result["rule"]
    confidence_config = CLASSIFICATION_CONFIG["confidence"]
    confidence = min(
        confidence_config["maximum"],
        confidence_config["base"] + best_result["score"] * confidence_config["per_score"],
    )
    return asdict(
        EmailClassification(
            category=rule["category"],
            confidence=round(confidence, 2),
            suggested_status=rule["suggested_status"],
            suggested_next_action=rule["suggested_next_action"],
            suggested_follow_up_days=rule["suggested_follow_up_days"],
            matched_keywords=best_result["matched_keywords"],
        )
    )


def _matched_keywords(text: str, keywords: list[str]) -> list[str]:
    matches = []
    for keyword in keywords:
        normalized_keyword = _normalize_text(keyword)
        if _keyword_matches(text, normalized_keyword):
            matches.append(keyword)
    return matches


def _keyword_matches(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    if re.search(r"[^\x00-\x7F]", keyword):
        return keyword in text
    pattern = rf"\b{re.escape(keyword)}\b"
    return bool(re.search(pattern, text))


def _is_better_result(candidate: ClassificationMatch, current: ClassificationMatch) -> bool:
    if candidate["score"] != current["score"]:
        return candidate["score"] > current["score"]
    return candidate["rule"]["priority"] > current["rule"]["priority"]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()
