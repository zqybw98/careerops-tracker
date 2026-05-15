from typing import Any

import pytest
from src.config_loader import (
    ConfigValidationError,
    get_email_classification_config,
    get_email_parser_config,
    get_reminder_config,
    validate_email_classification_config,
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
