-- A NULL job_id identifies a company portal. Job rows track individual openings.
CREATE TABLE IF NOT EXISTS applications (
    company_name TEXT NOT NULL,
    career_page_url TEXT,
    last_checked_at TEXT,
    application_id INTEGER UNIQUE,
    job_id TEXT,
    job_name TEXT,
    job_link TEXT,
    source_portal_url TEXT,
    applied_at TEXT,
    questions_answers_json TEXT
        CHECK (questions_answers_json IS NULL OR json_valid(questions_answers_json)),
    status TEXT NOT NULL DEFAULT 'not_checked'
        CHECK (status IN ('not_checked', 'checked', 'in_progress', 'applied', 'failed_to_apply')),
    status_notes_json TEXT NOT NULL DEFAULT '[]',
    CHECK ((job_id IS NULL) = (status IN ('not_checked', 'checked'))),
    UNIQUE (company_name, job_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS applications_company_portal_unique
    ON applications (company_name) WHERE job_id IS NULL;
