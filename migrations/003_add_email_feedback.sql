CREATE TABLE IF NOT EXISTS email_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_signature TEXT NOT NULL,
    subject TEXT,
    predicted_category TEXT,
    predicted_status TEXT,
    corrected_category TEXT,
    corrected_status TEXT,
    corrected_application_id INTEGER,
    corrected_company TEXT,
    corrected_role TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL
);
