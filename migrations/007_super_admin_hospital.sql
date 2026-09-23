-- 007_super_admin_hospital.sql
-- Link super_admins to a specific hospital

ALTER TABLE super_admins ADD COLUMN IF NOT EXISTS hospital_id INTEGER REFERENCES hospitals(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_super_admins_hospital
    ON super_admins(hospital_id);
