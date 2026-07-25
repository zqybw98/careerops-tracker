# CareerOps Capture Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in, localhost-only HTTP Bridge that previews and atomically saves reviewed Chrome Extension captures into the existing CareerOps SQLite workflow.

**Architecture:** `src.capture_service` owns request validation, duplicate orchestration, merge policy, idempotency, and transactional persistence. `src.capture_api` owns the standard-library HTTP server, bearer-token pairing, CORS, error mapping, and process-level singleton lifecycle. Existing database APIs remain backward compatible, and Streamlit only starts the Bridge when `start.bat` explicitly opts in.

**Tech Stack:** Python 3.13 standard library (`http.server`, `sqlite3`, `threading`, `secrets`, `hashlib`, `json`, `urllib`), Streamlit, pytest, Ruff, mypy.

## Global Constraints

- Follow `docs/superpowers/specs/2026-07-25-careerops-capture-extension-design.md`.
- Bind production traffic only to `127.0.0.1:8765`.
- Do not add Flask, FastAPI, cloud APIs, LLM dependencies, or npm tooling.
- The Bridge is disabled for imports, tests, Streamlit Cloud, and ordinary
  `streamlit run app.py` unless explicitly enabled.
- Every create or update requires review, a UUID v4 `client_request_id`, and a
  valid bearer token from the paired extension origin.
- Application write, activity events, and `capture_requests` insertion commit
  in one SQLite transaction or roll back together.
- `edited_fields` is validated, deduplicated, sorted, included in the
  idempotency hash, and authoritative for protected-field overwrite intent.
- Existing non-empty Company and Role values are never overwritten unless their
  names appear in `edited_fields`.
- Existing non-empty Status is preserved unless `status` appears in
  `edited_fields`; an explicit Status edit is validated before business rules
  run.
- Notes append by a fixed server rule and are never replaced by a client choice.
- Only a Bridge singleton owned by the current Python process may be reused;
  an external CareerOps Bridge is detected but never adopted.
- Existing private-data export behavior and allowlists remain unchanged.
- Do not migrate or write the user's real SQLite database during implementation
  or verification; use temporary databases.
- Do not print, log, export, or commit the pairing token.
- Do not commit or push until the user separately approves reviewed changes.

---

### Task 1: Add Transaction-Aware Database Primitives and Migration 007

**Files:**
- Create: `migrations/007_add_capture_requests.sql`
- Modify: `src/database.py`
- Modify: `tests/test_database.py`

**Interfaces:**
- Produces: `_create_application_in_transaction(connection: sqlite3.Connection, payload: dict[str, Any], source: str) -> int`
- Produces: `_update_application_in_transaction(connection: sqlite3.Connection, application_id: int, payload: dict[str, Any], source: str) -> None`
- Preserves: `create_application(...) -> int`
- Preserves: `update_application(...) -> None`
- Produces schema version 7 table `capture_requests`.

- [ ] **Step 1: Write failing compatibility and migration tests**

Add tests that assert:

```python
def test_public_create_and_update_still_commit_events(tmp_path: Path) -> None:
    ...


def test_transaction_helpers_do_not_commit_caller_transaction(tmp_path: Path) -> None:
    ...


def test_init_db_creates_capture_requests_schema(tmp_path: Path) -> None:
    ...


def test_init_db_applies_capture_migration_idempotently(tmp_path: Path) -> None:
    ...
```

