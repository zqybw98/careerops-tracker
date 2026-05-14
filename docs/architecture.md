# Architecture

CareerOps Tracker is a local-first Streamlit application for managing job
applications, classifying recruiting emails, and generating follow-up actions.
The MVP is intentionally small: it uses SQLite for persistence, deterministic
rules for automation, and pytest for regression coverage.

## System Goals

- Keep the tool easy to run locally with no external service dependency.
- Structure application data so the job search pipeline can be reviewed quickly.
- Convert unstructured recruiting emails into actionable status updates.
- Make automation decisions explainable through matched keywords and rule output.
- Keep Gmail API integration optional so the core project remains lightweight.

## High-Level Flow

```mermaid
flowchart LR
    User["User"] --> UI["Streamlit UI"]
    UI --> Services["Workflow services"]
    Services --> DB["SQLite database"]
    Services --> Classifier["Email classifier"]
    Services --> Reminders["Reminder engine"]
    DB --> Dashboard["Dashboard summary"]
    Classifier --> Services
    Reminders --> Services
    Services --> UI
    Dashboard --> UI
```

1. The user works through five sidebar workspaces: Overview, Applications,
   Contacts, Email Assistant, and Data & Settings.
2. The user adds or imports application records in the Streamlit interface.
3. The app stores records in a local SQLite database under `data/`.
4. The dashboard reads application records and builds pipeline metrics.
5. The assistant classifies pasted or optionally synced Gmail recruiting emails with transparent rules.
6. Suggested email outcomes can update an existing application.
7. The reminder engine turns dates and statuses into pending actions.

## Feature Coverage

This section mirrors the README feature list and maps each user-facing feature
area to the modules that implement it.

| Feature area | User-facing capability | Main modules |
| --- | --- | --- |
| Application tracking | Track company, role, location, dates, source links, contacts, notes, rejection reasons, statuses, next actions, searchable filters, stale-only views, and bulk maintenance actions. | `app.py`, `src/application_filters.py`, `src/database.py`, `src/models.py` |
| Contact CRM | Derive recruiter, hiring-manager, referral, source-channel, follow-up, and linked-application views from existing application records and activity events. | `app.py`, `src/contacts.py`, `src/database.py` |
| Import/export | Import English or Chinese CSV files, re-import updated files without duplicates, export records, load demo data, and clean older duplicate rows. | `src/csv_importer.py`, `src/demo_data.py`, `src/database.py` |
| Dashboard and editing | View pipeline metrics, status charts, pending actions, recent applications, decision analytics, funnel diagnostics, follow-up outcomes, and inline-edit key fields. | `src/dashboard.py`, `src/analytics.py`, `src/reminder_engine.py`, `app.py` |
| Email Assistant | Classify recruiting emails, extract application context, handle forwarded or mixed-language messages, rank top matches, apply confidence gates, save manual correction feedback, recommend next actions, and generate operation summaries. | `src/services/email_workflow.py`, `src/email_classifier.py`, `src/email_parser.py`, `src/email_feedback.py`, `src/email_insights.py`, `src/action_recommender.py` |
| Templates | Generate editable follow-up, interview thank-you, recruiter outreach, and rejection acknowledgement drafts. | `src/email_templates.py`, `app.py` |
| Activity traceability | Record creates, updates, imports, email-assistant actions, dashboard edits, duplicate cleanup, and deletes. | `src/database.py` |
| Configurable rules | Tune category keywords, parser patterns, matching thresholds, rejection reason patterns, and reminder timing without changing core logic. | `config/`, `src/config_loader.py` |
| Optional Gmail sync | Read recent recruiting emails locally with OAuth, preview classifications, and apply only user-approved actions. | `src/gmail_client.py`, `src/services/email_workflow.py` |
| Engineering quality | Run versioned SQLite migrations, linting, formatting, type checks, pytest, pre-commit hooks, CI, and tag-based releases. | `migrations/`, `pyproject.toml`, `.pre-commit-config.yaml`, `.github/workflows/tests.yml`, `.github/workflows/release.yml`, `CHANGELOG.md`, `tests/` |

