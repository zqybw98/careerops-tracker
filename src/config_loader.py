from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict, cast

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class EmailCategoryRule(TypedDict):
    category: str
    priority: int
    suggested_status: str
    suggested_next_action: str
    suggested_follow_up_days: int | None
    keywords: list[str]


class DefaultEmailClassification(TypedDict):
    category: str
    confidence: float
    suggested_status: str
    suggested_next_action: str
    suggested_follow_up_days: int | None


class ClassificationConfidenceConfig(TypedDict):
    base: float
    per_score: float
    maximum: float


class EmailClassificationConfig(TypedDict):
    category_rules: list[EmailCategoryRule]
    default_classification: DefaultEmailClassification
    confidence: ClassificationConfidenceConfig


class MatchThresholdConfig(TypedDict):
    auto_match: int
    suggested_match: int
    ambiguous_margin: int


class DateContextKeywordConfig(TypedDict):
    deadline: list[str]
    interview: list[str]


class ExtractionPatternConfig(TypedDict):
    company: list[str]
    role: list[str]
    location: list[str]


class IntentKeywordConfig(TypedDict):
    rejection: list[str]
    interview: list[str]
    assessment: list[str]
    confirmation: list[str]


class RejectionReasonRule(TypedDict):
    reason: str
    patterns: list[str]


class EmailParserConfig(TypedDict):
    match_thresholds: MatchThresholdConfig
    generic_email_domains: list[str]
    role_stop_words: list[str]
    common_locations: list[str]
    month_lookup: dict[str, int]
    date_context_keywords: DateContextKeywordConfig
    extraction_patterns: ExtractionPatternConfig
    intent_keywords: IntentKeywordConfig
    rejection_reason_rules: list[RejectionReasonRule]
    rejection_sentence_keywords: list[str]


class ReminderRule(TypedDict, total=False):
    priority: str
    message: str
    reason: str
    default_due_days: int
    minimum_days_open: int
    statuses: list[str]


class ReminderConfig(TypedDict):
    priority_order: dict[str, int]
    rules: dict[str, ReminderRule]


class JobPostExtractionPatternConfig(TypedDict):
    company: list[str]
    role: list[str]
    location: list[str]


class JobPostNextActionConfig(TypedDict):
    with_deadline: str
    with_source: str
    default: str


class JobPostConfig(TypedDict):
    default_status: str
    job_board_domains: list[str]
    common_locations: list[str]
    role_keywords: list[str]
    role_stop_lines: list[str]
    extraction_patterns: JobPostExtractionPatternConfig
    deadline_keywords: list[str]
    month_lookup: dict[str, int]
    next_actions: JobPostNextActionConfig


@lru_cache
def _load_json_config(filename: str) -> dict[str, Any]:
    config_path = CONFIG_DIR / filename
    with config_path.open(encoding="utf-8") as config_file:
        return cast(dict[str, Any], json.load(config_file))


def get_email_classification_config() -> EmailClassificationConfig:
    return cast(EmailClassificationConfig, _load_json_config("email_classification_rules.json"))


def get_email_parser_config() -> EmailParserConfig:
    return cast(EmailParserConfig, _load_json_config("email_parser_rules.json"))


def get_reminder_config() -> ReminderConfig:
    return cast(ReminderConfig, _load_json_config("reminder_rules.json"))


def get_job_post_config() -> JobPostConfig:
    return cast(JobPostConfig, _load_json_config("job_post_rules.json"))
