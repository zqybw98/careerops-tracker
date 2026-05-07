# CareerOps Tracker

[![Python Tests](https://github.com/zqybw98/careerops-tracker/actions/workflows/tests.yml/badge.svg)](https://github.com/zqybw98/careerops-tracker/actions/workflows/tests.yml)

A lightweight job application tracker and email classification assistant built with Python, Streamlit, and SQLite.

CareerOps Tracker helps job seekers structure applications, classify recruiting emails, and generate follow-up reminders from simple automation rules.

## Features

- Track companies, roles, locations, application dates, links, contacts, notes, and status.
- Classify recruiting emails as confirmation, recruiter reply, interview, assessment, rejection, follow-up, or other.
- Extract company, role, contact, and source-link hints from pasted recruiting emails.
- Suggest application status updates from email classification results.
- Match recruiting emails to existing applications or create a new application from email context.
- Generate automated reminders for follow-ups, interviews, assessments, and stale applications.
- View a Streamlit dashboard with application metrics and status charts.
- Load demo applications to preview the dashboard immediately after setup.
- Import and export applications with CSV, including common English and Chinese headers.
- Re-import updated CSV files without creating duplicate application records.
- Keep Gmail API integration optional for future expansion.

## Screenshots

### Dashboard

![Dashboard](docs/screenshots/dashboard.png)

### Application Records

![Application Records](docs/screenshots/recent-applications.png)

### Email Classification Assistant

![Email Classification Assistant](docs/screenshots/email-assistant.png)

### Application Management

![Application Management](docs/screenshots/applications.png)

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
|-- app.py
|-- requirements.txt
|-- src/
|   |-- database.py
|   |-- csv_importer.py
|   |-- dashboard.py
|   |-- demo_data.py
|   |-- email_classifier.py
|   |-- email_parser.py
|   |-- models.py
|   `-- reminder_engine.py
|-- tests/
|   |-- test_application_service.py
|   |-- test_csv_importer.py
|   |-- test_demo_data.py
|   |-- test_email_classifier.py
|   |-- test_email_parser.py
|   `-- test_reminder_engine.py
|-- samples/
|   |-- sample_applications.csv
|   `-- sample_emails.txt
`-- docs/
    `-- architecture.md
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
3. Review the detected category, confidence score, extracted application context, and suggested status.
4. Apply the suggested update to a matched application or create a new application from the email.
5. Use the dashboard to monitor waiting applications and follow-up tasks.

For a quick demo, open the Data tab and click `Load sample applications`.

The CSV importer supports the default English columns and common Chinese headers
such as `公司名称`, `职位名称`, `申请日期`, `最新状态`, and `备注/来源`.
When the same company, role, and application date already exist, CSV import
updates the existing record instead of adding a duplicate.

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
