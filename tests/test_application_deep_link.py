from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import src.ui.application_deep_link as application_deep_link
from src.database import create_application, init_db


class _QueryParams(dict[str, object]):
    pass


def _streamlit_state(**query_params: object) -> SimpleNamespace:
    return SimpleNamespace(
        query_params=_QueryParams(query_params),
        session_state={},
    )


def _create_application(db_path: Path) -> int:
    init_db(db_path)
    return create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer",
            "application_date": "2026-07-25",
            "status": "Applied",
        },
        db_path=db_path,
    )


def test_valid_deep_link_opens_existing_application_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "applications.db"
    application_id = _create_application(db_path)
    streamlit_state = _streamlit_state(
        workspace="Applications",
        application_id=str(application_id),
        redirect="https://example.com/ignored",
    )
    monkeypatch.setattr(application_deep_link, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(application_deep_link, "st", streamlit_state)

    consumed_id = application_deep_link.consume_application_deep_link()

    assert consumed_id == application_id
    assert streamlit_state.session_state["_workspace_nav_request"] == "Applications"
    assert streamlit_state.session_state["applications_pending_detail_id"] == application_id
    assert streamlit_state.query_params == {"redirect": "https://example.com/ignored"}

    assert application_deep_link.consume_application_deep_link() is None
    assert streamlit_state.session_state["applications_pending_detail_id"] == application_id
    assert streamlit_state.query_params == {"redirect": "https://example.com/ignored"}


@pytest.mark.parametrize("application_id", ["not-a-number", "0", "-3", "", None])
def test_invalid_application_id_lands_on_applications_without_opening_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    application_id: object,
) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    streamlit_state = _streamlit_state(
        workspace="Applications",
        application_id=application_id,
        theme="dark",
    )
    monkeypatch.setattr(application_deep_link, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(application_deep_link, "st", streamlit_state)

    assert application_deep_link.consume_application_deep_link() is None
    assert streamlit_state.session_state == {"_workspace_nav_request": "Applications"}
    assert streamlit_state.query_params == {"theme": "dark"}


def test_missing_application_lands_on_applications_without_opening_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    streamlit_state = _streamlit_state(
        workspace="Applications",
        application_id="999",
    )
    monkeypatch.setattr(application_deep_link, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(application_deep_link, "st", streamlit_state)

    assert application_deep_link.consume_application_deep_link() is None
    assert streamlit_state.session_state == {"_workspace_nav_request": "Applications"}
    assert streamlit_state.query_params == {}


@pytest.mark.parametrize(
    "workspace",
    [
        "Analytics",
        "https://example.com",
        "file:///C:/secret.txt",
        "../Applications",
    ],
)
def test_unrecognized_workspace_cannot_redirect_application_ui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workspace: str,
) -> None:
    db_path = tmp_path / "applications.db"
    application_id = _create_application(db_path)
    streamlit_state = _streamlit_state(
        workspace=workspace,
        application_id=str(application_id),
        embed="true",
    )
    monkeypatch.setattr(application_deep_link, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(application_deep_link, "st", streamlit_state)

    assert application_deep_link.consume_application_deep_link() is None
    assert streamlit_state.session_state == {}
    assert streamlit_state.query_params == {"embed": "true"}
