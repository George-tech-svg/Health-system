-- 006_super_admin.sql
-- Super Admin (hospital Director) + Department-to-Department internal messaging

CREATE TABLE IF NOT EXISTS super_admins (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    is_active INTEGER DEFAULT 1,
    last_login TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS internal_messages (
    id SERIAL PRIMARY KEY,
    from_department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    to_department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    patient_id TEXT,
    content TEXT NOT NULL,
    is_read INTEGER DEFAULT 0,
    read_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_internal_messages_from
    ON internal_messages(from_department_id);

CREATE INDEX IF NOT EXISTS idx_internal_messages_to
    ON internal_messages(to_department_id);

CREATE INDEX IF NOT EXISTS idx_internal_messages_patient
    ON internal_messages(patient_id);

CREATE TABLE IF NOT EXISTS referral_summaries (
    id SERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL,
    from_department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    to_department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_referral_summaries_patient
    ON referral_summaries(patient_id);

CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    hospital_id INTEGER,
    department_id INTEGER,
    patient_id TEXT,
    action TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_activity_log_created
    ON activity_log(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_activity_log_hospital
    ON activity_log(hospital_id);

CREATE INDEX IF NOT EXISTS idx_activity_log_department
    ON activity_log(department_id);

CREATE INDEX IF NOT EXISTS idx_activity_log_patient
    ON activity_log(patient_id);