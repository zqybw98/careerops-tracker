# CareerOps Tracker

A lightweight job application tracker and email classification assistant built with Python, Streamlit, and SQLite.

CareerOps Tracker helps job seekers structure applications, classify recruiting emails, and generate follow-up reminders from simple automation rules.

## Features

- Track companies, roles, locations, application dates, links, contacts, notes, and status.
- Classify recruiting emails as confirmation, recruiter reply, interview, assessment, rejection, follow-up, or other.
- Suggest application status updates from email classification results.
- Generate automated reminders for follow-ups, interviews, assessments, and stale applications.
- View a Streamlit dashboard with application metrics and status charts.
- Import and export applications with CSV.
- Keep Gmail API integration optional for future expansion.

## Tech Stack

- Python
- Streamlit
- SQLite
- pandas
- plotly
- pytest

## Project Structure

```text
.
├── app.py
├── requirements.txt
├── src/
│   ├── database.py
│   ├── dashboard.py
│   ├── email_classifier.py
│   ├── models.py
│   └── reminder_engine.py
├── tests/
│   ├── test_application_service.py
│   ├── test_email_classifier.py
│   └── test_reminder_engine.py
├── samples/
│   ├── sample_applications.csv
│   └── sample_emails.txt
└── docs/
    └── architecture.md
```

## Getting Started

Create and activate a virtual environment:

```bash
python -m venv .venv
```

On Windows PowerShell:

```bash
.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
streamlit run app.py
```

Run tests:

```bash
pytest
```

## Example Workflow

1. Add a job application.
2. Paste a recruiting email into the Email Assistant.
3. Review the detected category, confidence score, matched keywords, and suggested status.
4. Apply the suggested update to an existing application.
5. Use the dashboard to monitor waiting applications and follow-up tasks.

## Email Categories

- Application Confirmation
- Recruiter Reply
- Interview Invitation
- Assessment / Coding Test
- Rejection
- Follow-up Needed
- Other

## Why This Project

This project demonstrates practical automation, structured information management, and workflow tooling. It is intentionally small enough to complete in one to two weeks while still showing real business value for QA, automation, technical operations, and tooling roles.

## Future Improvements

- Optional Gmail API integration.
- Calendar reminders.
- Follow-up email template generator.
- ML-based email classification.
- Weekly job search report export.

## Screenshots

### Dashboard

![Dashboard](docs/screenshots/dashboard.png)

### Application Management

![Application Management](docs/screenshots/applications.png)

### Email Classification Assistant

![Email Classification Assistant](docs/screenshots/email-assistant.png)

### Application Records

![Application Records](docs/screenshots/recent-applications.png)