from __future__ import annotations

import re
from dataclasses import asdict

from src.models import EmailClassification


CATEGORY_RULES = [
    {
        "category": "Interview Invitation",
        "priority": 3,
        "suggested_status": "Interview Scheduled",
        "suggested_next_action": "Confirm availability and prepare interview notes.",
        "suggested_follow_up_days": 1,
        "keywords": [
            "invite you to an interview",
            "interview invitation",
            "schedule an interview",
            "video interview",
            "phone interview",
            "technical interview",
            "would like to meet",
            "availability for a call",
            "gespraech",
            "interview",
        ],
    },
    {
        "category": "Assessment / Coding Test",
        "priority": 4,
        "suggested_status": "Assessment",
        "suggested_next_action": "Review the assessment instructions and deadline.",
        "suggested_follow_up_days": 2,
        "keywords": [
            "coding challenge",
            "coding test",
            "technical assessment",
            "online assessment",
            "case study",
            "take-home",
            "home assignment",
            "testaufgabe",
            "assessment",
        ],
    },
    {
        "category": "Rejection",
        "priority": 5,
        "suggested_status": "Rejected",
        "suggested_next_action": "Close the application and capture useful notes.",
        "suggested_follow_up_days": None,
        "keywords": [
            "unfortunately",
            "not proceed",
            "not moving forward",
            "decided not to continue",
            "other candidates",
            "after careful consideration",
            "we regret",
            "leider",
            "absage",
        ],
    },
    {
        "category": "Application Confirmation",
        "priority": 2,
        "suggested_status": "Confirmation Received",
        "suggested_next_action": "Wait for the next response and follow up if needed.",
        "suggested_follow_up_days": 7,
        "keywords": [
            "thank you for your application",
            "received your application",
            "application has been received",
            "we have received",
            "your application was submitted",
            "eingang ihrer bewerbung",
            "bewerbung erhalten",
            "application confirmation",
        ],
    },
    {
        "category": "Recruiter Reply",
        "priority": 2,
        "suggested_status": "Follow-up Needed",
        "suggested_next_action": "Review the recruiter message and respond if action is required.",
        "suggested_follow_up_days": 2,
        "keywords": [
            "talent acquisition",
            "recruiter",
            "quick chat",
            "screening call",
            "could you share",
            "please send",
            "availability",
            "next steps",
        ],
    },
    {
        "category": "Follow-up Needed",
        "priority": 1,
        "suggested_status": "Follow-up Needed",
        "suggested_next_action": "Send or prepare a polite follow-up message.",
        "suggested_follow_up_days": 0,
        "keywords": [
            "following up",
            "checking in",
            "status of my application",
            "have not heard back",
            "haven't heard back",
            "any update",
        ],
    },
]


def classify_email(subject: str = "", body: str = "") -> dict:
    text = _normalize_text(f"{subject}\n{body}")
    subject_text = _normalize_text(subject)

    best_result: dict | None = None
    for rule in CATEGORY_RULES:
        matched = _matched_keywords(text, rule["keywords"])
        if not matched:
            continue

        score = len(matched)
        score += sum(1 for keyword in matched if keyword in subject_text)
        score += sum(1 for keyword in matched if len(keyword.split()) >= 3)

        result = {
            "rule": rule,
            "matched_keywords": matched,
            "score": score,
        }
        if best_result is None or _is_better_result(result, best_result):
            best_result = result

    if best_result is None:
        return asdict(
            EmailClassification(
                category="Other",
                confidence=0.2,
                suggested_status="Applied",
                suggested_next_action="Review manually and decide whether the application needs an update.",
                suggested_follow_up_days=None,
                matched_keywords=[],
            )
        )

    rule = best_result["rule"]
    confidence = min(0.95, 0.45 + best_result["score"] * 0.12)
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
        pattern = rf"\b{re.escape(_normalize_text(keyword))}\b"
        if re.search(pattern, text):
            matches.append(keyword)
    return matches


def _is_better_result(candidate: dict, current: dict) -> bool:
    if candidate["score"] != current["score"]:
        return candidate["score"] > current["score"]
    return candidate["rule"]["priority"] > current["rule"]["priority"]


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()
