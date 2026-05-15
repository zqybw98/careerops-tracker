from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict, cast

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class ConfigValidationError(ValueError):
    """Raised when a JSON configuration file has an invalid shape."""


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


def validate_email_classification_config(raw_config: object) -> EmailClassificationConfig:
    config = _require_mapping(raw_config, "email_classification")
    _require_keys(
        config,
        {"category_rules", "default_classification", "confidence"},
        "email_classification",
    )

    category_rules = _require_non_empty_list(
        config["category_rules"],
        "email_classification.category_rules",
    )
    for index, rule in enumerate(category_rules):
        _validate_email_category_rule(
            rule,
            f"email_classification.category_rules[{index}]",
        )

    _validate_default_classification(
        config["default_classification"],
        "email_classification.default_classification",
    )
    _validate_confidence_config(
        config["confidence"],
        "email_classification.confidence",
    )
    return cast(EmailClassificationConfig, config)


def get_email_classification_config() -> EmailClassificationConfig:
    return validate_email_classification_config(_load_json_config("email_classification_rules.json"))


def get_email_parser_config() -> EmailParserConfig:
    return cast(EmailParserConfig, _load_json_config("email_parser_rules.json"))


def get_reminder_config() -> ReminderConfig:
    return cast(ReminderConfig, _load_json_config("reminder_rules.json"))


def get_job_post_config() -> JobPostConfig:
    return cast(JobPostConfig, _load_json_config("job_post_rules.json"))


def _validate_email_category_rule(raw_rule: object, path: str) -> None:
    rule = _require_mapping(raw_rule, path)
    _require_keys(
        rule,
        {
            "category",
            "priority",
            "suggested_status",
            "suggested_next_action",
            "suggested_follow_up_days",
            "keywords",
        },
        path,
    )
    _require_string(rule["category"], f"{path}.category")
    _require_int(rule["priority"], f"{path}.priority", minimum=0)
    _require_string(rule["suggested_status"], f"{path}.suggested_status")
    _require_string(rule["suggested_next_action"], f"{path}.suggested_next_action")
    _require_optional_int(
        rule["suggested_follow_up_days"],
        f"{path}.suggested_follow_up_days",
        minimum=0,
    )
    _require_string_list(rule["keywords"], f"{path}.keywords", require_non_empty=True)


def _validate_default_classification(raw_default: object, path: str) -> None:
    default = _require_mapping(raw_default, path)
    _require_keys(
        default,
        {
            "category",
            "confidence",
            "suggested_status",
            "suggested_next_action",
            "suggested_follow_up_days",
        },
        path,
    )
    _require_string(default["category"], f"{path}.category")
    _require_probability(default["confidence"], f"{path}.confidence")
    _require_string(default["suggested_status"], f"{path}.suggested_status")
    _require_string(default["suggested_next_action"], f"{path}.suggested_next_action")
    _require_optional_int(
        default["suggested_follow_up_days"],
        f"{path}.suggested_follow_up_days",
        minimum=0,
    )


def _validate_confidence_config(raw_confidence: object, path: str) -> None:
    confidence = _require_mapping(raw_confidence, path)
    _require_keys(confidence, {"base", "per_score", "maximum"}, path)

    base = _require_probability(confidence["base"], f"{path}.base")
    _require_probability(confidence["per_score"], f"{path}.per_score")
    maximum = _require_probability(confidence["maximum"], f"{path}.maximum")
    if base > maximum:
        raise ConfigValidationError(f"{path}.base must be less than or equal to {path}.maximum")


def _require_mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{path} must be an object")
    return cast(dict[str, Any], value)


def _require_keys(config: dict[str, Any], required_keys: set[str], path: str) -> None:
    missing = sorted(required_keys - set(config))
    if missing:
        missing_keys = ", ".join(missing)
        raise ConfigValidationError(f"{path} is missing required key(s): {missing_keys}")


def _require_non_empty_list(value: object, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfigValidationError(f"{path} must be a list")
    if not value:
        raise ConfigValidationError(f"{path} must not be empty")
    return value


def _require_string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise ConfigValidationError(f"{path} must be a string")
    if not value.strip():
        raise ConfigValidationError(f"{path} must not be empty")
    return value


def _require_int(value: object, path: str, *, minimum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigValidationError(f"{path} must be an integer")
    if minimum is not None and value < minimum:
        raise ConfigValidationError(f"{path} must be greater than or equal to {minimum}")
    return value


def _require_optional_int(value: object, path: str, *, minimum: int | None = None) -> int | None:
    if value is None:
        return None
    return _require_int(value, path, minimum=minimum)


def _require_probability(value: object, path: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ConfigValidationError(f"{path} must be a number")
    number = float(value)
    if number < 0 or number > 1:
        raise ConfigValidationError(f"{path} must be between 0 and 1")
    return number


def _require_string_list(
    value: object,
    path: str,
    *,
    require_non_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise ConfigValidationError(f"{path} must be a list")
    if require_non_empty and not value:
        raise ConfigValidationError(f"{path} must not be empty")
    for index, item in enumerate(value):
        _require_string(item, f"{path}[{index}]")
    return cast(list[str], value)
