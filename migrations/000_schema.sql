-- 000_schema.sql
-- Full schema for AFYAHIV CARE (PostgreSQL / Neon)

-- ============================================================
-- PATIENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS patients (
    id SERIAL PRIMARY KEY,
    patient_id TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    location TEXT,
    arv_regimen TEXT,
    medication_time TEXT,
    registration_date TEXT,
    status TEXT DEFAULT 'active',
    hospital_id INTEGER,
    registration_source TEXT DEFAULT 'hospital'
);

-- ============================================================
-- MESSAGES
-- ============================================================
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL,
    direction TEXT CHECK (direction IN ('incoming', 'outgoing')),
    type TEXT CHECK (type IN ('sms', 'voice', 'ussd', 'video')),
    content TEXT NOT NULL,
    language TEXT,
    risk_level TEXT DEFAULT 'low',
    symptoms_detected TEXT,
    response_sent TEXT,
    timestamp TEXT,
    is_read INTEGER DEFAULT 0,
    is_emergency INTEGER DEFAULT 0,
    audio_file TEXT,
    video_file TEXT,
    parent_message_id INTEGER DEFAULT NULL,
    reply_to_id INTEGER DEFAULT NULL,
    is_delivered INTEGER DEFAULT 0,
    is_read_by_receiver INTEGER DEFAULT 0,
    is_deleted INTEGER DEFAULT 0,
    is_pinned INTEGER DEFAULT 0
);

-- ============================================================
-- PROVIDERS (legacy — kept for backward compatibility)
-- ============================================================
CREATE TABLE IF NOT EXISTS providers (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    full_name TEXT,
    role TEXT DEFAULT 'doctor',
    hospital TEXT,
    is_active INTEGER DEFAULT 1
);

-- ============================================================
-- ADHERENCE
-- ============================================================
CREATE TABLE IF NOT EXISTS adherence (
    id SERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL,
    date TEXT NOT NULL,
    dose_taken INTEGER DEFAULT 0,
    reminder_sent INTEGER DEFAULT 0,
    notes TEXT
);

-- ============================================================
-- VILLAGES
-- ============================================================
CREATE TABLE IF NOT EXISTS villages (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL
);

-- ============================================================
-- HOSPITALS (with auth columns)
-- ============================================================
CREATE TABLE IF NOT EXISTS hospitals (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    village TEXT NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    level INTEGER,
    phone TEXT,
    address TEXT,
    opening_hours TEXT,
    username TEXT,
    password_hash TEXT,
    contact_person TEXT,
    contact_email TEXT,
    county TEXT,
    sub_county TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_hospitals_username
    ON hospitals (username)
    WHERE username IS NOT NULL;

-- ============================================================
-- HOSPITAL DISTANCES
-- ============================================================
CREATE TABLE IF NOT EXISTS hospital_distances (
    id SERIAL PRIMARY KEY,
    village_name TEXT NOT NULL,
    hospital_name TEXT NOT NULL,
    distance_km DOUBLE PRECISION NOT NULL,
    travel_time_minutes INTEGER NOT NULL,
    directions TEXT
);

-- ============================================================
-- FAILED LOGINS
-- ============================================================
CREATE TABLE IF NOT EXISTS failed_logins (
    id SERIAL PRIMARY KEY,
    username TEXT,
    phone_number TEXT,
    attempt_time TEXT NOT NULL,
    ip_address TEXT
);

-- ============================================================
-- AUDIT LOGS
-- ============================================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_type TEXT NOT NULL,
    user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    ip_address TEXT,
    timestamp TEXT NOT NULL
);

-- ============================================================
-- REFILL REQUESTS
-- ============================================================
CREATE TABLE IF NOT EXISTS refill_requests (
    id SERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL,
    patient_name TEXT NOT NULL,
    medication_name TEXT NOT NULL,
    dosage TEXT,
    last_dose_date TEXT,
    preferred_pickup_date TEXT,
    preferred_pickup_time TEXT,
    request_date TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    approved_date TEXT,
    approved_pickup_date TEXT,
    approved_pickup_time TEXT,
    doctor_notes TEXT,
    new_medication_time TEXT,
    cancelled_by_patient INTEGER DEFAULT 0,
    cancel_reason TEXT
);

-- ============================================================
-- EMERGENCIES
-- ============================================================
CREATE TABLE IF NOT EXISTS emergencies (
    id SERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL,
    patient_name TEXT NOT NULL,
    emergency_message TEXT NOT NULL,
    communication_preference TEXT CHECK (communication_preference IN ('text_only', 'audio_only', 'either')),
    priority_level TEXT DEFAULT 'high',
    location_lat DOUBLE PRECISION,
    location_lng DOUBLE PRECISION,
    location_address TEXT,
    status TEXT DEFAULT 'active',
    timestamp TEXT NOT NULL,
    resolved_timestamp TEXT,
    doctor_response_timestamp TEXT,
    escalation_sent INTEGER DEFAULT 0,
    escalation_timestamp TEXT
);

-- ============================================================
-- EMERGENCY CONTACTS
-- ============================================================
CREATE TABLE IF NOT EXISTS emergency_contacts (
    id SERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL,
    name TEXT NOT NULL,
    phone_number TEXT NOT NULL,
    relationship TEXT,
    is_primary INTEGER DEFAULT 0,
    shared_with_doctor INTEGER DEFAULT 0
);

