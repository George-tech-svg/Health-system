# AFYAHIV CARE

## AI-Powered Multilingual Medication Adherence and Health Monitoring System for HIV Patients

---

## Project Overview

AFYAHIV CARE is a comprehensive digital health system designed to improve antiretroviral therapy (ART) adherence and strengthen symptom monitoring for people living with HIV. The system addresses practical barriers that affect continuity of care in low-resource settings, including low literacy levels, language barriers, limited smartphone access, and weak follow-up systems.

The solution combines multilingual SMS reminders, simulated voice interaction, symptom intake, rule-based risk analysis, and a provider dashboard for monitoring adherence and emergency alerts. The system uses a simulation methodology to model communication flows, symptom reporting, and triage logic under representative patient scenarios.

---

## Key Features

### Patient Features
- Multilingual SMS reporting (English and Kiswahili)
- Voice call reporting simulation for low-literacy users
- AI-powered emergency detection and risk classification
- Medication adherence tracking with daily logging
- Location-based hospital locator (GIS simulation)
- Two-way messaging with healthcare providers
- Account settings with language preference

### Doctor Features
- Patient registration and management
- Real-time emergency alerts
- Patient message history and response
- Adherence analytics dashboard
- Patient anonymization for privacy
- Location-based patient insights
- Audit logging for security

### Security Features
- Session timeout (15 minutes of inactivity)
- bcrypt password hashing
- Login attempt lockout (5 failed attempts)
- Patient anonymization (IDs only, no names visible)
- Audit logging for all user actions

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Backend Framework | Flask (Python) |
| Database | SQLite |
| Frontend | HTML5, CSS3, JavaScript |
| Authentication | bcrypt password hashing |
| Translation | Custom translation engine |
| GIS Simulation | Pre-calculated distance tables |
| AI Engine | Rule-based keyword detection |

---

## System Architecture
┌─────────────────────────────────────────────────────────────┐
│ PRESENTATION LAYER │
│ Patient Dashboard | Doctor Dashboard │
├─────────────────────────────────────────────────────────────┤
│ APPLICATION LAYER │
│ Patient Management | Message Processor | Alert Manager │
├─────────────────────────────────────────────────────────────┤
│ AI ENGINE │
│ Text Analysis | Risk Assessment | Response Generation │
├─────────────────────────────────────────────────────────────┤
│ DATA LAYER │
│ SQLite Database | Patient Records | Message Logs │
├─────────────────────────────────────────────────────────────┤
│ COMMUNICATION LAYER │
│ SMS Simulation | Voice Simulation │
└─────────────────────────────────────────────────────────────┘

text

---

## Installation Guide

### Prerequisites

- Python 3.8 or higher
- pip package manager

### Step 1: Clone the Repository

```bash
git clone https://github.com/George-tech-svg/AFYAHIV-CARE.git
cd AFYAHIV-CARE
Step 2: Install Dependencies
bash
pip install -r requirements.txt
Dependencies include:

Flask 2.3.0

bcrypt 4.0.1

requests 2.31.0

gunicorn 21.2.0

Step 3: Run the Application
bash
python app.py
Step 4: Access the System
Open your browser and navigate to:

text
http://localhost:5000
Login Credentials
Doctor Access
Field	Value
Username	dr.mwangi
Password	doctor123
Patient Access
Patients must be registered by a doctor. After registration, patients receive:

Patient ID (e.g., HIV8A3B2)

Registered phone number

Database Structure
The system uses SQLite with the following tables:

Table	Purpose
patients	Patient personal and medical information
messages	All SMS, voice, and system messages
providers	Doctor login credentials and profiles
adherence	Daily medication dose tracking
villages	Geographic locations for hospital locator
hospitals	Healthcare facility information
hospital_distances	Pre-calculated distances for GIS simulation
failed_logins	Security tracking for login attempts
audit_logs	Comprehensive audit trail of user actions
Project Files
File	Description
app.py	Main Flask application with all routes
database.py	Database models and operations
ai_engine.py	Rule-based AI for symptom analysis
sms_handler.py	SMS simulation and processing
voice_simulator.py	Voice call reporting simulation
translator.py	Language translation service
requirements.txt	Python dependencies
Templates Directory
File	Description
login.html	User authentication page
patient_dashboard.html	Patient interface
doctor_dashboard.html	Provider interface
register.html	Patient self-registration
How It Works
Patient Flow
Patient logs in using Patient ID and phone number

Patient selects language preference (English/Kiswahili)

Patient can send health reports via SMS or voice simulation

AI analyzes the message for emergency keywords

System classifies risk level (High/Medium/Low)

Response sent to patient automatically

Doctor dashboard updated with alerts if high risk

Doctor Flow
Doctor logs in with username and password

Doctor registers new patients with required information

Doctor reviews patient reports and emergency alerts

Doctor can send messages to patients

Analytics dashboard shows adherence trends

AI Risk Classification
Risk Level	Detection Criteria	System Response
High	Emergency keywords (bleeding, severe pain, difficulty breathing)	Hospital referral, doctor alert
Medium	Symptom keywords (fever, headache, vomiting)	Monitoring advice
Low	Positive keywords (better, good, well)	Encouragement message
Language Support
The system supports two languages:

Language	Code	Status
English	EN	Full support
Kiswahili	SW	Full support
Users can switch languages from within the dashboard. The translation covers all interface elements, buttons, labels, and system messages.

Security Features
Feature	Implementation
Session Management	15-minute timeout with automatic logout
Password Storage	bcrypt hashing (not plain text or simple hash)
Login Protection	Account lockout after 5 failed attempts
Patient Privacy	Names hidden from doctor dashboard; only Patient IDs visible
Audit Trail	All logins, logouts, and patient views recorded
Access Control	Role-based (Patient and Doctor)
Deployment
The system is deployed on Render.com and accessible at:

text
https://afyahiv-care.onrender.com
Deployment Steps
Push code to GitHub repository

Connect repository to Render.com

Set build command: pip install -r requirements.txt

Set start command: gunicorn app:app

Deploy automatically on push

Limitations (Capstone Simulation)
Aspect	Simulation Approach
SMS	Simulated via console output; not connected to live telecom
Voice	Text input simulation; not connected to speech-to-text API
GIS	Pre-calculated distances; not connected to live GPS or maps
AI	Rule-based keyword detection; not a trained machine learning model
Database	SQLite (file-based); not a production scale database
Future Enhancements
Integration with live SMS gateway (Africa's Talking)

Real speech-to-text for voice reports

Live GPS integration for hospital locator

Machine learning model for improved risk detection

Mobile application for patients

Multi-factor authentication

End-to-end encryption for messages

Troubleshooting
Common Issues and Solutions
Issue	Solution
Module not found	Run pip install -r requirements.txt
Database error	Delete afyahiv_care.db and restart
Port already in use	Change port in app.py from 5000 to 5001
Login fails	Ensure Patient ID and phone number match registered values
Session expired	Login again (auto-logout after 15 minutes)
