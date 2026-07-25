import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import src.capture_service as capture_service
import src.database as database
from src.capture_service import (
    CaptureConflictError,
    CaptureDatabaseBusyError,
    CaptureNotFoundError,
    CaptureValidationError,
    preview_capture,
    save_capture,
    validate_confirmed_payload,
    validate_preview_payload,
)
from src.database import create_application, get_application_events, get_applications, init_db


def _preview_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "company": "Example GmbH",
        "role": "QA Engineer",
        "location": "Berlin",
        "application_date": "2026-07-25",
        "status": "Applied",
        "source_link": "https://example.com/jobs/qa",
        "notes": "Captured from a reviewed job page.",
    }
    payload.update(overrides)
    return payload


def _confirmed_payload(**overrides: object) -> dict[str, object]:
    payload = _preview_payload(
        client_request_id=str(uuid4()),
        duplicate_resolution="none",
        edited_fields=[],
    )
    payload.update(overrides)
    return payload


def _application_by_id(db_path: Path, application_id: int) -> dict[str, object]:
    return next(application for application in get_applications(db_path) if application["id"] == application_id)


def _table_count(db_path: Path, table: str) -> int:
    with sqlite3.connect(db_path) as connection:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _seed_duplicate_candidates(db_path: Path) -> int:
    for index in range(3):
        create_application(
            {
                "company": "Example GmbH",
                "role": "QA Engineer",
                "status": "Applied",
                "source_link": f"https://example.com/jobs/{index}",
            },
            db_path=db_path,
        )
    return create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer",
            "status": "Applied",
            "source_link": "https://example.com/jobs/exact",
        },
        db_path=db_path,
    )


def test_preview_payload_accepts_only_capture_fields() -> None:
    cleaned = validate_preview_payload(_preview_payload())

    assert cleaned == {
        "company": "Example GmbH",
        "role": "QA Engineer",
        "location": "Berlin",
        "application_date": "2026-07-25",
        "status": "Applied",
        "source_link": "https://example.com/jobs/qa",
        "notes": "Captured from a reviewed job page.",
        "next_action": "Wait",
        "follow_up_date": "",
    }


@pytest.mark.parametrize("field", ["company", "role"])
def test_capture_payload_requires_trimmed_company_and_role(field: str) -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_preview_payload(_preview_payload(**{field: "   "}))

    assert error.value.field == field


@pytest.mark.parametrize("value", ["25.07.2026", "2026-7-25", "2026-02-30"])
def test_capture_payload_rejects_non_iso_application_date(value: str) -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_preview_payload(_preview_payload(application_date=value))

    assert error.value.field == "application_date"


def test_capture_payload_defaults_empty_status_to_applied() -> None:
    assert validate_preview_payload(_preview_payload(status=""))["status"] == "Applied"


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        ("Submitted", "Applied"),
        ("Confirmation Received", "Waiting"),
        ("coding test invited", "Interview / Assessment"),
        ("Absage erhalten", "Rejected"),
        ("Rejected / Talentpool option", "Rejected"),
        ("Interview, scheduled", "Interview / Assessment"),
    ],
)
def test_capture_payload_accepts_known_status_aliases(raw_status: str, expected: str) -> None:
    assert validate_preview_payload(_preview_payload(status=raw_status))["status"] == expected


def test_capture_payload_rejects_unknown_non_empty_status() -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_preview_payload(_preview_payload(status="Ready for mysterious workflow"))

    assert error.value.field == "status"


def test_capture_payload_does_not_match_status_keywords_inside_words() -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_preview_payload(_preview_payload(status="Latest update pending"))

    assert error.value.field == "status"


@pytest.mark.parametrize(
    "source_link",
    [
        "ftp://example.com/job",
        "example.com/job",
        "file:///job",
        "https://[invalid",
    ],
)
def test_capture_payload_rejects_non_http_source(source_link: str) -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_preview_payload(_preview_payload(source_link=source_link))

    assert error.value.field == "source_link"


def test_capture_payload_rejects_url_with_userinfo() -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_preview_payload(_preview_payload(source_link="https://user:secret@example.com/job"))

    assert error.value.field == "source_link"


def test_capture_payload_rejects_invalid_port() -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_preview_payload(_preview_payload(source_link="https://example.com:not-a-port/job"))

    assert error.value.field == "source_link"


def test_capture_payload_rejects_whitespace_hostname() -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_preview_payload(_preview_payload(source_link="https://exa mple.com/job"))

    assert error.value.field == "source_link"


