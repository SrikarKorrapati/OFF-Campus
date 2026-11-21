-- A NULL job_id identifies a company portal. Job rows record application outcomes.
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
        CHECK (status IN ('not_checked', 'checked', 'applied', 'failed_to_apply')),
    status_notes_json TEXT NOT NULL DEFAULT '[]'
        CHECK (CASE WHEN json_valid(status_notes_json) THEN
            (job_id IS NULL) = (status IN ('not_checked', 'checked'))
            AND json_type(status_notes_json) = 'array'
            AND json_array_length(status_notes_json) BETWEEN (status = 'failed_to_apply') AND 5
            AND coalesce(json_type(status_notes_json, '$[0]') = 'text'
                         AND trim(json_extract(status_notes_json, '$[0]'), char(9, 32)) <> '', 1)
            AND coalesce(json_type(status_notes_json, '$[1]') = 'text'
                         AND trim(json_extract(status_notes_json, '$[1]'), char(9, 32)) <> '', 1)
            AND coalesce(json_type(status_notes_json, '$[2]') = 'text'
                         AND trim(json_extract(status_notes_json, '$[2]'), char(9, 32)) <> '', 1)
            AND coalesce(json_type(status_notes_json, '$[3]') = 'text'
                         AND trim(json_extract(status_notes_json, '$[3]'), char(9, 32)) <> '', 1)
            AND coalesce(json_type(status_notes_json, '$[4]') = 'text'
                         AND trim(json_extract(status_notes_json, '$[4]'), char(9, 32)) <> '', 1)
            AND printf('%s%s%s%s%s', json_extract(status_notes_json, '$[0]'),
                       json_extract(status_notes_json, '$[1]'), json_extract(status_notes_json, '$[2]'),
                       json_extract(status_notes_json, '$[3]'), json_extract(status_notes_json, '$[4]'))
                NOT GLOB ('*[' || char(10, 11, 12, 13, 28, 29, 30, 133, 8232, 8233) || ']*')
        ELSE 0 END),
    UNIQUE (company_name, job_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS applications_company_portal_unique
    ON applications (company_name) WHERE job_id IS NULL;