-- ============================================================
-- EMERGENCY MESSAGES
-- ============================================================
CREATE TABLE IF NOT EXISTS emergency_messages (
    id SERIAL PRIMARY KEY,
    emergency_id INTEGER NOT NULL,
    sender_type TEXT CHECK (sender_type IN ('patient', 'doctor')),
    message_type TEXT CHECK (message_type IN ('text', 'audio')),
    content TEXT,
    audio_file TEXT,
    timestamp TEXT NOT NULL,
    is_read INTEGER DEFAULT 0
);

-- ============================================================
-- EMERGENCY LOCATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS emergency_locations (
    id SERIAL PRIMARY KEY,
    emergency_id INTEGER NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    accuracy DOUBLE PRECISION,
    speed DOUBLE PRECISION,
    heading DOUBLE PRECISION,
    timestamp TEXT NOT NULL
);

-- ============================================================
-- TREATMENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS treatments (
    id SERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL,
    doctor_name TEXT NOT NULL,
    treatment_date TEXT NOT NULL,
    diagnosis TEXT,
    notes TEXT,
    next_appointment_date TEXT,
    next_appointment_reason TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL
);

-- ============================================================
-- PRESCRIBED MEDICATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS prescribed_medications (
    id SERIAL PRIMARY KEY,
    treatment_id INTEGER NOT NULL,
    medication_name TEXT NOT NULL,
    dosage_amount TEXT NOT NULL,
    dosage_unit TEXT DEFAULT 'pill(s)',
    times_per_day INTEGER NOT NULL,
    schedule_times TEXT NOT NULL,
    duration_days INTEGER,
    instructions TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

-- ============================================================
-- REMINDER PREFERENCES
-- ============================================================
CREATE TABLE IF NOT EXISTS reminder_preferences (
    id SERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL UNIQUE,
    custom_audio_message TEXT,
    custom_text_message TEXT,
    reminder_voice_enabled INTEGER DEFAULT 1,
    reminder_sms_enabled INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- ============================================================
-- MEDICATION ADHERENCE
-- ============================================================
CREATE TABLE IF NOT EXISTS medication_adherence (
    id SERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL,
    medication_id INTEGER NOT NULL,
    scheduled_time TEXT NOT NULL,
    taken_at TEXT,
    status TEXT DEFAULT 'pending',
    reminder_sent INTEGER DEFAULT 0,
    notes TEXT
);

-- ============================================================
-- APPOINTMENT ALERTS
-- ============================================================
CREATE TABLE IF NOT EXISTS appointment_alerts (
    id SERIAL PRIMARY KEY,
    patient_id TEXT NOT NULL,
    treatment_id INTEGER NOT NULL,
    appointment_date TEXT NOT NULL,
    alert_dismissed INTEGER DEFAULT 0,
    dismissed_by TEXT,
    dismissed_at TEXT,
    is_active INTEGER DEFAULT 1
);

-- ============================================================
-- SEED: VILLAGES
-- ============================================================
INSERT INTO villages (name, latitude, longitude) VALUES
    ('Siaya Town', -0.0614, 34.2880),
    ('Bondo', -0.0980, 34.2730),
    ('Kisumu', -0.1035, 34.7550),
    ('Rangala', 0.0720, 34.1580),
    ('Ugunja', 0.1650, 34.1200)
ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- SEED: HOSPITALS
-- ============================================================
INSERT INTO hospitals (name, village, latitude, longitude, level, phone, address, opening_hours) VALUES
    ('Siaya County Referral Hospital', 'Siaya Town', -0.0614, 34.2880, 5, '057-123456', 'Siaya Town, along Kisumu Road', '24/7'),
    ('Bondo Sub-County Hospital', 'Bondo', -0.0980, 34.2730, 4, '057-345678', 'Bondo Town, near Police Station', '24/7'),
    ('Jaramogi Oginga Odinga Hospital', 'Kisumu', -0.1035, 34.7550, 5, '057-456789', 'Kisumu City, along Jomo Kenyatta Highway', '24/7'),
    ('Rangala Health Centre', 'Rangala', 0.0720, 34.1580, 3, '057-567890', 'Rangala Market, Siaya County', '8am-5pm'),
    ('Ugunja Sub-County Hospital', 'Ugunja', 0.1650, 34.1200, 4, '057-678901', 'Ugunja Town', '24/7')
ON CONFLICT DO NOTHING;

-- ============================================================
-- SEED: HOSPITAL DISTANCES
-- ============================================================
INSERT INTO hospital_distances (village_name, hospital_name, distance_km, travel_time_minutes, directions) VALUES
    ('Siaya Town', 'Siaya County Referral Hospital', 2.0, 5, 'Head towards the main road. The hospital is 2km ahead on your left.'),
    ('Bondo', 'Bondo Sub-County Hospital', 1.5, 4, 'Walk towards the town center. Hospital is near the police station.'),
    ('Kisumu', 'Jaramogi Oginga Odinga Hospital', 3.0, 8, 'Head towards the city center. Hospital is along Jomo Kenyatta Highway.'),
    ('Rangala', 'Rangala Health Centre', 1.0, 3, 'Walk towards the market. Health centre is on the main road.'),
    ('Ugunja', 'Ugunja Sub-County Hospital', 2.5, 6, 'Head towards Ugunja Town center. Hospital is near the bus stage.')
ON CONFLICT DO NOTHING;