@pytest.mark.parametrize("control_character", ["\r", "\n", "\t", "\x00"])
def test_capture_payload_rejects_control_characters(control_character: str) -> None:
    source_link = f"https://example.com/{control_character}job"

    with pytest.raises(CaptureValidationError) as error:
        validate_preview_payload(_preview_payload(source_link=source_link))

    assert error.value.field == "source_link"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("company", "x" * 201),
        ("role", "x" * 301),
        ("location", "x" * 301),
        ("source_link", "https://example.com/" + "x" * 2_001),
        ("notes", "x" * 4_001),
    ],
)
def test_capture_payload_enforces_field_length_limits(field: str, value: str) -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_preview_payload(_preview_payload(**{field: value}))

    assert error.value.field == field


def test_preview_rejects_confirmed_request_fields() -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_preview_payload(_preview_payload(client_request_id=str(uuid4())))

    assert error.value.field == "client_request_id"


@pytest.mark.parametrize(
    "client_request_id",
    ["", "not-a-uuid", str(UUID("00000000-0000-1000-8000-000000000000"))],
)
def test_confirmed_payload_requires_uuid_v4(client_request_id: str) -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_confirmed_payload(_confirmed_payload(client_request_id=client_request_id))

    assert error.value.field == "client_request_id"


@pytest.mark.parametrize("edited_fields", ["location", [1], ["location", None]])
def test_confirmed_payload_requires_string_array_for_edited_fields(edited_fields: object) -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_confirmed_payload(_confirmed_payload(edited_fields=edited_fields))

    assert error.value.field == "edited_fields"


def test_confirmed_payload_rejects_unknown_edited_field() -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_confirmed_payload(_confirmed_payload(edited_fields=["location", "password"]))

    assert error.value.field == "edited_fields"


def test_confirmed_payload_deduplicates_and_sorts_edited_fields() -> None:
    cleaned = validate_confirmed_payload(_confirmed_payload(edited_fields=["notes", "location", "notes", "company"]))

    assert cleaned["edited_fields"] == ["company", "location", "notes"]


def test_confirmed_payload_rejects_unknown_request_field() -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_confirmed_payload(_confirmed_payload(debug=True))

    assert error.value.field == "debug"


def test_confirmed_payload_requires_existing_id_for_use_existing() -> None:
    with pytest.raises(CaptureValidationError) as error:
        validate_confirmed_payload(_confirmed_payload(duplicate_resolution="use_existing"))

    assert error.value.field == "existing_application_id"


