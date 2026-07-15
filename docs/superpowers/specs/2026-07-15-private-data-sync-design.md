# Private CareerOps Data Sync Design

## Goal

Provide a one-click Windows workflow that exports the local CareerOps Tracker
data, records readable changes in Git, and pushes them to the private GitHub
repository `zqybw98/careerops-private-data`.

The public `careerops-tracker` repository must continue to exclude real job
application data.

## User Workflow

1. Continue using CareerOps Tracker normally.
2. Double-click `sync_private_data.bat` when a backup is wanted.
3. The script exports the current database into the local private-data checkout.
4. It commits and pushes only when exported data changed.
5. The terminal reports success, no changes, or a recoverable error.

## Repository Layout

The private repository will use this structure:

```text
careerops-private-data/
|-- exports/
|   |-- applications.csv
|   |-- application_events.csv
|   |-- contacts.csv
|   |-- company_research_notes.csv
|   `-- email_feedback.csv
|-- snapshot/
|   `-- careerops.sql
`-- sync_manifest.json
```

Missing optional tables will produce an empty documented export instead of
failing the entire sync.

## Components

### `src/private_data_export.py`

- Reads `data/applications.db` in read-only usage.
- Writes deterministic UTF-8 CSV files ordered by stable identifiers.
- Writes a consistent SQLite SQL snapshot limited to approved tables and
  columns for private-data recovery.
- Writes a manifest containing the export format version, schema row counts,
  and a content fingerprint without volatile timestamps or local absolute
  paths.
- Writes files to a staging directory first and replaces destination files only
  after the export completes successfully.

### `src/private_data_sync.py`

- Accepts only the private repository `zqybw98/careerops-private-data`.
- Rejects mismatched remotes without echoing the configured remote URL or any
  embedded credentials.
- Verifies the exact GitHub owner, repository name, and `PRIVATE` visibility
  before synchronization.
- Stages only the exact repository-relative files returned by the exporter;
  unrelated files already present under `exports/` or `snapshot/` are ignored.
- Rejects any exporter path outside the private repository checkout before a
  commit or push can run.

### `sync_private_data.bat`

- Changes to the public project root using `%~dp0`.
- Uses `.venv\Scripts\python.exe` when available.
- Uses a configurable target path, defaulting to
  `%USERPROFILE%\Documents\CareerOps Private Data`.
- Runs the exporter.
- Initializes or validates the private Git checkout.
- Verifies that the configured GitHub repository is private before pushing.
- Refuses public, internal, unverifiable, or unexpected repositories.
- Commits with a timestamped message only when files changed.
- Pushes to `zqybw98/careerops-private-data`.
- Keeps the terminal open and prints a clear recovery step on failure.

## First-Time Setup

The first run will require GitHub CLI authentication. It will create the local
checkout and the GitHub repository with private visibility when they do not
already exist. Existing repositories will be reused after their owner, name,
remote URL, and visibility are validated. First-time initialization and daily
synchronization remain separate commands.

No GitHub token or credential will be written into the project or batch file.

## Data Safety

- The source SQLite database is never modified by synchronization.
- Export and Git failures do not affect the Tracker database.
- Real data remains ignored by the public repository through the existing
  `data/` rule.
- The script refuses to push when the destination repository is public or the
  remote does not match `zqybw98/careerops-private-data`.
- Remote validation errors never echo the configured URL, user information,
  query parameters, or credentials.
- Git stages only the exact files returned by the exporter. Extra files in the
  checkout are neither staged nor deleted automatically.
- CSV and SQL text provide reviewable Git history; the raw SQLite binary is not
  committed on every sync.
- Execution time appears only in terminal output. It is not written into the
  committed manifest, so unchanged data stays byte-identical.

## Verification

- Unit tests will cover deterministic export, missing optional tables, and
  manifest row counts.
- A local smoke test will export a temporary SQLite fixture.
- The batch workflow will be checked for first-run, no-change, changed-data,
  missing-authentication, and wrong-remote behavior.
- Existing project tests and quality checks will remain unchanged and be run
  after implementation.

## Non-Goals

- Automatic sync after every application update.
- Storing credentials in the repository.
- Publishing or sharing the private repository.
- Changing the current Streamlit database or application workflow.
- Adding cloud databases, external APIs, or scheduled background services.
