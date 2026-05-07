# Architecture

CareerOps Tracker is a lightweight local-first application.

## Main Flow

1. The user adds job applications through the Streamlit UI.
2. Application records are stored in SQLite.
3. The email assistant classifies pasted recruiting emails with explainable rules.
4. The reminder engine turns application status and dates into pending actions.
5. The dashboard summarizes the pipeline with metrics and charts.

## Components

- `app.py`: Streamlit interface.
- `src/database.py`: SQLite setup and CRUD operations.
- `src/email_classifier.py`: Rule-based email classification.
- `src/reminder_engine.py`: Follow-up and action reminder generation.
- `src/dashboard.py`: Summary metrics.
- `tests/`: Regression tests for workflow rules.

## Optional Future Module

Gmail API integration should stay optional. The MVP works with pasted email text so the app remains simple to run and easy to review.

