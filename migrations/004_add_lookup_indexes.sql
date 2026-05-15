CREATE INDEX IF NOT EXISTS idx_application_events_application_id
ON application_events(application_id);

CREATE INDEX IF NOT EXISTS idx_email_feedback_signature
ON email_feedback(email_signature);
