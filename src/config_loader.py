from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict, cast

from src.models import STATUS_OPTIONS

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
    return validate_email_parser_config(_load_json_config("email_parser_rules.json"))


def get_reminder_config() -> ReminderConfig:
    return validate_reminder_config(_load_json_config("reminder_rules.json"))


def get_job_post_config() -> JobPostConfig:
    return validate_job_post_config(_load_json_config("job_post_rules.json"))


def validate_email_parser_config(raw_config: object) -> EmailParserConfig:
    config = _require_mapping(raw_config, "email_parser")
    _require_keys(
        config,
        {
            "match_thresholds",
            "generic_email_domains",
            "role_stop_words",
            "common_locations",
            "month_lookup",
            "date_context_keywords",
            "extraction_patterns",
            "intent_keywords",
            "rejection_reason_rules",
            "rejection_sentence_keywords",
        },
        "email_parser",
    )

    _validate_match_thresholds(config["match_thresholds"], "email_parser.match_thresholds")
    _require_string_list(config["generic_email_domains"], "email_parser.generic_email_domains", require_non_empty=True)
    _require_string_list(config["role_stop_words"], "email_parser.role_stop_words", require_non_empty=True)
    _require_string_list(config["common_locations"], "email_parser.common_locations", require_non_empty=True)
    _validate_month_lookup(config["month_lookup"], "email_parser.month_lookup")
    _validate_required_string_list_mapping(
        config["date_context_keywords"],
        {"deadline", "interview"},
        "email_parser.date_context_keywords",
    )
    _validate_regex_pattern_mapping(
        config["extraction_patterns"],
        {"company", "role", "location"},
        "email_parser.extraction_patterns",
    )
    _validate_required_string_list_mapping(
        config["intent_keywords"],
        {"rejection", "interview", "assessment", "confirmation"},
        "email_parser.intent_keywords",
    )
    _validate_rejection_reason_rules(
        config["rejection_reason_rules"],
        "email_parser.rejection_reason_rules",
    )
    _require_string_list(
        config["rejection_sentence_keywords"],
        "email_parser.rejection_sentence_keywords",
        require_non_empty=True,
    )
    return cast(EmailParserConfig, config)


def validate_reminder_config(raw_config: object) -> ReminderConfig:
    config = _require_mapping(raw_config, "reminder")
    _require_keys(config, {"priority_order", "rules"}, "reminder")

    priority_order = _require_string_int_mapping(
        config["priority_order"],
        "reminder.priority_order",
        minimum=0,
    )
    rules = _require_mapping(config["rules"], "reminder.rules")
    _require_keys(
        rules,
        {
            "follow_up_due",
            "interview_preparation",
            "assessment_deadline",
            "stale_application",
            "weekly_follow_up",
            "saved_role",
        },
        "reminder.rules",
    )
    for rule_name, raw_rule in rules.items():
        _validate_reminder_rule(
            raw_rule,
            f"reminder.rules.{rule_name}",
            priority_order=priority_order,
        )
    return cast(ReminderConfig, config)


def validate_job_post_config(raw_config: object) -> JobPostConfig:
    config = _require_mapping(raw_config, "job_post")
    _require_keys(
        config,
        {
            "default_status",
            "job_board_domains",
            "common_locations",
            "role_keywords",
            "role_stop_lines",
            "extraction_patterns",
            "deadline_keywords",
            "month_lookup",
            "next_actions",
        },
        "job_post",
    )

    _require_status(config["default_status"], "job_post.default_status")
    _require_string_list(config["job_board_domains"], "job_post.job_board_domains", require_non_empty=True)
    _require_string_list(config["common_locations"], "job_post.common_locations", require_non_empty=True)
    _require_string_list(config["role_keywords"], "job_post.role_keywords", require_non_empty=True)
    _require_string_list(config["role_stop_lines"], "job_post.role_stop_lines", require_non_empty=True)
    _validate_regex_pattern_mapping(
        config["extraction_patterns"],
        {"company", "role", "location"},
        "job_post.extraction_patterns",
    )
    _require_string_list(config["deadline_keywords"], "job_post.deadline_keywords", require_non_empty=True)
    _validate_month_lookup(config["month_lookup"], "job_post.month_lookup")
    _validate_required_string_mapping(
        config["next_actions"],
        {"with_deadline", "with_source", "default"},
        "job_post.next_actions",
    )
    return cast(JobPostConfig, config)


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


