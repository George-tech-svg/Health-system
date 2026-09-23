-- 008_department_full.sql
-- Give departments real power: enquiries, treatments, patients, bookings

-- 1. Link treatments to departments
ALTER TABLE treatments ADD COLUMN IF NOT EXISTS department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_treatments_department ON treatments(department_id);

-- 2. Link messages to departments (per-department chats)
ALTER TABLE messages ADD COLUMN IF NOT EXISTS department_id INTEGER REFERENCES departments(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_messages_department ON messages(department_id);

-- 3. Appointments table
CREATE TABLE IF NOT EXISTS appointments (
    id SERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    appointment_date TEXT NOT NULL,
    time_slot TEXT,
    purpose TEXT,
    symptoms TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_appointments_patient ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_appointments_department ON appointments(department_id);
CREATE INDEX IF NOT EXISTS idx_appointments_status ON appointments(status);