CREATE TABLE IF NOT EXISTS company_research_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    decision TEXT,
    relevant_roles TEXT,
    skipped_roles TEXT,
    summary TEXT,
    notes TEXT,
    source_link TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_company_research_company
ON company_research_notes(company);

CREATE INDEX IF NOT EXISTS idx_company_research_checked_at
ON company_research_notes(checked_at);