The helper test must begin a transaction, call the internal helper, roll back,
and verify that neither the application nor its activity event remains.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_database.py -q
```

Expected: FAIL because migration 007 and the connection-aware helpers do not
exist.

- [ ] **Step 3: Add migration 007**

Create:

```sql
CREATE TABLE IF NOT EXISTS capture_requests (
    client_request_id TEXT PRIMARY KEY,
    payload_sha256 TEXT NOT NULL,
    application_id INTEGER NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

Do not add `capture_requests` to private export allowlists. Update
`_migration_is_satisfied(connection, version=7)` to require the table and all
five columns so a partial table is not baselined as complete.

- [ ] **Step 4: Extract the internal transaction helpers**

Move the current SQL and `_insert_event()` work into:

```python
def _create_application_in_transaction(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    source: str,
) -> int:
    ...


def _update_application_in_transaction(
    connection: sqlite3.Connection,
    application_id: int,
    payload: dict[str, Any],
    source: str,
) -> None:
    ...
```

The helpers must not open connections and must not call `commit()` or
`rollback()`. Keep the public wrappers equivalent to:

```python
def create_application(...):
    with get_connection(db_path) as connection:
        application_id = _create_application_in_transaction(
            connection,
            payload,
            source,
        )
        connection.commit()
        return application_id
```

Use the same pattern for `update_application()`. Preserve current cleaning,
timestamps, return values, and event names.

- [ ] **Step 5: Run database tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_database.py -q
```

Expected: PASS.

- [ ] **Step 6: Review and commit the isolated database change**

Review:

```powershell
git diff -- migrations/007_add_capture_requests.sql src/database.py tests/test_database.py
```

Suggested commit:

```powershell
git add migrations/007_add_capture_requests.sql src/database.py tests/test_database.py
git commit -m "Add atomic capture persistence primitives"
```

Do not push.

### Task 2: Implement Capture Validation, Merge Policy, and Idempotency

**Files:**
- Create: `src/capture_service.py`
- Create: `tests/test_capture_service.py`
- Modify: `tests/test_private_data_export.py`

**Interfaces:**
- Produces: `CaptureValidationError(field: str, message: str)`
- Produces: `CaptureConflictError(code: str, details: dict[str, Any])`
- Produces: `CaptureNotFoundError(code: str)`
- Produces: `CaptureDatabaseBusyError()`
- Produces: `validate_preview_payload(payload: object) -> dict[str, Any]`
- Produces: `validate_confirmed_payload(payload: object) -> dict[str, Any]`
- Produces: `preview_capture(payload: object, db_path: Path | str = DEFAULT_DB_PATH) -> dict[str, Any]`
- Produces: `save_capture(payload: object, db_path: Path | str = DEFAULT_DB_PATH) -> dict[str, Any]`
- Consumes: database transaction helpers from Task 1.

- [ ] **Step 1: Write failing validation tests**

Cover:

- only the documented request fields are accepted;
- Company and Role are required after trimming;
- ISO Application Date validation;
- exact status or recognized alias acceptance;
- unknown non-empty status rejection instead of fallback to `Applied`;
- `http`/`https` Source validation and all documented length limits;
- valid UUID v4 requirement for confirmed requests;
- `edited_fields` omission on preview;
- strings-only `edited_fields`;
- unknown edited field returning a field-level validation error;
- deduplication and stable sorting of edited field names;
- `create_anyway` validating but ignoring merge intent.

Representative assertion:

```python
def test_confirmed_payload_rejects_unknown_edited_field() -> None:
    payload = valid_confirmed_payload(
        edited_fields=["location", "password"],
    )

    with pytest.raises(CaptureValidationError) as error:
        validate_confirmed_payload(payload)

    assert error.value.field == "edited_fields"
```

- [ ] **Step 2: Write failing duplicate and merge tests**

Use temporary databases and cover:

- at most three likely duplicates from
  `find_likely_duplicate_applications()`;
- exact normalized Company + Role + Source blocking duplicate;
- `none` rejecting a blocking duplicate;
- `create_anyway` creating a separate record only after explicit selection;
- `use_existing` requiring a real `existing_application_id`;
- unedited Company and Role filling blanks but preserving non-empty values;
- edited Company and Role replacing non-empty values;
- unedited Location, Source, and Application Date filling blanks only;
- edited Location, Source, and Application Date replacing values;
- Notes appending once, never replacing;
- empty or omitted `edited_fields` granting no protected overwrite;
- existing Interview plus incoming Applied with unedited Status preserving
  Interview;
- existing Rejected plus incoming Applied with unedited Status preserving
  Rejected;
- an explicitly edited Status using the validated selected value;
- an explicit Rejected edit clearing Follow-up Date and setting `No action`.

- [ ] **Step 3: Write failing idempotency and rollback tests**

Cover:

```text
same ID + same canonical payload -> replay original result, no extra note/event
same ID + different edited_fields -> CaptureConflictError("idempotency_conflict")
same ID + any other payload change -> CaptureConflictError("idempotency_conflict")
new ID -> exactly one application/event/capture_requests row
application failure -> no event and no capture_requests row
event failure -> no application change and no capture_requests row
capture_requests failure -> no application change and no event
```

Use monkeypatching at the connection-aware helper boundary. Verify the
canonical hash includes unique sorted `edited_fields` but excludes the bearer
token and `client_request_id`.

- [ ] **Step 4: Run focused tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_capture_service.py -q
```

Expected: collection failure because `src.capture_service` does not exist.

- [ ] **Step 5: Implement validation and preview**

Keep public validation output as cleaned dictionaries to match current project
conventions. Define immutable constants:

```python
CAPTURE_FIELDS = {
    "company",
    "role",
    "location",
    "application_date",
    "status",
    "source_link",
    "notes",
}
EDITABLE_FIELDS = frozenset(CAPTURE_FIELDS)
RESOLUTIONS = {"none", "create_anyway", "use_existing"}
```

Perform status-alias recognition before calling existing normalization so an
unknown non-empty value cannot silently become `Applied`. Run
`apply_status_business_rules()` after validation. Return normalized fields and
duplicate candidates from preview without writing.

Raise stable service exceptions rather than embedding workflow state in
messages:

```python
class CaptureConflictError(Exception):
    code: str
    details: dict[str, Any]


class CaptureNotFoundError(Exception):
    code: str


class CaptureDatabaseBusyError(Exception):
    ...
```

Use `CaptureConflictError` for `duplicate_conflict` and
`idempotency_conflict`, `CaptureNotFoundError` for a missing selected record,
and `CaptureDatabaseBusyError` when SQLite remains unavailable after the busy
timeout.

- [ ] **Step 6: Implement protected-field merge and canonical hashing**

Build the existing-record payload from `APPLICATION_COLUMNS`, applying:

```text
company, role:
  overwrite non-empty only when explicitly edited
location, source_link, application_date:
  unedited extraction fills blanks only; explicit edit may replace
notes:
  append unique non-empty capture note; never replace
status:
  when absent from edited_fields, preserve existing non-empty status
  when present in edited_fields, use validated incoming status
  then apply status business rules
```

Canonicalize JSON with sorted keys, stable separators, and the deduplicated
sorted `edited_fields`; hash UTF-8 bytes with SHA-256.

- [ ] **Step 7: Implement one-connection save**

Use:

```python
with get_connection(db_path) as connection:
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("BEGIN IMMEDIATE")
    try:
        # replay/conflict check
        # application create/update through internal helper
        # capture_requests insert
        connection.commit()
    except Exception:
        connection.rollback()
        raise
```

The database helper writes the corresponding application events in the same
transaction. Return only `result`, `application_id`, `replayed`, and
`open_url`.

- [ ] **Step 8: Prove private export ignores the operational table**

Extend `tests/test_private_data_export.py` to initialize migration 007, insert a
synthetic `capture_requests` row, export, and assert that no capture request,
payload hash, or token-like value appears in CSV, SQL, or manifest output.

- [ ] **Step 9: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_capture_service.py tests/test_private_data_export.py -q
```

Expected: PASS.

- [ ] **Step 10: Review and commit**

Suggested commit:

```powershell
git add src/capture_service.py tests/test_capture_service.py tests/test_private_data_export.py
git commit -m "Add reviewed browser capture workflow"
```

Do not push.

### Task 3: Add Pairing State and the Authenticated HTTP Contract

**Files:**
- Create: `src/capture_api.py`
- Create: `tests/test_capture_api.py`

**Interfaces:**
- Produces: `CaptureBridgeStatus(state: str, message: str, port: int)`
- Produces: `get_or_create_pairing_token(path: Path) -> str`
- Produces: `rotate_pairing_token(path: Path) -> str`
- Produces: `build_capture_server(*, host: str, port: int, db_path: Path, pairing_path: Path) -> ThreadingHTTPServer`
- Consumes: `preview_capture()` and `save_capture()` from Task 2.

- [ ] **Step 1: Write failing token and pairing tests**

Cover:

- first read generates a 32-byte URL-safe random token;
- normal reads reuse the token;
- token rotation atomically replaces it and clears paired origin;
- routine return values and errors never expose token text;
- only one syntactically valid `chrome-extension://<id>` origin may pair;
- the same paired origin can reconnect;
- a different origin is rejected until local rotation/reset;
- `secrets.compare_digest()` is used for authentication behavior.

Use a temporary `capture_pairing.json`; never inspect or write the real `data/`
path.

- [ ] **Step 2: Write failing endpoint tests**

Start a test server on `127.0.0.1` with port `0` and exercise it with
`urllib.request`. Cover:

- `GET /api/v1/health` returns only service identity and no sensitive values;
- health may echo only a syntactically valid extension Origin and never `*`;
- authenticated `POST /api/v1/pair/confirm`;
- exact paired Origin plus bearer token required for preview/create;
- CORS preflight permits only fixed methods and headers;
- `application/json` enforcement;
- 256 KiB limit before JSON parsing/database access;
- `400`, `401`, `403`, `404`, `409`, `413`, `415`, `422`, `500`, and `503`
  mappings without stack traces;
- missing or unsupported `X-CareerOps-API-Version` returning
  `400 unsupported_api_version`;
- SQLite locked beyond five seconds maps to `503`;
- successful responses use `Cache-Control: no-store`.

- [ ] **Step 3: Run endpoint tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_capture_api.py -q
```

Expected: collection failure because `src.capture_api` does not exist.

- [ ] **Step 4: Implement pairing state**

Store only:

```json
{
  "token": "<random local token>",
  "paired_origin": "chrome-extension://...",
  "updated_at": "ISO timestamp"
}
```

Write through a temporary sibling file followed by `Path.replace()`. Apply
best-effort current-user file restriction on Windows; return a warning state if
restriction cannot be confirmed. Never include token text in that warning.

- [ ] **Step 5: Implement the fixed HTTP routes**

Use `ThreadingHTTPServer` and a `BaseHTTPRequestHandler` subclass with explicit
route dispatch:

```text
GET     /api/v1/health
OPTIONS /api/v1/pair/confirm
POST    /api/v1/pair/confirm
OPTIONS /api/v1/applications/preview
POST    /api/v1/applications/preview
OPTIONS /api/v1/applications
POST    /api/v1/applications
```

Reject all other routes. Parse `Content-Length` before reading. Use generic
JSON error bodies with machine code, message, and optional field; never return
tracebacks, paths, raw SQL, or token values.

Map service failures explicitly:

```text
CaptureValidationError -> 422
CaptureConflictError("duplicate_conflict") -> 409 duplicate_conflict
CaptureConflictError("idempotency_conflict") -> 409 idempotency_conflict
CaptureNotFoundError -> 404 existing_application_not_found
CaptureDatabaseBusyError -> 503 database_busy
```

Every authenticated route requires exactly
`X-CareerOps-API-Version: 1`. A missing or unsupported value returns
`400 unsupported_api_version` before service or database work.

- [ ] **Step 6: Run HTTP tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_capture_api.py -q
```

Expected: PASS.

- [ ] **Step 7: Review and commit**

Suggested commit:

```powershell
git add src/capture_api.py tests/test_capture_api.py
git commit -m "Add authenticated localhost capture API"
```

Do not push.

### Task 4: Add Process-Level Singleton Startup, Deep Links, and Local Pairing UI

**Files:**
- Modify: `src/capture_api.py`
- Modify: `tests/test_capture_api.py`
- Create: `src/ui/application_deep_link.py`
- Create: `tests/test_application_deep_link.py`
- Create: `src/ui/capture_pairing.py`
- Create: `tests/test_capture_pairing.py`
- Modify: `src/ui/data_settings_page.py`
- Modify: `app.py`
- Modify: `start.bat`

**Interfaces:**
- Produces: `ensure_capture_bridge_started() -> CaptureBridgeStatus`
- Produces: `consume_application_deep_link() -> int | None`
- Produces: `render_capture_pairing() -> None`
- Uses environment flag: `CAREEROPS_CAPTURE_ENABLED=1`.

- [ ] **Step 1: Write failing singleton tests**

Cover:

- feature flag absent returns disabled without binding;
- tests/imports do not start the server;
- repeated calls return the same process-owned Bridge;
- simultaneous calls guarded by one module-level Lock start at most one thread;
- an externally owned CareerOps Bridge returns
  `external_bridge_detected` and is not adopted;
- external detection does not reveal or rotate this process's token and does
  not populate `_BRIDGE_SERVER`;
- an unrelated process on 8765 returns `port_conflict` without crashing
  Streamlit;
- Streamlit Cloud environment remains disabled.

Reset singleton state through a test-only fixture that shuts down only the
temporary test server it created. Only a live `_BRIDGE_SERVER` owned by the
current Python process may be returned as the reusable singleton.

- [ ] **Step 2: Write failing application deep-link tests**

Cover:

- `workspace=Applications` plus a valid positive existing ID requests the
  Applications workspace and opens Details through
  `applications_pending_detail_id`;
- a non-numeric or non-positive ID is ignored;
- a deleted or missing ID safely lands on Applications without opening Details;
- query parameters are cleared after the first consumption, so reruns do not
  reopen the dialog;
- unrecognized workspace values, extra URL-like values, and file-like values
  cannot redirect the app.

Call `consume_application_deep_link()` before the Sidebar widget is
instantiated. The helper may perform a read-only existence check only when the
two supported parameters are present.

- [ ] **Step 3: Write failing pairing-UI helper tests**

Extract non-Streamlit decisions into testable helpers:

```python
def pairing_ui_state(
    *,
    local_run: bool,
    bridge_status: CaptureBridgeStatus,
) -> dict[str, bool | str]:
    ...
```

Assert hosted/disabled runs cannot reveal or rotate the token, while a local
enabled process-owned Bridge can render pairing instructions. Also assert
`external_bridge_detected` and `port_conflict` states cannot reveal or rotate
this process's token.

- [ ] **Step 4: Run focused tests and verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_capture_api.py tests/test_application_deep_link.py tests/test_capture_pairing.py -q
```

Expected: FAIL because singleton, deep-link, and pairing UI helpers do not
exist.

- [ ] **Step 5: Implement process-level lifecycle**

Keep module-level state in `src.capture_api`:

```python
_BRIDGE_LOCK = threading.Lock()
_BRIDGE_SERVER: ThreadingHTTPServer | None = None
_BRIDGE_THREAD: threading.Thread | None = None
_BRIDGE_STATUS: CaptureBridgeStatus | None = None
```

Inside the Lock, return only an existing live `_BRIDGE_SERVER` owned by this
Python process. If a port probe finds another valid CareerOps Bridge, return
`external_bridge_detected` without adopting it, populating singleton state, or
revealing/rotating this process's token, and tell the user to close the other
CareerOps process or use its UI. If another application owns the port, return
`port_conflict` and identify that it must be closed. Both states keep Streamlit
usable. The production path must always use `127.0.0.1:8765`; only test server
factories may accept port `0`.

- [ ] **Step 6: Wire opt-in startup and Applications deep links**

In `start.bat`, set:

```bat
set "CAREEROPS_CAPTURE_ENABLED=1"
```

immediately before launching Streamlit. In `app.py`, call
`ensure_capture_bridge_started()` from `main()`, not at import time. A disabled
or warning status must not prevent the rest of the app from rendering.

At the beginning of `main()`, before
`_apply_workspace_navigation_request()` and `render_sidebar_navigation()`,
call `consume_application_deep_link()`. It reads only `workspace` and
`application_id`, accepts only the Applications workspace and a positive
existing ID, sets the existing workspace request and
`applications_pending_detail_id`, and clears all query parameters after
consumption. Missing or deleted IDs still request Applications but do not open
Details.

- [ ] **Step 7: Add the local-only Tools UI**

`render_capture_pairing()` shows:

- Bridge state;
- fixed endpoint `http://127.0.0.1:8765`;
- explicit token reveal control;
- extension pairing instructions;
- guarded token rotation confirmation;
- warnings without token text.

Call it from `render_data_tools()` under a collapsed
`Browser Capture pairing` expander. Do not show token controls on hosted runs.

- [ ] **Step 8: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_capture_api.py tests/test_application_deep_link.py tests/test_capture_pairing.py -q
```

Expected: PASS.

- [ ] **Step 9: Review and commit**

Suggested commit:

```powershell
git add src/capture_api.py tests/test_capture_api.py src/ui/application_deep_link.py tests/test_application_deep_link.py src/ui/capture_pairing.py tests/test_capture_pairing.py src/ui/data_settings_page.py app.py start.bat
git commit -m "Enable opt-in CareerOps capture bridge"
```

Do not push.

### Task 5: Concurrency, Documentation, and Final Local Gate

**Files:**
- Modify: `tests/test_capture_api.py`
- Modify: `tests/test_capture_service.py`
- Modify: `README.md`
- Create: `docs/browser-capture.md`

**Interfaces:**
- Documents local pairing, start behavior, privacy boundaries, recovery, and
  the exact API version.

- [ ] **Step 1: Add concurrency integration tests**

Against one temporary SQLite file, cover:

- repeated Streamlit-style reads while a Bridge capture commits;
- two distinct simultaneous confirmed captures;
- subsequent `get_applications()` seeing committed writes;
- a lock held longer than five seconds returning `503`;
- no corruption, duplicate event, or partial idempotency row.

Use barriers or Events for deterministic ordering; do not use timing-only
assertions.

- [ ] **Step 2: Document the local-only workflow**

Document:

```text
start.bat -> Bridge enabled
manual streamlit command -> Bridge disabled
Tools -> Browser Capture pairing -> reveal/copy token
Chrome options -> paste token and grant optional loopback permission
```

State that the hosted demo is not supported, the token stays local, Capture
never submits applications, and only reviewed fields are sent.

- [ ] **Step 3: Run focused and complete verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_database.py tests/test_capture_service.py tests/test_capture_api.py tests/test_application_deep_link.py tests/test_capture_pairing.py tests/test_private_data_export.py -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m pytest
git diff --check
git status --short
```

Expected: every command passes; only planned source, test, migration, launcher,
and documentation files are changed.

- [ ] **Step 4: Run a synthetic manual smoke test**

Use a temporary database through `CAREEROPS_DB_PATH`, not the real
`data/applications.db`. Start with `CAREEROPS_CAPTURE_ENABLED=1`, verify health,
pair using a synthetic token file, preview one synthetic job, save it once,
retry with the same ID, confirm exactly one application and event set, and
verify the returned `open_url` opens that synthetic record once.

Do not load or change real application data.

- [ ] **Step 5: Final scope review**

Confirm:

- no cloud URL or broad bind address;
- no token in Git diff, logs, fixtures, screenshots, or exports;
- no private sync behavior change;
- no unrelated Streamlit UI refactor;
- no real database migration was triggered;
- no commit was pushed.