def test_preview_returns_at_most_three_stable_duplicate_candidates(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    for index in range(5):
        create_application(
            {
                "company": "Example GmbH",
                "role": f"QA Engineer {index}",
                "status": "Applied",
                "source_link": f"https://example.com/jobs/{index}",
            },
            db_path=db_path,
        )

    result = preview_capture(_preview_payload(role="QA Engineer"), db_path=db_path)

    assert len(result["duplicates"]) == 3
    expected_fields = {"application_id", "company", "role", "score", "reason"}
    assert all(set(candidate) == expected_fields for candidate in result["duplicates"])
    assert _table_count(db_path, "capture_requests") == 0


def test_preview_prioritizes_exact_source_match(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    exact_id = _seed_duplicate_candidates(db_path)

    result = preview_capture(
        _preview_payload(source_link="https://example.com/jobs/exact"),
        db_path=db_path,
    )

    assert result["duplicates"][0]["application_id"] == exact_id
    assert len(result["duplicates"]) == 3


def test_preview_and_save_return_consistent_duplicate_candidates(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    _seed_duplicate_candidates(db_path)
    preview_payload = _preview_payload(source_link="https://example.com/jobs/exact")
    preview = preview_capture(preview_payload, db_path=db_path)

    with pytest.raises(CaptureConflictError) as error:
        save_capture(
            {
                **preview_payload,
                "client_request_id": str(uuid4()),
                "duplicate_resolution": "none",
                "edited_fields": [],
            },
            db_path=db_path,
        )

    assert error.value.details["duplicates"] == preview["duplicates"]


def test_none_resolution_rejects_exact_normalized_duplicate(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer (m/w/d)",
            "status": "Applied",
            "source_link": "https://EXAMPLE.com/jobs/qa/",
        },
        db_path=db_path,
    )

    with pytest.raises(CaptureConflictError) as error:
        save_capture(
            _confirmed_payload(
                company="Example",
                role="QA Engineer",
                source_link="https://example.com/jobs/qa",
            ),
            db_path=db_path,
        )

    assert error.value.code == "duplicate_conflict"
    assert len(get_applications(db_path)) == 1
    assert _table_count(db_path, "capture_requests") == 0


def test_none_resolution_rejects_likely_duplicate_with_different_source(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    existing_id = create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer (m/w/d)",
            "status": "Applied",
            "source_link": "https://example.com/jobs/old",
        },
        db_path=db_path,
    )

    with pytest.raises(CaptureConflictError) as error:
        save_capture(
            _confirmed_payload(
                company="Example",
                role="QA Engineer",
                source_link="https://example.com/jobs/new",
            ),
            db_path=db_path,
        )

    assert error.value.code == "duplicate_conflict"
    assert [candidate["application_id"] for candidate in error.value.details["duplicates"]] == [existing_id]
    assert len(get_applications(db_path)) == 1
    assert _table_count(db_path, "capture_requests") == 0


def test_duplicate_conflict_candidates_include_exact_source_match(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    exact_id = _seed_duplicate_candidates(db_path)

    with pytest.raises(CaptureConflictError) as error:
        save_capture(
            _confirmed_payload(source_link="https://example.com/jobs/exact"),
            db_path=db_path,
        )

    returned_ids = [candidate["application_id"] for candidate in error.value.details["duplicates"]]
    assert exact_id in returned_ids
    assert len(returned_ids) == 3


def test_create_anyway_validates_edit_intent_but_creates_separate_record(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    existing_id = create_application(
        {
            "company": "Captured GmbH",
            "role": "QA Engineer",
            "location": "Munich",
            "status": "Waiting",
            "source_link": "https://example.com/jobs/qa",
        },
        db_path=db_path,
    )

    result = save_capture(
        _confirmed_payload(
            company="Captured GmbH",
            role="QA Engineer",
            location="Berlin",
            source_link="https://example.com/jobs/qa",
            duplicate_resolution="create_anyway",
            existing_application_id=existing_id,
            edited_fields=["company", "location"],
        ),
        db_path=db_path,
    )

    assert result["result"] == "created"
    assert result["application_id"] != existing_id
    assert len(get_applications(db_path)) == 2
    assert _application_by_id(db_path, existing_id)["company"] == "Captured GmbH"


def test_use_existing_requires_real_application_id(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)

    with pytest.raises(CaptureNotFoundError) as error:
        save_capture(
            _confirmed_payload(
                duplicate_resolution="use_existing",
                existing_application_id=999,
            ),
            db_path=db_path,
        )

    assert error.value.code == "existing_application_not_found"
    assert _table_count(db_path, "capture_requests") == 0


def test_use_existing_rejects_unrelated_application_id(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    unrelated_id = create_application(
        {
            "company": "Another Company",
            "role": "Sales Manager",
            "status": "Waiting",
            "notes": "Unrelated application.",
        },
        db_path=db_path,
    )
    matching_id = create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer",
            "status": "Applied",
            "source_link": "https://example.com/jobs/existing",
        },
        db_path=db_path,
    )

    with pytest.raises(CaptureConflictError) as error:
        save_capture(
            _confirmed_payload(
                duplicate_resolution="use_existing",
                existing_application_id=unrelated_id,
                edited_fields=["status", "notes"],
            ),
            db_path=db_path,
        )

    assert error.value.code == "duplicate_conflict"
    assert [candidate["application_id"] for candidate in error.value.details["duplicates"]] == [matching_id]
    assert _application_by_id(db_path, unrelated_id)["notes"] == "Unrelated application."
    assert _table_count(db_path, "capture_requests") == 0


def test_use_existing_accepts_selected_duplicate_candidate(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    application_id = create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer",
            "location": "",
            "status": "Applied",
            "source_link": "https://example.com/jobs/existing",
        },
        db_path=db_path,
    )

    result = save_capture(
        _confirmed_payload(
            location="Berlin",
            duplicate_resolution="use_existing",
            existing_application_id=application_id,
            edited_fields=["location"],
        ),
        db_path=db_path,
    )

    assert result["result"] == "updated"
    assert result["application_id"] == application_id
    assert _application_by_id(db_path, application_id)["location"] == "Berlin"


def test_use_existing_preserves_unedited_non_empty_fields_and_appends_notes(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    application_id = create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer (m/w/d)",
            "location": "Munich",
            "application_date": "2026-07-01",
            "status": "Interview / Assessment",
            "source_link": "https://existing.example/jobs/1",
            "notes": "Existing note.",
            "next_action": "Prepare for interview.",
            "follow_up_date": "2026-07-30",
        },
        db_path=db_path,
    )

    result = save_capture(
        _confirmed_payload(
            company="Example",
            role="QA Engineer",
            location="Berlin",
            application_date="2026-07-25",
            status="Applied",
            source_link="https://incoming.example/jobs/2",
            notes="Capture note.",
            duplicate_resolution="use_existing",
            existing_application_id=application_id,
            edited_fields=[],
        ),
        db_path=db_path,
    )
    updated = _application_by_id(db_path, application_id)

    assert result["result"] == "updated"
    assert updated["company"] == "Example GmbH"
    assert updated["role"] == "QA Engineer (m/w/d)"
    assert updated["location"] == "Munich"
    assert updated["application_date"] == "2026-07-01"
    assert updated["status"] == "Interview / Assessment"
    assert updated["source_link"] == "https://existing.example/jobs/1"
    assert updated["notes"] == "Existing note.\n\nCapture note."
    assert updated["next_action"] == "Prepare for interview."
    assert updated["follow_up_date"] == "2026-07-30"


