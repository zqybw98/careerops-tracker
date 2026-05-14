# Changelog

All notable changes to CareerOps Tracker are documented here.

The release workflow reads the section matching the pushed tag, such as
`v0.1.0`, and uses it as the GitHub Release body. If a tag does not have a
matching section, GitHub generates release notes automatically.

## [Unreleased]

### Added

- Configurable automation rules for email categories, parser patterns, match thresholds, and reminders.
- Versioned SQLite migrations with a lightweight `schema_version` table.
- Activity log support for application changes and assistant-driven updates.
- Decision analytics, inline dashboard editing, and richer Email Assistant recommendations.
- Manual correction feedback for email category, suggested status, and matched application preferences.
- Applications-page search, date-range filtering, stale-only filtering, and bulk maintenance actions.

### Changed

- Project documentation now maps feature areas to implementation modules.
- Database-focused tests were renamed for clearer ownership.
- No Response applications no longer create stale follow-up reminders unless a follow-up date is explicitly set.

## [v0.1.0] - 2026-05-07

### Added

- Streamlit dashboard for job application tracking.
- SQLite persistence with CSV import/export.
- Rule-based recruiting email classification assistant.
- Follow-up and pending-action reminder engine.
- Demo data loader for quick project review.
- Pytest regression test suite with GitHub Actions CI.
- Architecture documentation for engineering review.
