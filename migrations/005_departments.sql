-- 005_departments.sql
-- Departments (each is its own login), photos, services, triage rules.
-- NO individual doctor accounts. Doctors work through the department account.

CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    hospital_id INTEGER NOT NULL REFERENCES hospitals(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    head_doctor TEXT,
    secretary_name TEXT,
    phone TEXT,
    email TEXT,
    consultation_fee TEXT,
    operating_hours TEXT DEFAULT '24/7',
    username TEXT UNIQUE,
    password_hash TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_departments_hospital ON departments(hospital_id);
CREATE INDEX IF NOT EXISTS idx_departments_username ON departments(username);

CREATE TABLE IF NOT EXISTS department_photos (
    id SERIAL PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    caption TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_department_photos_dept ON department_photos(department_id);

CREATE TABLE IF NOT EXISTS department_services (
    id SERIAL PRIMARY KEY,
    department_id INTEGER NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_department_services_dept ON department_services(department_id);

CREATE TABLE IF NOT EXISTS triage_rules (
    id SERIAL PRIMARY KEY,
    keywords TEXT NOT NULL,
    department_name TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    is_emergency INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

INSERT INTO triage_rules (keywords, department_name, priority, is_emergency, created_at) VALUES
('bleeding,severe bleeding,hemorrhage,damu', 'Emergency', 100, 1, NOW()::text),
('chest pain,heart attack,crushing chest', 'Cardiology', 90, 1, NOW()::text),
('difficulty breathing,shortness of breath,cannot breathe,kupumua', 'Emergency', 90, 1, NOW()::text),
('unconscious,fainted,passed out,kuzirai', 'Emergency', 95, 1, NOW()::text),
('severe pain,unbearable,excruciating,maumivu makali', 'Emergency', 85, 1, NOW()::text),
('poisoning,overdose,swallowed', 'Emergency', 95, 1, NOW()::text),
('seizure,convulsion,fit', 'Emergency', 95, 1, NOW()::text),
('severe burn,burned', 'Emergency', 90, 1, NOW()::text),
('headache,migraine,kichwa', 'General Medicine', 40, 0, NOW()::text),
('fever,chills,hot body,homa', 'General Medicine', 45, 0, NOW()::text),
('malaria,mosquito', 'General Medicine', 50, 0, NOW()::text),
('typhoid', 'General Medicine', 50, 0, NOW()::text),
('cough,cold,flu,sore throat,kikohozi', 'General Medicine', 35, 0, NOW()::text),
('vomiting,nausea,tapika,kichefuchefu', 'General Medicine', 40, 0, NOW()::text),
('diarrhea,loose stool,kuhara', 'General Medicine', 40, 0, NOW()::text),
('stomach pain,abdominal pain,tumbo', 'General Medicine', 40, 0, NOW()::text),
('fatigue,tired,weak,uchovu', 'General Medicine', 30, 0, NOW()::text),
('child,baby,infant,mtoto', 'Pediatrics', 55, 0, NOW()::text),
('pregnant,pregnancy,labour,labor,mjamzito', 'Maternity', 55, 0, NOW()::text),
('birth,delivery,contractions', 'Maternity', 60, 0, NOW()::text),
('rash,skin,itching,uvimbe,mzio', 'Dermatology', 45, 0, NOW()::text),
('sores,blisters,skin infection', 'Dermatology', 45, 0, NOW()::text),
('tooth,teeth,dental,gum,meno', 'Dentistry', 50, 0, NOW()::text),
('eye,vision,blurred,eye pain,macho', 'Ophthalmology', 50, 0, NOW()::text),
('ear,hearing,nose,sinus,sore ear', 'ENT', 50, 0, NOW()::text),
('bone,fracture,joint,sprain,back pain', 'Orthopedics', 45, 0, NOW()::text),
('depression,anxiety,mental,stress,suicidal', 'Psychiatry', 55, 0, NOW()::text),
('hiv,arv,antiretroviral,art', 'HIV Clinic', 50, 0, NOW()::text),
('tuberculosis,tb,persistent cough,night sweats', 'TB Clinic', 55, 0, NOW()::text),
('cancer,tumor,lump,chemo,oncology', 'Oncology', 60, 0, NOW()::text);

-- NOTE: No default departments are seeded.
-- Departments are created by the Director via the dashboard only.
