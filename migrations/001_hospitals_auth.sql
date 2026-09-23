-- 001_hospitals_auth.sql
-- Add authentication fields to the hospitals table

ALTER TABLE hospitals ADD COLUMN IF NOT EXISTS username       TEXT;
ALTER TABLE hospitals ADD COLUMN IF NOT EXISTS password_hash  TEXT;
ALTER TABLE hospitals ADD COLUMN IF NOT EXISTS contact_person TEXT;
ALTER TABLE hospitals ADD COLUMN IF NOT EXISTS contact_email  TEXT;
ALTER TABLE hospitals ADD COLUMN IF NOT EXISTS county         TEXT;
ALTER TABLE hospitals ADD COLUMN IF NOT EXISTS sub_county     TEXT;
ALTER TABLE hospitals ADD COLUMN IF NOT EXISTS is_active      INTEGER DEFAULT 1;
ALTER TABLE hospitals ADD COLUMN IF NOT EXISTS created_at     TEXT;

-- Unique username index (only on non-null values)
CREATE UNIQUE INDEX IF NOT EXISTS idx_hospitals_username
    ON hospitals (username)
    WHERE username IS NOT NULL;