## Components

| Component | Responsibility |
| --- | --- |
| `app.py` | Streamlit UI, tab routing, forms, import/export, and user interactions. Business workflows are delegated to services. |
| `config/` | JSON rule configuration for email classification, email parsing, matching thresholds, and reminder behavior. |
| `migrations/` | Ordered SQLite schema migrations applied at startup and tracked in `schema_version`. |
| `src/action_recommender.py` | Converts classified emails and extracted context into workflow decisions, prioritized next actions, follow-up dates, rationales, and suggested template types. |
| `src/analytics.py` | Builds decision-oriented metrics such as response rates, conversion, waiting days, monthly volume, stale pipeline breakdowns, response timing, rejection reasons, follow-up outcomes, funnels, and channel-role cross analysis. |
| `src/application_filters.py` | Applies Applications-page search filters, date-range filtering, stale-only filtering, and bulk action payload rules. |
| `src/contacts.py` | Builds a contact-centric mini CRM view from application contacts, source links, follow-up dates, and activity events. |
| `src/config_loader.py` | Loads typed JSON configuration for rule-based modules with a small cached API. |
| `src/database.py` | SQLite connection management, migration execution, CRUD, CSV sync imports, duplicate cleanup, and activity logging. |
| `src/csv_importer.py` | Normalizes English and Chinese CSV headers, dates, and statuses before import. |
| `src/models.py` | Shared status options, application columns, and classification result shape. |
| `src/dashboard.py` | Aggregates applications into total, weekly, waiting, interview, assessment, and rejection metrics. |
| `src/email_classifier.py` | Rule-based recruiting email classification with confidence scores and suggested next actions. |
| `src/email_feedback.py` | Builds email signatures, finds similar correction feedback, and applies category or application-match overrides. |
| `src/email_parser.py` | Extracts company, role, location, contact, source-link, deadline, interview-date, and rejection-reason hints from pasted or forwarded email text, then ranks existing application matches. |
| `src/email_insights.py` | Converts classification, extracted context, and ranked matches into explainable Email Assistant report rows. |
| `src/email_templates.py` | Generates rule-based follow-up, interview thank-you, recruiter outreach, and rejection acknowledgement emails. |
| `src/gmail_client.py` | Optional local Gmail API client that fetches read-only recruiting emails for preview classification. |
| `src/reminder_engine.py` | Generates follow-up, interview, assessment, stale-application, and saved-role reminders. |
| `src/services/email_workflow.py` | Orchestrates email classification, extracted context, application matching, workflow recommendations, note generation, and Gmail preview application. |
| `src/demo_data.py` | Loads portfolio-friendly sample data from `samples/sample_applications.csv` without duplicates. |
| `tests/` | Regression tests for database persistence, config loading, CSV import, email rules, workflow services, analytics, reminders, Gmail preview behavior, and demo data loading. |
| `pyproject.toml` | Central configuration for Ruff linting, Ruff formatting, and mypy type checking. |
| `.pre-commit-config.yaml` | Local hooks for lint auto-fix, formatting, and type checks before commits. |
| `.streamlit/config.toml` | Streamlit theme configuration used locally and in the hosted demo. |
| `.github/workflows/tests.yml` | Runs lint, format, type checks, and pytest on push and pull requests. |
| `.github/workflows/release.yml` | Creates tag-based GitHub Releases from matching `CHANGELOG.md` sections or GitHub-generated notes. |
| `CHANGELOG.md` | Human-maintained release history used by the release workflow. |
| `docs/deployment.md` | Deployment checklist for publishing the app on Streamlit Community Cloud. |

## Layering Direction

The codebase is moving toward a small three-layer structure:

- `app.py` and future `ui/` modules own display, forms, widgets, and session state.
- `src/services/` owns workflow orchestration that combines classifiers, parsers,
  recommendations, database writes, and note generation.
- Boundary modules such as `src/database.py`, `src/gmail_client.py`, and
  `src/csv_importer.py` act as adapters around persistence and external inputs.

This keeps user-interface changes separate from business workflow decisions, which
is useful as the assistant grows beyond pasted email classification.

