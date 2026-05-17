# Changelog

All notable changes to CareerOps Tracker are documented here.

The release workflow reads the section matching the pushed tag, such as
`v0.1.0`, and uses it as the GitHub Release body. If a tag does not have a
matching section, GitHub generates release notes automatically.

## [Unreleased]

## [v0.2.1] - 2026-05-17

### Added

- CSV import preview with created, updated, unchanged, skipped, and field-overwrite details before writing to SQLite.
- Backup downloads for application CSV data, the activity log, and the local SQLite database.
- Pending Actions queue controls for marking reminders done, snoozing by 3 or 7 days, and opening the related application.
- Project-level `AGENTS.md` instructions for keeping future changes small, reviewable, and testable.

### Changed

- Overview now defaults to the active pipeline while keeping closed applications available behind a toggle.
- Email Assistant recommendations can be manually reviewed and adjusted before applying status, next-action, follow-up, and rejection-reason updates.
- Runtime validation for email parser, reminder, and job-post configuration files.
- README documentation now includes `job_post_rules.json` in the configurable rules section.

### Fixed

- Calendar export date range defaults now pass valid Streamlit date values.

## [v0.2.0] - 2026-05-16

### Added

- Configurable automation rules for email categories, parser patterns, match thresholds, and reminders.
- Versioned SQLite migrations with a lightweight `schema_version` table.
- Activity log support for application changes and assistant-driven updates.
- Decision analytics, inline dashboard editing, and richer Email Assistant recommendations.
- Manual correction feedback for email category, suggested status, and matched application preferences.
- Applications-page search, date-range filtering, stale-only filtering, and bulk maintenance actions.
- Decision analytics for time-to-first-response, rejection reason breakdown, follow-up outcomes, interview-to-offer funnel, and channel x role-type combinations.
- Realistic email edge-case coverage for forwarded messages, quoted replies, similar same-company roles, multiple dates, mismatch-based rejections, domain-only recruiter hints, and long mixed-language messages.
- Contact-centric mini CRM workspace for recruiter, hiring-manager, referral, channel, last-activity, follow-up, and linked-application views.
- Calendar export for interview, assessment, offer follow-up, and follow-up dates as `.ics` files and copyable text blocks.
- Job Post Intake workflow that extracts draft application records from pasted JDs or job URLs and creates Saved applications after user confirmation.
- Germany-focused multilingual support for German recruiting phrases, rejection reason taxonomy, visa/work-authorization hints, Germany-specific source tagging, and English/German/Chinese email templates.

### Changed

- Project documentation now maps feature areas to implementation modules.
- Database-focused tests were renamed for clearer ownership.
- No Response applications no longer create stale follow-up reminders unless a follow-up date is explicitly set.
- Forwarded email parsing now prefers the original recruiter sender over personal mail forwarding wrappers.

## [v0.1.0] - 2026-05-07

### Added

- Streamlit dashboard for job application tracking.
- SQLite persistence with CSV import/export.
- Rule-based recruiting email classification assistant.
- Follow-up and pending-action reminder engine.
- Demo data loader for quick project review.
- Pytest regression test suite with GitHub Actions CI.
- Architecture documentation for engineering review.
