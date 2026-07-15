# Private CareerOps Data Sync

This workflow stores real CareerOps data in the private GitHub repository
`zqybw98/careerops-private-data`. The public `careerops-tracker` repository
continues to ignore `data/`.

## Important Privacy Boundary

Git history is permanent unless it is explicitly rewritten. Review the export
policy before the first push. The private export intentionally includes job
search notes, contact details, source links, email feedback subjects, and email
signatures because they are part of the local Tracker workflow.

The exporter reads only these approved database fields:

- `applications`: `id`, `company`, `role`, `location`, `application_date`,
  `status`, `source_link`, `contact`, `notes`, `rejection_reason`,
  `next_action`, `follow_up_date`, `created_at`, `updated_at`.
- `application_events`: `id`, `application_id`, `event_type`, `old_value`,
  `new_value`, `source`, `created_at`.
- `email_feedback`: `id`, `email_signature`, `subject`,
  `predicted_category`, `predicted_status`, `corrected_category`,
  `corrected_status`, `corrected_application_id`, `corrected_company`,
  `corrected_role`, `source`, `created_at`.
- `schema_version`: `version`, `name`, `applied_at`.
- `company_research_notes`, when present: `id`, `company`, `checked_at`,
  `decision`, `relevant_roles`, `skipped_roles`, `summary`, `notes`,
  `source_link`, `created_at`, `updated_at`.
- `contacts.csv` is a deterministic view derived only from approved application
  fields: application ID, company, role, status, contact, source link, and last
  update.

The exporter does not scan project directories and never includes raw SQLite
files, WAL files, logs, caches, temporary files, `.env` files, tokens,
credentials, email bodies, attachments, or attachment paths. If an approved
database table gains an unapproved column, synchronization stops until the
policy is reviewed and updated.

## Prerequisites

1. Run `setup.bat` for the Tracker virtual environment.
2. Install Git and GitHub CLI (`gh`).
3. Sign in with `gh auth login` and confirm with `gh auth status`.

No token or credential is stored by the scripts.

## First-Time Initialization

Run this once:

```powershell
.\init_private_data_repo.bat
```

The command creates or clones only `zqybw98/careerops-private-data` with
private visibility. It refuses non-empty local targets and validates the
repository again after initialization. The default local checkout is:

```text
%USERPROFILE%\Documents\CareerOps Private Data
```

Use a different location when needed:

```powershell
.\init_private_data_repo.bat --target "D:\CareerOps Private Data"
```

Initialization does not export Tracker data. It is deliberately separate from
daily synchronization.

## Validate Without Pushing

Run this before the first sync and whenever the remote configuration changes:

```powershell
.\verify_private_data_sync.bat
```

Dry-run checks the exact Git remote, confirms GitHub visibility is `PRIVATE`,
exports into a temporary directory, lists the approved output files, and reports
whether data changed. It does not modify the private checkout, stage files,
create a commit, or push.

## Daily One-Click Sync

Double-click or run:

```powershell
.\sync_private_data.bat
```

The command validates the remote and private visibility before export. It then
writes deterministic CSV, SQL, and manifest files. If their bytes are unchanged,
the command exits without a commit or push. When data changed, it creates one
timestamped commit and pushes `main`. Git stages only the exact files returned
by the exporter; unrelated files in the checkout are left untouched and
unstaged.

## Exported Repository Layout

```text
careerops-private-data/
|-- exports/
|   |-- applications.csv
|   |-- application_events.csv
|   |-- company_research_notes.csv
|   |-- contacts.csv
|   `-- email_feedback.csv
|-- snapshot/
|   `-- careerops.sql
`-- sync_manifest.json
```

The SQL snapshot is generated from a single read-only transaction using stable
table, column, and row ordering. It is an allowlisted equivalent of SQLite
`.dump`; the live database file is never copied.

## Restore to a New Database

Restore into a new file for inspection. Do not overwrite the live Tracker
database while Streamlit is running.

From the private-data checkout:

```powershell
python -c "import sqlite3; from pathlib import Path; connection = sqlite3.connect('careerops-restored.db'); connection.executescript(Path('snapshot/careerops.sql').read_text(encoding='utf-8')); connection.close()"
```

Open and verify `careerops-restored.db` before replacing any local data. The
restore contains only the approved tables and columns listed above.

## Failure Behavior

- Export failure: no Git staging, commit, or push occurs.
- Wrong remote, wrong owner/name, public repository, invalid GitHub response,
  or failed authentication: synchronization stops before export.
- Remote validation errors do not echo the configured remote URL or embedded
  credentials.
- Exporter paths outside the private repository checkout stop synchronization
  before staging, commit, or push.
- Commit failure: exported local files remain available for inspection.
- Push failure: the export and local commit remain in the private checkout;
  fix authentication or network access and run `git push origin main` there.
- Tracker data is never modified by these workflows.

## Development Verification Status

Implementation and tests must be completed locally first. Do not run
`init_private_data_repo.bat` or `sync_private_data.bat` against the real GitHub
repository until the implementation results have been reviewed and approved.