## Data Model

The MVP stores application records and traceability events in SQLite.

Schema changes are versioned through lightweight SQL migrations in
`migrations/`. At startup, `init_db()` creates the `schema_version` table, reads
applied versions, and applies missing migrations in filename order. Existing
databases that already satisfy a migration are baselined by recording the
version without rerunning unsafe `ALTER TABLE` statements.

### `applications`

| Field | Purpose |
| --- | --- |
| `id` | Auto-incrementing primary key. |
| `company` | Target company name. |
| `role` | Job title or internship title. |
| `location` | Role location, for example Berlin or Germany. |
| `application_date` | Date when the application was submitted or saved. |
| `status` | Pipeline state such as `Applied`, `Interview Scheduled`, `Assessment`, or `Rejected`. |
| `source_link` | Job post or company career page URL. |
| `contact` | Recruiter or contact email/name. |
| `notes` | Free-form application notes. |
| `rejection_reason` | Optional rejected-application context used for later review and analytics. |
| `next_action` | Human-readable next step. |
| `follow_up_date` | Date used by the reminder engine. |
| `created_at` | UTC timestamp for record creation. |
| `updated_at` | UTC timestamp for the latest update. |

### `application_events`

| Field | Purpose |
| --- | --- |
| `id` | Auto-incrementing event id. |
| `application_id` | Application record affected by the event. |
| `event_type` | Event name such as `application_created`, `status_changed`, or `application_deleted`. |
| `old_value` | Previous value or previous application summary. |
| `new_value` | New value or new application summary. |
| `source` | Actor/source such as `manual`, `csv_import`, `dashboard_inline_edit`, `email_assistant`, `email_next_action`, `gmail_sync`, `demo_data`, or `duplicate_cleanup`. |
| `created_at` | UTC timestamp when the event was recorded. |

### `schema_version`

| Field | Purpose |
| --- | --- |
| `version` | Numeric migration version from the SQL filename. |
| `name` | Migration filename stem, for example `002_add_rejection_reason`. |
| `applied_at` | UTC timestamp when the migration was applied or baselined. |

### `email_feedback`

| Field | Purpose |
| --- | --- |
| `id` | Auto-incrementing feedback id. |
| `email_signature` | Normalized token signature used to compare similar future emails. |
| `subject` | Original email subject used when the correction was saved. |
| `predicted_category` | Category predicted before the user corrected the assistant. |
| `predicted_status` | Suggested status predicted before correction. |
| `corrected_category` | User-approved email category. |
| `corrected_status` | User-approved suggested application status. |
| `corrected_application_id` | User-approved application match, if one was selected. |
| `corrected_company` | Snapshot of the corrected application company. |
| `corrected_role` | Snapshot of the corrected application role. |
| `source` | Feedback source, currently `manual_feedback`. |
| `created_at` | UTC timestamp when the correction was recorded. |

The database is local and ignored by Git (`data/`), so sample data and tests
can be shared without exposing personal job search records.

## Activity Logging

Every create, update, delete, CSV sync import, dashboard inline edit,
email-assistant update, Gmail sync action, demo-data load, and duplicate-cleanup
action can write an event to `application_events`.
The application management view shows the selected record's activity log, which
improves traceability and makes status changes auditable.

Rejected applications can also store a dedicated `rejection_reason`. This keeps
the main application table readable while preserving useful review context such
as no interview, after HR screen, position closed, experience mismatch, or
language/location mismatch. Changes to this field are recorded in the activity
log like other application updates.

## Application Statuses

Statuses are centralized in `src/models.py` to keep the UI, classifier, and
reminder rules aligned:

- `Saved`
- `Applied`
- `Confirmation Received`
- `Interview Scheduled`
- `Assessment`
- `Offer`
- `Rejected`
- `No Response`
- `Follow-up Needed`

Closed statuses are `Rejected` and `Offer`; the reminder engine skips these.

## Email Classification Design

The classifier is rule-based rather than ML-based. This is deliberate for the
MVP because recruiting email patterns are repetitive and explainability matters.
It includes English, German, and Chinese recruiting phrases for the most common
workflow categories.

