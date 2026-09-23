-- 002_patients_hospital_link.sql
-- Link patients to hospitals

ALTER TABLE patients ADD COLUMN IF NOT EXISTS hospital_id         INTEGER;
ALTER TABLE patients ADD COLUMN IF NOT EXISTS registration_source TEXT DEFAULT 'hospital';

-- Assign any unlinked patients to the first hospital (fallback)
UPDATE patients
SET hospital_id = (SELECT id FROM hospitals ORDER BY id LIMIT 1)
WHERE hospital_id IS NULL;

-- Set registration_source for existing patients
UPDATE patients
SET registration_source = 'hospital'
WHERE registration_source IS NULL;

-- Foreign key constraint
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE constraint_name = 'fk_patients_hospital'
    ) THEN
        ALTER TABLE patients
        ADD CONSTRAINT fk_patients_hospital
        FOREIGN KEY (hospital_id) REFERENCES hospitals(id)
        ON DELETE SET NULL;
    END IF;
END $$;