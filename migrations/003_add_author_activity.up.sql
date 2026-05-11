ALTER TABLE drafts ADD COLUMN author TEXT DEFAULT NULL;

CREATE TABLE IF NOT EXISTS draft_activity (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    draft_id   INTEGER NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
    author     TEXT    NOT NULL DEFAULT 'system',
    action     TEXT    NOT NULL,
    notes      TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_draft_activity_draft_id ON draft_activity(draft_id);