def test_use_existing_fills_blank_fields_without_edit_intent(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    application_id = create_application(
        {
            "company": "Captured GmbH",
            "role": "Support Engineer",
            "location": "",
            "source_link": "",
            "status": "Applied",
        },
        db_path=db_path,
    )

    save_capture(
        _confirmed_payload(
            company="Captured GmbH",
            role="Support Engineer",
            location="Berlin",
            source_link="https://example.com/jobs/support",
            duplicate_resolution="use_existing",
            existing_application_id=application_id,
            edited_fields=[],
        ),
        db_path=db_path,
    )
    updated = _application_by_id(db_path, application_id)

    assert updated["company"] == "Captured GmbH"
    assert updated["role"] == "Support Engineer"
    assert updated["location"] == "Berlin"
    assert updated["source_link"] == "https://example.com/jobs/support"


def test_use_existing_replaces_explicitly_edited_fields_and_applies_rejected_rule(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    application_id = create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer",
            "location": "Munich",
            "application_date": "2026-07-01",
            "status": "Interview / Assessment",
            "source_link": "https://existing.example/jobs/1",
            "notes": "Existing note.",
            "next_action": "Prepare for interview.",
            "follow_up_date": "2026-07-30",
        },
        db_path=db_path,
    )

    save_capture(
        _confirmed_payload(
            company="Example Technologies GmbH",
            role="Senior QA Engineer",
            location="Berlin",
            application_date="2026-07-25",
            status="Rejected",
            source_link="https://incoming.example/jobs/2",
            notes="Rejection received.",
            duplicate_resolution="use_existing",
            existing_application_id=application_id,
            edited_fields=[
                "company",
                "role",
                "location",
                "application_date",
                "status",
                "source_link",
            ],
        ),
        db_path=db_path,
    )
    updated = _application_by_id(db_path, application_id)

    assert updated["company"] == "Example Technologies GmbH"
    assert updated["role"] == "Senior QA Engineer"
    assert updated["location"] == "Berlin"
    assert updated["application_date"] == "2026-07-25"
    assert updated["status"] == "Rejected"
    assert updated["source_link"] == "https://incoming.example/jobs/2"
    assert updated["notes"] == "Existing note.\n\nRejection received."
    assert updated["next_action"] == "No action"
    assert updated["follow_up_date"] == ""


def test_use_existing_preserves_rejected_status_when_status_is_unedited(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    application_id = create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer",
            "status": "Rejected",
            "next_action": "No action",
        },
        db_path=db_path,
    )

    save_capture(
        _confirmed_payload(
            status="Applied",
            duplicate_resolution="use_existing",
            existing_application_id=application_id,
            edited_fields=[],
        ),
        db_path=db_path,
    )

    assert _application_by_id(db_path, application_id)["status"] == "Rejected"


def test_use_existing_does_not_append_duplicate_multi_paragraph_notes(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    existing_notes = "First captured detail.\n\nSecond captured detail."
    application_id = create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer",
            "status": "Applied",
            "notes": existing_notes,
        },
        db_path=db_path,
    )

    save_capture(
        _confirmed_payload(
            notes=existing_notes,
            duplicate_resolution="use_existing",
            existing_application_id=application_id,
            edited_fields=["notes"],
        ),
        db_path=db_path,
    )

    assert _application_by_id(db_path, application_id)["notes"] == existing_notes


