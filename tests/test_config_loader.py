from typing import Any

import pytest
from src.config_loader import (
    ConfigValidationError,
    get_email_classification_config,
    get_email_parser_config,
    get_job_post_config,
    get_reminder_config,
    validate_email_classification_config,
    validate_email_parser_config,
    validate_job_post_config,
    validate_reminder_config,
)


def test_loads_email_classification_rules_from_config() -> None:
    config = get_email_classification_config()

    categories = {rule["category"] for rule in config["category_rules"]}

    assert "Interview Invitation" in categories
    assert "Rejection" in categories
    assert config["default_classification"]["category"] == "Other"


def test_validates_missing_email_classification_keys() -> None:
    config = _valid_email_classification_config()
    del config["category_rules"]

    with pytest.raises(ConfigValidationError, match="category_rules"):
        validate_email_classification_config(config)


def test_validates_category_rule_keywords() -> None:
    config = _valid_email_classification_config()
    config["category_rules"][0]["keywords"] = []

    with pytest.raises(ConfigValidationError, match="category_rules\\[0\\]\\.keywords"):
        validate_email_classification_config(config)


def test_validates_confidence_range() -> None:
    config = _valid_email_classification_config()
    config["confidence"]["maximum"] = 1.5

    with pytest.raises(ConfigValidationError, match="maximum.*between 0 and 1"):
        validate_email_classification_config(config)


def test_loads_parser_rules_from_config() -> None:
    config = get_email_parser_config()

    assert config["match_thresholds"]["auto_match"] >= config["match_thresholds"]["suggested_match"]
    assert "Berlin" in config["common_locations"]
    assert config["rejection_reason_rules"]


def test_loads_reminder_rules_from_config() -> None:
    config = get_reminder_config()

    assert config["rules"]["weekly_follow_up"]["minimum_days_open"] == 7
    assert config["priority_order"]["High"] < config["priority_order"]["Low"]


def test_loads_job_post_rules_from_config() -> None:
    config = get_job_post_config()

    assert config["default_status"] == "Saved"
    assert "linkedin" in config["job_board_domains"]
    assert config["next_actions"]["with_deadline"]


def test_validates_email_parser_threshold_order() -> None:
    config = _valid_email_parser_config()
    config["match_thresholds"]["auto_match"] = 2
    config["match_thresholds"]["suggested_match"] = 3

    with pytest.raises(ConfigValidationError, match="auto_match.*suggested_match"):
        validate_email_parser_config(config)


def test_validates_email_parser_regex_patterns() -> None:
    config = _valid_email_parser_config()
    config["extraction_patterns"]["role"] = ["("]

    with pytest.raises(ConfigValidationError, match=r"email_parser\.extraction_patterns\.role\[0\]"):
        validate_email_parser_config(config)


def test_validates_reminder_priority_references() -> None:
    config = _valid_reminder_config()
    config["rules"]["weekly_follow_up"]["priority"] = "Urgent"

    with pytest.raises(ConfigValidationError, match="priority.*priority_order"):
        validate_reminder_config(config)


def test_validates_job_post_default_status() -> None:
    config = _valid_job_post_config()
    config["default_status"] = "Draft"

    with pytest.raises(ConfigValidationError, match="job_post\\.default_status"):
        validate_job_post_config(config)


def test_validates_job_post_regex_patterns() -> None:
    config = _valid_job_post_config()
    config["extraction_patterns"]["company"] = ["("]

    with pytest.raises(ConfigValidationError, match=r"job_post\.extraction_patterns\.company\[0\]"):
        validate_job_post_config(config)


def _valid_email_classification_config() -> dict[str, Any]:
    return {
        "category_rules": [
            {
                "category": "Rejection",
                "priority": 5,
                "suggested_status": "Rejected",
                "suggested_next_action": "Close the application.",
                "suggested_follow_up_days": None,
                "keywords": ["unfortunately"],
            }
        ],
        "default_classification": {
            "category": "Other",
            "confidence": 0.2,
            "suggested_status": "Applied",
            "suggested_next_action": "Review manually.",
            "suggested_follow_up_days": None,
        },
        "confidence": {
            "base": 0.45,
            "per_score": 0.12,
            "maximum": 0.95,
        },
    }


def _valid_email_parser_config() -> dict[str, Any]:
    return {
        "match_thresholds": {
            "auto_match": 6,
            "suggested_match": 3,
            "ambiguous_margin": 2,
        },
        "generic_email_domains": ["gmail"],
        "role_stop_words": ["the"],
        "common_locations": ["Berlin"],
        "month_lookup": {"jan": 1},
        "date_context_keywords": {
            "deadline": ["deadline"],
            "interview": ["interview"],
        },
        "extraction_patterns": {
            "company": [r"company:\s*(.+)"],
            "role": [r"role:\s*(.+)"],
            "location": [r"location:\s*(.+)"],
        },
        "intent_keywords": {
            "rejection": ["unfortunately"],
            "interview": ["interview"],
            "assessment": ["assessment"],
            "confirmation": ["received"],
        },
        "rejection_reason_rules": [
            {
                "reason": "Other candidates were selected.",
                "patterns": ["other candidates"],
            }
        ],
        "rejection_sentence_keywords": ["unfortunately"],
    }


def _valid_reminder_config() -> dict[str, Any]:
    base_rule = {
        "priority": "Medium",
        "message": "Review this application.",
        "reason": "review",
    }
    return {
        "priority_order": {
            "High": 0,
            "Medium": 1,
            "Low": 2,
        },
        "rules": {
            "follow_up_due": {
                "priority": "High",
                "message": "Follow up.",
                "reason": "follow_up_date",
            },
            "interview_preparation": {
                "priority": "High",
                "message": "Prepare interview notes.",
                "reason": "interview_preparation",
            },
            "assessment_deadline": {
                "priority": "High",
                "message": "Work on assessment.",
                "reason": "assessment_deadline",
                "default_due_days": 2,
            },
            "stale_application": {
                **base_rule,
                "minimum_days_open": 14,
                "statuses": ["Applied", "Confirmation Received"],
            },
            "weekly_follow_up": {
                **base_rule,
                "minimum_days_open": 7,
                "statuses": ["Applied", "Confirmation Received"],
            },
            "saved_role": {
                "priority": "Low",
                "message": "Review saved role.",
                "reason": "saved_role",
            },
        },
    }


def _valid_job_post_config() -> dict[str, Any]:
    return {
        "default_status": "Saved",
        "job_board_domains": ["linkedin"],
        "common_locations": ["Berlin"],
        "role_keywords": ["engineer"],
        "role_stop_lines": ["about us"],
        "extraction_patterns": {
            "company": [r"company:\s*(.+)"],
            "role": [r"role:\s*(.+)"],
            "location": [r"location:\s*(.+)"],
        },
        "deadline_keywords": ["deadline"],
        "month_lookup": {"jan": 1},
        "next_actions": {
            "with_deadline": "Apply before {deadline}.",
            "with_source": "Review source.",
            "default": "Review JD.",
        },
    }