## Configurable Rule Layer

Rules that are likely to change during job-search usage live in JSON files under
`config/` rather than being hard-coded directly in the business logic:

| Config file | Controls |
| --- | --- |
| `config/email_classification_rules.json` | Email categories, multilingual keywords, suggested statuses, suggested next actions, follow-up intervals, default fallback behavior, and confidence scoring parameters. |
| `config/email_parser_rules.json` | Application matching thresholds, generic email domains, role stop words, common locations, date-context keywords, extraction regex patterns, email intent keywords, and rejection-reason patterns. |
| `config/reminder_rules.json` | Reminder priorities, messages, reasons, waiting-day thresholds, status scopes, and default assessment due-date behavior. |

`src/config_loader.py` exposes typed helper functions so the rest of the code can
ask for classification, parser, or reminder configuration without depending on
file paths or JSON parsing. This keeps the MVP deterministic and testable while
making future tuning cheaper: adding a new German rejection phrase, changing a
follow-up interval, or tightening the auto-match threshold no longer requires
editing classifier or parser logic.

Each rule contains:

- a category, such as `Interview Invitation` or `Rejection`
- a suggested application status
- a suggested next action
- an optional follow-up interval
- keywords that explain why the rule matched

When an email is classified, the app returns the category, confidence score,
matched keywords, suggested status, and suggested next action. If no rule
matches, the email is classified as `Other` and routed to manual review.

The email assistant also extracts lightweight application context from pasted
email content. It looks for company names, role titles, locations,
sender/contact details, source links, deadlines, interview dates, and rejection
reasons, then compares those hints against existing application records. When a
confident match is found, the matched application is pre-selected for the user.
If no match exists, the same extracted context can prefill a new application
record.

Existing-application matching uses an explainable score rather than a single
string comparison. The matcher combines company identity, role-title similarity,
role keyword overlap, sender/source domain hints, location hints, and status
context. It also uses a minimum score and an ambiguity margin so company-only
emails from employers with multiple open roles are routed to manual selection
instead of being applied to the wrong record.

The action recommender turns the classified email and extracted fields into a
workflow decision and an operational next step. It decides whether the safest
action is to update status, save only a task, confirm a candidate match, close a
rejection, or create a new record. It then prioritizes actions such as interview
preparation, assessment submission, recruiter replies, rejection review, or
scheduled follow-up. Each recommendation includes priority, review level,
follow-up date, template type, rationale, and explicit record/status actions.
Status updates pass through a confidence gate: `>= 85%` is ready after quick
review, `60% - 84%` requires explicit user confirmation, and `< 60%` blocks
status updates so the user can only save a task or review manually.

The same decision context is converted into an operation summary. This summary
explains the classified email type, confidence gate, target application,
matching evidence, status action, and next step. When an Email Assistant action
is applied, the summary is appended to the application notes so later review can
trace why the update happened.

The assistant also has a manual correction loop. When the user corrects the
category, suggested status, or matched application, the correction is stored as
`email_feedback` with a normalized signature of the email. Future similar emails
are checked against recent feedback before workflow actions are applied. A
matching correction raises confidence, adds a visible `manual feedback override`
keyword, and can promote the corrected application as the top match. This keeps
the behavior deterministic while making the assistant feel adaptive without
requiring an ML model.

## Email Template Generation

The Templates tab generates editable, rule-based career email drafts from an
existing application record. Template selection can be suggested from application
status, for example rejected applications default toward acknowledgement emails
and interview records default toward thank-you emails. This keeps the workflow
lightweight while connecting reminders, statuses, and recruiting communication.

## Reminder Rules

The reminder engine converts structured application data into pending actions:

| Condition | Reminder |
| --- | --- |
| Follow-up date is due | High priority follow-up reminder. |
| Status is `Interview Scheduled` | Prepare interview notes and confirm logistics. |
| Status is `Assessment` | Work on assessment and check the deadline. |
| Application is open for 7+ days | Consider a polite follow-up. |
| Application is open for 14+ days | Consider follow-up or mark as no response. |
| Status is `Saved` | Decide whether to apply. |