def _validate_match_thresholds(raw_thresholds: object, path: str) -> None:
    thresholds = _require_mapping(raw_thresholds, path)
    _require_keys(thresholds, {"auto_match", "suggested_match", "ambiguous_margin"}, path)
    auto_match = _require_int(thresholds["auto_match"], f"{path}.auto_match", minimum=0)
    suggested_match = _require_int(thresholds["suggested_match"], f"{path}.suggested_match", minimum=0)
    _require_int(thresholds["ambiguous_margin"], f"{path}.ambiguous_margin", minimum=0)
    if auto_match < suggested_match:
        raise ConfigValidationError(f"{path}.auto_match must be greater than or equal to {path}.suggested_match")


def _validate_month_lookup(raw_month_lookup: object, path: str) -> None:
    month_lookup = _require_string_int_mapping(raw_month_lookup, path, minimum=1)
    for month_name, month_number in month_lookup.items():
        if month_number > 12:
            raise ConfigValidationError(f"{path}.{month_name} must be between 1 and 12")


def _validate_required_string_list_mapping(
    raw_mapping: object,
    required_keys: set[str],
    path: str,
) -> None:
    mapping = _require_mapping(raw_mapping, path)
    _require_keys(mapping, required_keys, path)
    for key in required_keys:
        _require_string_list(mapping[key], f"{path}.{key}", require_non_empty=True)


def _validate_required_string_mapping(
    raw_mapping: object,
    required_keys: set[str],
    path: str,
) -> None:
    mapping = _require_mapping(raw_mapping, path)
    _require_keys(mapping, required_keys, path)
    for key in required_keys:
        _require_string(mapping[key], f"{path}.{key}")


def _validate_regex_pattern_mapping(
    raw_mapping: object,
    required_keys: set[str],
    path: str,
) -> None:
    mapping = _require_mapping(raw_mapping, path)
    _require_keys(mapping, required_keys, path)
    for key in required_keys:
        patterns = _require_string_list(mapping[key], f"{path}.{key}", require_non_empty=True)
        _validate_regex_patterns(patterns, f"{path}.{key}")


def _validate_regex_patterns(patterns: list[str], path: str) -> None:
    for index, pattern in enumerate(patterns):
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigValidationError(f"{path}[{index}] must be a valid regex pattern: {exc}") from exc


def _validate_rejection_reason_rules(raw_rules: object, path: str) -> None:
    rules = _require_non_empty_list(raw_rules, path)
    for index, raw_rule in enumerate(rules):
        rule_path = f"{path}[{index}]"
        rule = _require_mapping(raw_rule, rule_path)
        _require_keys(rule, {"reason", "patterns"}, rule_path)
        _require_string(rule["reason"], f"{rule_path}.reason")
        _require_string_list(rule["patterns"], f"{rule_path}.patterns", require_non_empty=True)


def _validate_reminder_rule(
    raw_rule: object,
    path: str,
    *,
    priority_order: dict[str, int],
) -> None:
    rule = _require_mapping(raw_rule, path)
    _require_keys(rule, {"priority", "message", "reason"}, path)
    priority = _require_string(rule["priority"], f"{path}.priority")
    if priority not in priority_order:
        raise ConfigValidationError(f"{path}.priority must be defined in reminder.priority_order")

    _require_string(rule["message"], f"{path}.message")
    _require_string(rule["reason"], f"{path}.reason")
    if "default_due_days" in rule:
        _require_int(rule["default_due_days"], f"{path}.default_due_days", minimum=0)
    if "minimum_days_open" in rule:
        _require_int(rule["minimum_days_open"], f"{path}.minimum_days_open", minimum=0)
    if "statuses" in rule:
        statuses = _require_string_list(rule["statuses"], f"{path}.statuses", require_non_empty=True)
        for index, status in enumerate(statuses):
            _require_status(status, f"{path}.statuses[{index}]")


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


def _require_status(value: object, path: str) -> str:
    status = _require_string(value, path)
    if status not in STATUS_OPTIONS:
        valid_statuses = ", ".join(STATUS_OPTIONS)
        raise ConfigValidationError(f"{path} must be one of: {valid_statuses}")
    return status


def _require_string_int_mapping(value: object, path: str, *, minimum: int | None = None) -> dict[str, int]:
    mapping = _require_mapping(value, path)
    if not mapping:
        raise ConfigValidationError(f"{path} must not be empty")
    for key, item in mapping.items():
        _require_string(key, f"{path} key")
        _require_int(item, f"{path}.{key}", minimum=minimum)
    return cast(dict[str, int], mapping)


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
