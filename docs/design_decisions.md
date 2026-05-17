# Design Decisions

CareerOps Tracker started as a compact portfolio MVP and evolved into a
local-first workflow tool for structured job-search operations. This document
captures the main engineering choices behind the project so reviewers can see
not only what the app does, but why it was built this way.

## 1. Rule-Based Classification Instead of ML

**Decision:** Use configurable rule-based email classification instead of a
machine-learning model.

**Why:** Recruiting emails are repetitive and usually contain strong signals:
confirmation phrases, interview invitations, assessment deadlines, rejection
language, follow-up wording, sender domains, and job titles. A deterministic
rules engine is easier to inspect, test, and explain.

**Benefits:**

- Predictable behavior for QA-style regression tests.
- Clear evidence for each classification result.
- No training dataset, model hosting, or API cost.
- Easier debugging when German, English, or Chinese phrases need adjustment.

**Tradeoff:** Rules will not understand every edge case. The app handles this
with confidence thresholds, manual review, and correction feedback instead of
pretending every result is fully automatic.

## 2. Local-First SQLite Storage

**Decision:** Store application records, activity events, and feedback locally
in SQLite.

**Why:** Job-search data is private. The core tracker should work without a
cloud database, external account, or network access.

**Benefits:**

- Easy local setup for students and portfolio reviewers.
- Data remains under the user's control.
- Enough structure for filtering, analytics, migrations, and export workflows.
- Simple backup path through CSV, SQLite file copy, and activity log export.

**Tradeoff:** SQLite is not intended for multi-user production collaboration.
That is acceptable because the project is scoped as a personal operations tool.

## 3. Configurable JSON Rules

**Decision:** Put classification, parsing, reminder, and job-post extraction
rules in JSON config files.

**Why:** Recruiting language changes over time, especially across German,
English, and Chinese emails. Rejection reasons, deadline phrases, role keywords,
and job-board patterns should be adjustable without rewriting core code.

**Benefits:**

- Separates business rules from application logic.
- Makes multilingual tuning easier.
- Keeps tests focused on behavior instead of hardcoded strings.
- Supports future rule updates without changing the Streamlit UI.

**Tradeoff:** JSON config needs validation. The project includes validation for
classification rules and keeps additional config validation as an incremental
quality improvement.

## 4. Optional Gmail Sync

**Decision:** Keep Gmail integration optional and read-only.

**Why:** OAuth setup can make a portfolio project feel heavy. The core value
should still work by pasting an email manually, while Gmail preview remains an
extra workflow for local use.

**Benefits:**

- The hosted demo remains safe and simple.
- Users can evaluate the app without granting mailbox access.
- Gmail dependencies stay isolated in `requirements-gmail.txt`.
- Manual paste, CSV import, and local workflows remain first-class paths.

**Tradeoff:** The app does not automatically mutate Gmail state or send replies.
This is intentional because mailbox actions should require explicit user
control.

## 5. Streamlit for Product UI

**Decision:** Use Streamlit instead of Flask or a heavier frontend stack.

**Why:** The project focuses on workflow automation, structured data, and
operations tooling rather than custom web infrastructure. Streamlit makes it
possible to build a usable dashboard, forms, CSV workflows, and analytics
quickly in Python.

**Benefits:**

- Fast iteration for a one-person portfolio project.
- Python-first implementation that matches the target roles.
- Built-in widgets for forms, tables, charts, file upload, and downloads.
- Easy deployment on Streamlit Community Cloud.

**Tradeoff:** Streamlit gives less control than a custom frontend. The project
manages this by keeping page modules small and moving business logic into
services and adapters.

## 6. Versioned Migrations Instead of Ad Hoc Schema Edits

**Decision:** Use ordered SQL migrations and a `schema_version` table.

**Why:** The data model grew from a simple applications table into activity
events, feedback records, indexes, and additional fields. Versioned migrations
make schema changes traceable and safer.

**Benefits:**

- Clear upgrade path for existing local databases.
- Better auditability than scattered `ALTER TABLE` checks.
- Easier regression testing of database initialization.

**Tradeoff:** The migration runner is intentionally lightweight instead of using
Alembic. That keeps the project approachable while still showing disciplined
schema evolution.

## 7. Human-in-the-Loop Automation

**Decision:** Email Assistant suggests updates, but the user reviews and applies
them.

**Why:** Job-search records are important and email classification can be
ambiguous. The app should automate repetitive interpretation while keeping the
final state change under user control.

**Benefits:**

- Prevents low-confidence emails from silently changing application status.
- Lets users adjust status, next action, follow-up date, and rejection reason
  before applying.
- Records correction feedback so future similar cases can improve.

**Tradeoff:** This is not a fully autonomous assistant. That is a deliberate
product choice: reliability and traceability matter more than speed alone.

## 8. Activity Log for Traceability

**Decision:** Track important changes as application events.

**Why:** A tracker should explain how a record got to its current state:
manual edits, CSV imports, email assistant updates, feedback corrections, and
status changes.

**Benefits:**

- Supports QA-style traceability.
- Makes debugging and data review easier.
- Creates a foundation for future analytics on process history.

**Tradeoff:** Activity history adds more data to manage. The app keeps the event
model simple and focused on useful workflow changes.

## 9. CSV Import and Export as Core Workflows

**Decision:** Treat CSV import/export as a core feature, not a fallback.

**Why:** Many job seekers already track applications in spreadsheets. A useful
tool should meet that workflow instead of forcing migration into a closed
system.

**Benefits:**

- Easy onboarding from existing job-search spreadsheets.
- Safer local backup and review.
- Practical support for iterative imports with created, updated, and unchanged
  records.

**Tradeoff:** CSV data can be messy. The app handles this with column mapping,
normalization, deduplication, and import previews.

## Summary

The project intentionally favors:

- explainable automation over black-box prediction,
- local data ownership over mandatory cloud services,
- configurable rules over hardcoded behavior,
- user-confirmed workflow updates over risky full automation,
- testable Python modules over one-off scripts.

These choices make CareerOps Tracker better aligned with QA, automation,
tooling, and technical operations work than a purely cosmetic dashboard would be.
