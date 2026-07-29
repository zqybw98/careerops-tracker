# Private CareerOps Data Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe, one-click Windows workflow that exports approved CareerOps data and synchronizes it only to `zqybw98/careerops-private-data` after private-visibility validation.

**Architecture:** A read-only Python exporter produces deterministic CSV, SQL, and manifest files from an explicit table-and-column allowlist. A separate Python sync service validates the local Git remote and GitHub visibility, while thin batch launchers separate first-time initialization, daily sync, and dry-run validation.

**Tech Stack:** Python 3.13 standard library (`sqlite3`, `csv`, `json`, `subprocess`, `pathlib`), Git, GitHub CLI, Windows batch, pytest.

## Global Constraints

- The only allowed GitHub destination is `zqybw98/careerops-private-data`.
- Remote owner, repository name, and private visibility must be verified before any push.
- Remote validation errors must not echo the configured URL, user information,
  query parameters, or embedded credentials.
- The source SQLite database must be opened read-only and never modified.
- Export only explicitly allowlisted business tables and columns.
- Stage only the exact repository-relative files returned by `ExportResult.files`;
  never stage directory roots, `.` or `-A`, and reject paths outside the private checkout.
- Do not export raw SQLite files, logs, caches, temporary files, environment files, tokens, credentials, email bodies, or attachment paths.
- Stable data must produce byte-identical CSV, SQL, and manifest files.
- No changes means no commit and no push.
- Initialization and daily synchronization are separate commands.
- This implementation performs local verification only; it must not create the GitHub repository or push during development.

---

### Task 1: Deterministic Read-Only Exporter

**Files:**
- Create: `src/private_data_export.py`
- Test: `tests/test_private_data_export.py`

**Interfaces:**
- Produces: `export_private_data(db_path: Path, destination: Path) -> ExportResult`
- Produces: `ExportResult(files: tuple[Path, ...], row_counts: dict[str, int], fingerprint: str)`
- Produces: immutable `APPROVED_TABLE_COLUMNS` and `CSV_EXPORT_TABLES` allowlists.

- [ ] **Step 1: Write failing exporter tests**

Cover read-only behavior, exact file allowlist, deterministic output across two runs, stable row sorting, missing optional `company_research_notes`, failure on unexpected columns, absence of credentials/email-body fields, and manifest row counts.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `python -m pytest tests/test_private_data_export.py -q`

Expected: collection failure because `src.private_data_export` does not exist.

- [ ] **Step 3: Implement the minimal exporter**

Implementation requirements:

```python
APPROVED_TABLE_COLUMNS = {
    "applications": (
        "id",
        "company",
        "role",
        "location",
        "application_date",
        "status",
        "source_link",
        "contact",
        "notes",
        "rejection_reason",
        "next_action",
        "follow_up_date",
        "created_at",
        "updated_at",
    ),
    "application_events": (
        "id",
        "application_id",
        "event_type",
        "old_value",
        "new_value",
        "source",
        "created_at",
    ),
    "email_feedback": (
        "id",
        "email_signature",
        "subject",
        "predicted_category",
        "predicted_status",
        "corrected_category",
        "corrected_status",
        "corrected_application_id",
        "corrected_company",
        "corrected_role",
        "source",
        "created_at",
    ),
    "schema_version": ("version", "name", "applied_at"),
    "company_research_notes": (
        "id",
        "company",
        "checked_at",
        "decision",
        "relevant_roles",
        "skipped_roles",
        "summary",
        "notes",
        "source_link",
        "created_at",
        "updated_at",
    ),
}
```

Open with `sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)`, begin a consistent read transaction, verify table schemas before reading, order rows by primary key, and write into a temporary staging directory. Generate SQL using deterministic `CREATE TABLE` and `INSERT` statements limited to approved columns. Replace destination files only after every staged file succeeds.

The committed manifest contains only format version, approved exports, row counts, and a content fingerprint. The current execution time is console output only.

- [ ] **Step 4: Run exporter tests**

Run: `python -m pytest tests/test_private_data_export.py -q`

Expected: all exporter tests pass.

### Task 2: Safe Git and GitHub Synchronization Service

**Files:**
- Create: `src/private_data_sync.py`
- Test: `tests/test_private_data_sync.py`

**Interfaces:**
- Consumes: `export_private_data(...) -> ExportResult`
- Produces: `run_sync(config: SyncConfig, runner: CommandRunner) -> SyncResult`
- Produces: `validate_remote_url(url: str) -> None`
- Produces: `validate_private_repository(runner: CommandRunner) -> None`

- [ ] **Step 1: Write failing synchronization tests**

Use a fake command runner. Cover:

- correct private repository permits dry-run and sync planning;
- wrong owner or repository is rejected before export/commit/push without
  exposing the configured remote URL or embedded credentials;
