CREATE TABLE IF NOT EXISTS capture_requests (
    client_request_id TEXT PRIMARY KEY,
    payload_sha256 TEXT NOT NULL,
    application_id INTEGER NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);
