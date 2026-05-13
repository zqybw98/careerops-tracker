from src.config_loader import (
    get_email_classification_config,
    get_email_parser_config,
    get_reminder_config,
)


def test_loads_email_classification_rules_from_config() -> None:
    config = get_email_classification_config()

    categories = {rule["category"] for rule in config["category_rules"]}

    assert "Interview Invitation" in categories
    assert "Rejection" in categories
    assert config["default_classification"]["category"] == "Other"


def test_loads_parser_rules_from_config() -> None:
    config = get_email_parser_config()

    assert config["match_thresholds"]["auto_match"] >= config["match_thresholds"]["suggested_match"]
    assert "Berlin" in config["common_locations"]
    assert config["rejection_reason_rules"]


def test_loads_reminder_rules_from_config() -> None:
    config = get_reminder_config()

    assert config["rules"]["weekly_follow_up"]["minimum_days_open"] == 7
    assert config["priority_order"]["High"] < config["priority_order"]["Low"]
