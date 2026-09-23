-- 003_indexes.sql
-- Performance indexes for hospital-scoped queries

CREATE INDEX IF NOT EXISTS idx_patients_hospital_id
    ON patients (hospital_id);

CREATE INDEX IF NOT EXISTS idx_patients_status
    ON patients (status);

CREATE INDEX IF NOT EXISTS idx_messages_patient_id
    ON messages (patient_id);

CREATE INDEX IF NOT EXISTS idx_emergencies_patient_id
    ON emergencies (patient_id);

CREATE INDEX IF NOT EXISTS idx_emergencies_status
    ON emergencies (status);

CREATE INDEX IF NOT EXISTS idx_refill_requests_patient_id
    ON refill_requests (patient_id);

CREATE INDEX IF NOT EXISTS idx_treatments_patient_id
    ON treatments (patient_id);