def test_same_request_replays_without_duplicate_application_event_or_note(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    request = _confirmed_payload()

    first = save_capture(request, db_path=db_path)
    event_count = len(get_application_events(first["application_id"], db_path))
    second = save_capture(request, db_path=db_path)

    assert first == {
        "result": "created",
        "application_id": first["application_id"],
        "replayed": False,
        "open_url": (f"http://localhost:8501/?workspace=Applications&application_id={first['application_id']}"),
    }
    assert second == {**first, "replayed": True}
    assert len(get_applications(db_path)) == 1
    assert len(get_application_events(first["application_id"], db_path)) == event_count
    assert _table_count(db_path, "capture_requests") == 1


@pytest.mark.parametrize(
    "changed",
    [
        {"edited_fields": ["location"]},
        {"location": "Hamburg"},
    ],
)
def test_same_request_id_with_changed_canonical_payload_conflicts(
    tmp_path: Path,
    changed: dict[str, object],
) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    request = _confirmed_payload()
    save_capture(request, db_path=db_path)

    with pytest.raises(CaptureConflictError) as error:
        save_capture({**request, **changed}, db_path=db_path)

    assert error.value.code == "idempotency_conflict"
    assert len(get_applications(db_path)) == 1
    assert _table_count(db_path, "capture_requests") == 1


def test_new_request_writes_one_application_event_and_capture_request(tmp_path: Path) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)

    result = save_capture(_confirmed_payload(), db_path=db_path)

    assert result["replayed"] is False
    assert len(get_applications(db_path)) == 1
    assert len(get_application_events(result["application_id"], db_path)) == 1
    assert _table_count(db_path, "capture_requests") == 1


def test_application_helper_failure_rolls_back_everything(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)

    def fail_create(*args: object, **kwargs: object) -> int:
        raise RuntimeError("synthetic application failure")

    monkeypatch.setattr(capture_service, "_create_application_in_transaction", fail_create)

    with pytest.raises(RuntimeError, match="synthetic application failure"):
        save_capture(_confirmed_payload(), db_path=db_path)

    assert _table_count(db_path, "applications") == 0
    assert _table_count(db_path, "application_events") == 0
    assert _table_count(db_path, "capture_requests") == 0


def test_event_failure_rolls_back_application_and_capture_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)

    def fail_event(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic event failure")

    monkeypatch.setattr(database, "_insert_event", fail_event)

    with pytest.raises(RuntimeError, match="synthetic event failure"):
        save_capture(_confirmed_payload(), db_path=db_path)

    assert _table_count(db_path, "applications") == 0
    assert _table_count(db_path, "application_events") == 0
    assert _table_count(db_path, "capture_requests") == 0


def test_capture_request_failure_rolls_back_existing_application_and_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "applications.db"
    init_db(db_path)
    application_id = create_application(
        {
            "company": "Example GmbH",
            "role": "QA Engineer",
            "status": "Applied",
            "notes": "Original note.",
        },
        db_path=db_path,
    )
    original_event_count = len(get_application_events(application_id, db_path))

    def fail_capture_request(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic capture request failure")

    monkeypatch.setattr(capture_service, "_insert_capture_request", fail_capture_request)

    with pytest.raises(RuntimeError, match="synthetic capture request failure"):
        save_capture(
            _confirmed_payload(
                status="Waiting",
                notes="Incoming note.",
                duplicate_resolution="use_existing",
                existing_application_id=application_id,
                edited_fields=["status"],
            ),
            db_path=db_path,
        )

    unchanged = _application_by_id(db_path, application_id)
    assert unchanged["status"] == "Applied"
    assert unchanged["notes"] == "Original note."
    assert len(get_application_events(application_id, db_path)) == original_event_count
    assert _table_count(db_path, "capture_requests") == 0


@pytest.mark.parametrize(
    "message",
    [
        "database is locked",
        "database is busy",
        "database table is locked",
    ],
)
def test_database_busy_error_is_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    def fail_connection(*args: object, **kwargs: object) -> sqlite3.Connection:
        raise sqlite3.OperationalError(message)

    monkeypatch.setattr(capture_service, "get_connection", fail_connection)

    with pytest.raises(CaptureDatabaseBusyError):
        save_capture(_confirmed_payload(), db_path=tmp_path / "applications.db")
