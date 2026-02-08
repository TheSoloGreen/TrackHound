-- Adds per-user ownership for root entities.
-- Backfill strategy:
-- 1) Use the oldest existing user as owner for legacy rows.
-- 2) If no users exist, create a bootstrap-owner user and assign legacy rows to it.

ALTER TABLE shows ADD COLUMN IF NOT EXISTS user_id INTEGER;
ALTER TABLE media_files ADD COLUMN IF NOT EXISTS user_id INTEGER;
ALTER TABLE scan_locations ADD COLUMN IF NOT EXISTS user_id INTEGER;

-- The runtime migration helper in app.models.migrations performs safe backfill and indexing
-- across SQLite/PostgreSQL, including bootstrap owner creation when needed.

CREATE INDEX IF NOT EXISTS ix_shows_user_id ON shows (user_id);
CREATE INDEX IF NOT EXISTS ix_media_files_user_id ON media_files (user_id);
CREATE INDEX IF NOT EXISTS ix_scan_locations_user_id ON scan_locations (user_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_scan_locations_user_path ON scan_locations (user_id, path);
