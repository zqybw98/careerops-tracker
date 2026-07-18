from src.ui.sidebar import WORKSPACE_OPTIONS, normalize_workspace


def test_applications_is_the_default_workspace() -> None:
    assert WORKSPACE_OPTIONS[0] == "Applications"


def test_legacy_workspaces_map_to_the_simplified_navigation() -> None:
    assert normalize_workspace("Overview") == "Analytics"
    assert normalize_workspace("Contacts") == "More"
    assert normalize_workspace("Email Assistant") == "More"
    assert normalize_workspace("Data & Settings") == "More"
    assert normalize_workspace("Applications") == "Applications"