- public or unverifiable visibility is rejected;
- unchanged Git state skips commit and push;
- changed Git state stages only exporter-returned files, then commits and pushes once;
- unrelated files under export directories remain unstaged and untouched;
- exporter-returned paths outside the private checkout are rejected before commit or push;
- exporter failure prevents all Git writes;
- push failure returns a non-zero result while preserving exported files;
- initialization and daily sync modes reject each other's invalid states.

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `python -m pytest tests/test_private_data_sync.py -q`

Expected: collection failure because `src.private_data_sync` does not exist.

- [ ] **Step 3: Implement command orchestration and safety gates**

Use subprocess argument lists, never shell-built command strings. Validate these exact values:

```python
EXPECTED_REPOSITORY = "zqybw98/careerops-private-data"
ALLOWED_REMOTE_URLS = {
    "https://github.com/zqybw98/careerops-private-data.git",
    "git@github.com:zqybw98/careerops-private-data.git",
}
```

Before push, run `git remote get-url origin` and `gh repo view zqybw98/careerops-private-data --json nameWithOwner,visibility`. Accept only exact owner/name and `PRIVATE`. Dry-run performs validation and export comparison but never stages, commits, or pushes. Daily sync requires an already initialized checkout. Initialization may create the private GitHub repository only when the user explicitly runs the separate initialization command.

For daily synchronization, resolve every path returned by `ExportResult.files`,
verify that it is inside the private checkout, convert it to a stable
repository-relative path, deduplicate it, and pass only those exact paths to
`git status --porcelain --` and `git add --`. Extra files already present in the
checkout must never be staged automatically.

- [ ] **Step 4: Run synchronization tests**

Run: `python -m pytest tests/test_private_data_sync.py -q`

Expected: all synchronization tests pass.

### Task 3: CLI and Windows Launchers

**Files:**
- Create: `scripts/private_data_sync.py`
- Create: `init_private_data_repo.bat`
- Create: `sync_private_data.bat`
- Create: `verify_private_data_sync.bat`

**Interfaces:**
- Consumes: `src.private_data_sync.main(argv: Sequence[str] | None = None) -> int`
- Produces three explicit user entrypoints with no embedded credentials.

- [ ] **Step 1: Add CLI argument tests to `tests/test_private_data_sync.py`**

Cover `initialize`, `sync`, and `dry-run` modes, explicit `--target`, default target under `%USERPROFILE%\Documents\CareerOps Private Data`, and non-zero exit codes for every safety failure.

- [ ] **Step 2: Run CLI tests and confirm failure**

Run: `python -m pytest tests/test_private_data_sync.py -q`

Expected: new CLI tests fail before implementation.

- [ ] **Step 3: Implement the CLI and launchers**

Each batch file changes to `%~dp0`, requires `.venv\Scripts\python.exe`, calls the thin CLI with one fixed mode, forwards optional arguments, and pauses on failure. `sync_private_data.bat` must never initialize a repository. `verify_private_data_sync.bat` must always use dry-run.

- [ ] **Step 4: Run CLI tests and batch syntax smoke checks**

Run: `python -m pytest tests/test_private_data_sync.py -q`

Expected: all tests pass; no GitHub repository is created and no push occurs.

### Task 4: Documentation and Design Correction

**Files:**
- Create: `docs/private-data-sync.md`
- Modify: `docs/superpowers/specs/2026-07-15-private-data-sync-design.md`

**Interfaces:**
- Documents the approved export field list, privacy implications, first-time initialization, dry-run, daily sync, recovery, and restore commands.

- [ ] **Step 1: Document the exact data boundary**

List every approved table and column. State that Notes, contacts, source links, email feedback subjects, and signatures are private and permanently versioned once pushed. State that email bodies, credentials, tokens, raw database files, `.env`, caches, logs, and attachment paths are excluded.

- [ ] **Step 2: Separate first-time and daily workflows**

Document:

```text
verify_private_data_sync.bat
init_private_data_repo.bat
sync_private_data.bat
```

Explain that this development task does not run initialization or push.

- [ ] **Step 3: Correct the manifest design**

Remove the committed sync timestamp requirement from the design. Record volatile execution time only in console output so unchanged data remains byte-identical.

### Task 5: Local Verification Gate

**Files:**
- Review only; do not create repositories or push.

- [ ] **Step 1: Run focused tests**

Run: `python -m pytest tests/test_private_data_export.py tests/test_private_data_sync.py -q`

- [ ] **Step 2: Run the complete test suite**

Run: `python -m pytest`

- [ ] **Step 3: Run quality checks**

Run:

```text
python -m ruff check .
python -m ruff format --check .
python -m mypy src
```

- [ ] **Step 4: Run a local exporter smoke test against a temporary copy**

Export from a temporary SQLite fixture and verify the expected files and stable hashes across two runs. Do not run initialization, commit, or push against the real private-data destination.

- [ ] **Step 5: Review scope and Git diff**

Confirm no existing user changes were included, no credential-like files were added, and no command contacted GitHub for a write operation.