This keeps the automation simple and deterministic while still providing
practical value for job search operations.

## Decision Analytics

The dashboard includes a decision-oriented analytics layer rather than only raw
record counts. `src/analytics.py` derives:

- response rate by inferred source, such as LinkedIn, StepStone, or career page
- interview/assessment conversion rate by inferred role type
- average active waiting days by company
- applications per calendar month
- stale pipeline breakdown for open applications
- saved-only versus submitted application volume
- time-to-first-response by source, using status history when available
- rejection reason breakdown from structured rejection notes
- follow-up effectiveness by current outcome after a follow-up was planned
- interview-to-offer funnel from current and historical statuses
- channel x role-type cross analysis for prioritizing sourcing effort

Sources and role types are inferred from lightweight rules so the analytics stay
transparent and testable. These metrics help answer operational questions such
as which channels are responding, where the pipeline is stale, which role types
are converting into interviews or assessments, and which follow-up or sourcing
patterns deserve more attention.

## Import, Export, and Demo Data

CSV import/export makes the tool portable and easy to review. The expected CSV
columns are defined in `src/models.py` as `APPLICATION_COLUMNS`. The importer
also supports common Chinese headers such as `公司名称`, `职位名称`, `申请日期`,
`最新状态`, `拒绝原因`, and `备注/来源`, then normalizes them into the internal
application schema.

The Data tab also includes `Load sample applications`, which imports demo rows
from `samples/sample_applications.csv`. The loader checks company, role, and
application date to avoid creating duplicates when clicked multiple times.

CSV imports use a sync strategy instead of append-only inserts. If an imported
row matches an existing record by normalized company, role, and application
date, the app updates the existing record and merges notes. Otherwise it creates
a new record. A maintenance action can remove duplicate records that were
created by older append-only imports.

## Testing Strategy

The project uses pytest for fast regression tests:

- database tests verify application creation, updates, sync imports, duplicate cleanup, activity events, and email feedback persistence
- email classifier tests verify core recruiting email categories
- email workflow tests verify manual correction feedback overrides for similar future emails
- email template tests verify suggested template types and generated draft content
- reminder tests verify follow-up, interview, assessment, and closed-status logic
- demo data tests verify sample CSV loading and idempotent import behavior

GitHub Actions runs the same test suite on every push and pull request to
demonstrate basic CI discipline. The CI pipeline also runs `ruff check`,
`ruff format --check`, and `mypy src` so formatting, linting, type hints, and
regression tests are checked together.

Pre-commit hooks run the same local quality gates before commits:

- `ruff check --fix`
- `ruff format`
- `mypy src`

## Optional Gmail Module

Gmail integration is optional and isolated from the local workflow:

```text
Gmail API -> read-only email fetcher -> existing classifier -> preview -> user-applied update
```

The Gmail client uses `https://www.googleapis.com/auth/gmail.readonly`, stores
OAuth files locally as `credentials.json` and `token.json`, and does not modify
the mailbox. The core app continues to work with pasted email text when Gmail
dependencies or credentials are not configured, which keeps the hosted demo and
reviewer setup simple.

## Deployment Model

The hosted demo target is Streamlit Community Cloud. The repository is organized
so the platform can run the app directly from the root:

- entry point: `app.py`
- dependency file: `requirements.txt`
- visual configuration: `.streamlit/config.toml`
- recommended Python version: `3.13`

The deployed SQLite database is suitable for demo usage. Long-term production
usage would require a persistent hosted database, but that is intentionally out
of scope for this portfolio MVP.

## Design Decisions

- **Streamlit over Flask:** faster to build a useful dashboard and forms for a
  one-to-two-week portfolio project.
- **SQLite over hosted database:** no deployment dependency and enough structure
  for CRUD, filtering, and export workflows.
- **Rules over ML:** explainable output, predictable tests, and no training data
  requirement.
- **Local-first storage:** protects personal application data and keeps the demo
  reproducible.
- **Optional integrations:** external APIs can be added later without weakening
  the MVP.
