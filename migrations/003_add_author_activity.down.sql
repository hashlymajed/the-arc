DROP INDEX IF EXISTS idx_draft_activity_draft_id;
DROP TABLE IF EXISTS draft_activity;
ALTER TABLE drafts DROP COLUMN author;
