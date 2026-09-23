# app.py - FastAfya (Hospital-based model, PostgreSQL)
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from database import Database
from ai_engine import AIEngine
from sms_handler import SMSHandler
from voice_simulator import VoiceSimulator
from translator import translator
from datetime import datetime, timedelta
from functools import wraps
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from math import radians, sin, cos, sqrt, atan2
import uuid
import re
import os
import json
import atexit


import cloudinary
import cloudinary.uploader

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)


def upload_to_cloudinary(file_obj, folder, resource_type="image"):
    """Upload a Flask FileStorage to Cloudinary, return the secure URL."""
    try:
        result = cloudinary.uploader.upload(
            file_obj,
            folder="fastafya/" + folder,
            resource_type=resource_type,
        )
        return result.get("secure_url")
    except Exception as e:
        print("Cloudinary upload error: " + str(e))
        return None

app = Flask(__name__)
app.secret_key = "fastafya-secret-key-2024"
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=60)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024

db = Database()
ai_engine = AIEngine()
sms_handler = SMSHandler(ai_engine, db)
voice_simulator = VoiceSimulator(ai_engine, sms_handler, db)

scheduler = BackgroundScheduler()


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c


def format_phone(phone):
    phone = re.sub(r'\D', '', str(phone))
    if phone.startswith('0'):
        phone = phone[1:]
    elif phone.startswith('254'):
        phone = phone[3:]
    return "+254" + phone


# ============ AUTH DECORATORS ============
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_type' not in session:
            return jsonify({"error": "Not logged in"}), 401
        return f(*args, **kwargs)
    return decorated_function


def hospital_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_type' not in session or session.get('user_type') != 'hospital':
            return jsonify({"error": "Hospital access required"}), 401
        return f(*args, **kwargs)
    return decorated_function


def doctor_login_required(f):
    """Allows hospital accounts AND Director (super_admin) sessions."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        ut = session.get('user_type')
        if ut not in ('hospital', 'super_admin'):
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


def patient_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_type' not in session or session.get('user_type') != 'patient':
            return jsonify({"error": "Patient access required"}), 401
        return f(*args, **kwargs)
    return decorated_function


# ============ BACKGROUND JOBS ============
escalated_emergencies = set()


def check_and_send_medication_reminders():
    try:
        patients = db.get_all_patients()
    except Exception:
        return
    try:
        current_time = datetime.now()
        current_hour = current_time.hour
        current_minute = current_time.minute
        for patient in patients:
            patient_id = patient[1]
            patient_name = patient[2]
            phone_number = patient[3]
            active_meds = db.get_active_medications(patient_id)
            for med in active_meds:
                schedule_times = med.get('schedule_times', [])
                for scheduled_time in schedule_times:
                    if ':' not in scheduled_time:
                        continue
                    sch_hour = int(scheduled_time.split(':')[0])
                    sch_minute = int(scheduled_time.split(':')[1])
                    time_diff = (sch_hour - current_hour) * 60 + (sch_minute - current_minute)
                    if 8 <= time_diff <= 12:
                        pref = db.get_reminder_preference(patient_id)
                        if pref and pref.get('custom_audio_message'):
                            reminder_message = pref['custom_audio_message']
                        else:
                            reminder_message = "Reminder: Take your " + med['medication_name'] + " " + med['dosage_amount'] + " " + med['dosage_unit'] + " at " + scheduled_time + ". You have 10 minutes."
                        print("\n🔔 VOICE REMINDER for " + patient_name + " (" + phone_number + "):")
                        print("   Message: " + reminder_message)
                        db.create_adherence_record(patient_id, med['id'], datetime.now().date().isoformat() + " " + scheduled_time + ":00")
    except Exception as e:
        print("Error in medication reminders: " + str(e))


def check_appointment_reminders():
    try:
        patients = db.get_all_patients()
        today = datetime.now().date()
        for patient in patients:
            patient_id = patient[1]
            patient_name = patient[2]
            alerts = db.get_active_appointment_alerts(patient_id)
            for alert in alerts:
                appointment_date = datetime.fromisoformat(alert['appointment_date']).date()
                days_until = (appointment_date - today).days
                if days_until == 1:
                    message = "🔴 URGENT: Your hospital appointment is TOMORROW! Reason: " + str(alert['reason'])
                    print("\n🔴 APPOINTMENT REMINDER for " + patient_name + ": " + message)
                    sms_handler.send_sms(patient[3], message, 'English')
                elif days_until == 3:
                    message = "📅 REMINDER: Your hospital appointment is in 3 days on " + str(appointment_date) + "."
                    print("\n📅 APPOINTMENT REMINDER for " + patient_name + ": " + message)
                    sms_handler.send_sms(patient[3], message, 'English')
    except Exception as e:
        print("Error in appointment reminders: " + str(e))


def check_unresponded_emergencies():
    global escalated_emergencies
    try:
        rows = db.get_unresponded_emergencies_older_than(minutes=5)
    except Exception:
        return
    try:
        for emergency in rows:
            emergency_id = emergency[0]
            patient_id = emergency[1]
            patient_name = emergency[2]
            if emergency_id not in escalated_emergencies:
                db.mark_emergency_escalated(emergency_id)
                escalated_emergencies.add(emergency_id)
                contacts = db.get_emergency_contacts(patient_id)
                db.add_audit_log('system', 'auto_escalation', 'emergency_escalated',
                                 "Emergency #" + str(emergency_id) + " for " + patient_name + " escalated")
                print("\n🚨 AUTO-ESCALATION: Emergency #" + str(emergency_id) + " for " + patient_name)
                for contact in contacts:
                    print("   📱 Notified: " + contact['name'] + " (" + contact['phone_number'] + ")")
    except Exception as e:
        print("Error in emergency escalation: " + str(e))


scheduler.add_job(func=check_unresponded_emergencies, trigger=CronTrigger(minute='*'), id='emergency_escalation', replace_existing=True)
scheduler.add_job(func=check_and_send_medication_reminders, trigger=CronTrigger(minute='*'), id='medication_reminders', replace_existing=True)
scheduler.add_job(func=check_appointment_reminders, trigger=CronTrigger(hour=8, minute=0), id='appointment_reminders', replace_existing=True)


def schedule_all_reminders():
    patients = db.get_all_patients()
    scheduled_count = 0
    for patient in patients:
        medication_time = patient[6]
        if not medication_time:
            continue
        try:
            if 'T' in medication_time:
                medication_time = '20:00'
            hour = int(medication_time.split(':')[0])
            minute = int(medication_time.split(':')[1])
            scheduled_count += 1
        except Exception:
            pass
    print("✅ Scheduled reminders for " + str(scheduled_count) + " patients")


# ============ BASIC ROUTES ============
@app.route('/set_language', methods=['POST'])
@login_required
def set_language():
    language = request.json.get('language', 'English')
    if session.get('user_type') == 'patient':
        session['patient_language'] = language
    else:
        session['doctor_language'] = language
    return jsonify({"status": "success", "language": language})


@app.route('/api/translate', methods=['POST'])
def api_translate():
    data = request.json
    text = data.get('text', '')
    language = data.get('language', 'English')
    if not text:
        return jsonify({"translated": ""})
    return jsonify({"translated": translator.translate_text(text, language)})


@app.route('/')
def index():
    return render_template('login.html')


# ============ PATIENT LOGIN ============
@app.route('/patient/login', methods=['POST'])
def patient_login():
    patient_id = request.form.get('patient_id')
    password = request.form.get('password')
    if not patient_id or not password:
        return render_template('login.html', error="Please enter both Patient ID and Password")
    failed_count = db.get_failed_attempts(username=patient_id)
    if failed_count >= 5:
        return render_template('login.html', error="Account locked due to too many failed attempts.")
    patient = db.authenticate_patient(patient_id, password)
    if patient:
        db.clear_failed_attempts(username=patient_id)
        session.clear()
        session['user_type'] = 'patient'
        session['patient_id'] = patient[1]
        session['patient_phone'] = patient[3]
        session['patient_location'] = patient[5]
        session['patient_name'] = patient[2]
        session['patient_hospital_id'] = patient[10] if len(patient) > 10 else None
        session['patient_language'] = 'English'
        session.permanent = True
        db.add_audit_log('patient', patient_id, 'login', 'Patient ' + patient_id + ' logged in')
        return redirect(url_for('patient_dashboard'))
    db.record_failed_login(username=patient_id)
    remaining = 4 - failed_count
    return render_template('login.html', error="Invalid credentials. " + str(remaining) + " attempts remaining.")


# ============ PATIENT REGISTER ============
@app.route('/patient/register', methods=['GET', 'POST'])
def patient_register():
    if request.method == 'GET':
        hospitals = db.get_all_hospitals()
        return render_template('patient_register.html', hospitals=hospitals)

    full_name = request.form.get('full_name', '').strip()
    phone = format_phone(request.form.get('phone_number', ''))
    password = request.form.get('password', '')
    confirm = request.form.get('confirm_password', '')
    location = request.form.get('location', '').strip()
    hospital_id = request.form.get('hospital_id')
    arv_regimen = request.form.get('arv_regimen', '') or 'General'
    medication_time = request.form.get('medication_time', '20:00')

    if not full_name or not phone or not password or not location or not hospital_id:
        hospitals = db.get_all_hospitals()
        return render_template('patient_register.html', hospitals=hospitals, error="Please fill all required fields.")

    if len(password) < 4:
        hospitals = db.get_all_hospitals()
        return render_template('patient_register.html', hospitals=hospitals, error="Password must be at least 4 characters.")

    if password != confirm:
        hospitals = db.get_all_hospitals()
        return render_template('patient_register.html', hospitals=hospitals, error="Passwords do not match.")

    patient_id = "PAT" + str(uuid.uuid4())[:5].upper()

    try:
        db.register_patient(
            patient_id, full_name, phone, password, location, arv_regimen, medication_time,
            hospital_id=int(hospital_id), registration_source='self'
        )
        db.add_audit_log('patient', patient_id, 'self_register', 'Patient self-registered')
        return render_template('patient_register.html', success=True, patient_id=patient_id)
    except Exception as e:
        hospitals = db.get_all_hospitals()
        return render_template('patient_register.html', hospitals=hospitals, error="Registration failed: " + str(e))


# ============ HOSPITAL LOGIN ============
@app.route('/hospital/login', methods=['POST'])
def hospital_login():
    username = request.form.get('username')
    password = request.form.get('password')
    if not username or not password:
        return render_template('login.html', error="Please enter both Username and Password")
    failed_count = db.get_failed_attempts(username=username)
    if failed_count >= 5:
        return render_template('login.html', error="Account locked due to too many failed attempts.")
    hospital = db.authenticate_hospital(username, password)
    if hospital:
        db.clear_failed_attempts(username=username)
        session.clear()
        session['user_type'] = 'hospital'
        session['hospital_id'] = hospital[0]
        session['hospital_name'] = hospital[1]
        # Backward-compat aliases used by existing templates
        session['doctor_id'] = hospital[0]
        session['doctor_name'] = hospital[1]
        session['hospital'] = hospital[1]
        session['doctor_language'] = 'English'
        session.permanent = True
        db.add_audit_log('hospital', username, 'login', 'Hospital ' + hospital[1] + ' logged in')
        return redirect(url_for('doctor_dashboard'))
    db.record_failed_login(username=username)
    remaining = 4 - failed_count
    return render_template('login.html', error="Invalid credentials. " + str(remaining) + " attempts remaining.")


# ============ HOSPITAL REGISTER ============
@app.route('/hospital/register', methods=['GET', 'POST'])
def hospital_register():
    if request.method == 'GET':
        return render_template('hospital_register.html')

    name = request.form.get('name', '').strip()
    county = request.form.get('county', '').strip()
    sub_county = request.form.get('sub_county', '').strip()
    village = request.form.get('village', '').strip()
    address = request.form.get('address', '').strip()
    phone = request.form.get('phone', '').strip()
    contact_person = request.form.get('contact_person', '').strip()
    contact_email = request.form.get('contact_email', '').strip()
    username = request.form.get('username', '').strip().lower()
    password = request.form.get('password', '')
    confirm = request.form.get('confirm_password', '')

    if not name or not county or not sub_county or not village or not username:
        return render_template('hospital_register.html', error="Please fill all required fields.")

    if len(password) < 6:
        return render_template('hospital_register.html', error="Password must be at least 6 characters.")

    if password != confirm:
        return render_template('hospital_register.html', error="Passwords do not match.")

    if ' ' in username:
        return render_template('hospital_register.html', error="Username cannot contain spaces.")

    existing = db.get_hospital_by_username(username)
    if existing:
        return render_template('hospital_register.html', error="That username is already taken.")

    try:
        # 1. Create hospital
        hospital_id = db.register_hospital(
            name=name, village=village, county=county, sub_county=sub_county,
            address=address, phone=phone, contact_person=contact_person,
            contact_email=contact_email, username=username, password=password,
        )
        # 2. Create Director (super_admin) linked to this hospital
        director_username = username
        existing_sa = db.get_super_admin_by_username(director_username)
        if not existing_sa:
            db.create_super_admin(
                username=director_username,
                password=password,
                full_name=contact_person or ("Director of " + name),
                hospital_id=hospital_id,
                email=contact_email,
                phone=phone,
            )
        db.add_audit_log('hospital', username, 'register',
                         'Hospital ' + name + ' + Director ' + director_username + ' registered')
        return render_template('hospital_register.html', success=True, username=director_username)
    except Exception as e:
        return render_template('hospital_register.html', error="Registration failed: " + str(e))


# ============ PATIENT DASHBOARD ============
@app.route('/patient/dashboard')
@patient_login_required
def patient_dashboard():
    patient_id = session['patient_id']
    patient = db.get_patient_by_id(patient_id)
    messages = db.get_patient_messages_with_replies(patient_id)
    taken, total = db.get_adherence_stats(patient_id)
    adherence_percent = (taken / total * 100) if total > 0 else 85
    villages = db.get_all_villages()
    current_language = session.get('patient_language', 'English')
    emergency_contacts = db.get_emergency_contacts(patient_id)
    treatments = db.get_patient_treatments(patient_id)
    active_medications = db.get_active_medications(patient_id)
    today_adherence = db.get_today_adherence(patient_id)
    appointment_alerts = db.get_active_appointment_alerts(patient_id)
    reminder_pref = db.get_reminder_preference(patient_id)

    hospital_name = "Unknown"
    if patient and len(patient) > 10 and patient[10]:
        h = db.get_hospital_by_id(patient[10])
        if h:
            hospital_name = h[1]

    return render_template('patient_dashboard.html',
                         patient_id=patient_id,
                         patient_location=patient[5] if patient else 'Unknown',
                         patient_arv=patient[6] if patient else 'TLD',
                         patient_time=patient[7] if patient else '20:00',
                         hospital_name=hospital_name,
                         messages=messages[:50],
                         adherence_percent=adherence_percent,
                         unread_count=0,
                         villages=villages,
                         session=session,
                         language=current_language,
                         emergency_contacts=emergency_contacts,
                         treatments=treatments,
                         active_medications=active_medications,
                         today_adherence=today_adherence,
                         appointment_alerts=appointment_alerts,
                         reminder_pref=reminder_pref)


@app.route('/patient/send_report', methods=['POST'])
@patient_login_required
def patient_send_report():
    report_text = request.form.get('report_text')
    patient_id = session['patient_id']
    patient = db.get_patient_by_id(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    analysis = ai_engine.analyze_text(report_text)
    db.save_message_with_parent_and_reply(
        patient[1], 'outgoing', 'sms', report_text, 'English',
        analysis['risk_level'], ','.join(analysis['symptoms']), analysis['response'],
        None, None, None
    )
    return jsonify({"status": "processed", "response": analysis['response'], "risk_level": analysis['risk_level']})


@app.route('/patient/voice_with_audio', methods=['POST'])
@patient_login_required
def patient_voice_with_audio():
    try:
        report_text = request.form.get('report_text', '')
        patient_id = session.get('patient_id')
        patient = db.get_patient_by_id(patient_id)
        if not patient:
            return jsonify({"error": "Patient not found"}), 404
        analysis = ai_engine.analyze_text(report_text)
        audio_filename = None
        if 'audio' in request.files:
            audio_file = request.files['audio']
            if audio_file and audio_file.filename != '':
                audio_filename = upload_to_cloudinary(
                    audio_file, "voice/patients/" + patient[1], "video"
                )
        db.save_message_with_parent_and_reply(
            patient[1], 'outgoing', 'voice', report_text, 'English',
            analysis['risk_level'], ','.join(analysis['symptoms']), analysis['response'],
            None, audio_filename, None
        )
        return jsonify({"status": "processed", "response": analysis['response'],
                        "risk_level": analysis['risk_level'], "audio_file": audio_filename})
    except Exception as e:
        return jsonify({"error": str(e), "status": "error"}), 500


@app.route('/patient/video_upload', methods=['POST'])
@patient_login_required
def patient_video_upload():
    try:
        patient_id = session.get('patient_id')
        patient = db.get_patient_by_id(patient_id)
        if not patient:
            return jsonify({"error": "Patient not found"}), 404
        video_filename = None
        if 'video' in request.files:
            video_file = request.files['video']
            if video_file and video_file.filename != '':
                video_filename = upload_to_cloudinary(
                    video_file, "video/patients/" + patient[1], "video"
                )
        description = request.form.get('description', 'Video message')
        db.save_message_with_parent_and_reply(
            patient[1], 'outgoing', 'video', description, 'English',
            'low', '', 'Video message received', None, None, None
        )
        return jsonify({"status": "processed", "response": "Video message sent to hospital",
                        "video_file": video_filename})
    except Exception as e:
        return jsonify({"error": str(e), "status": "error"}), 500


@app.route('/patient/messages')
@patient_login_required
def patient_messages():
    patient_id = session['patient_id']
    messages = db.get_patient_messages_with_replies(patient_id)
    result = []
    for msg in messages:
        result.append({
            'id': msg[0], 'direction': msg[2], 'type': msg[3], 'content': msg[4],
            'risk_level': msg[6], 'timestamp': msg[9],
            'audio_file': msg[12] if len(msg) > 12 else None,
            'video_file': msg[13] if len(msg) > 13 else None,
            'reply_to_id': msg[15] if len(msg) > 15 else None,
            'is_delivered': msg[17] if len(msg) > 17 else 0,
            'is_read_by_receiver': msg[16] if len(msg) > 16 else 0,
        })
    return jsonify(result)


@app.route('/patient/mark_delivered/<int:message_id>', methods=['POST'])
@patient_login_required
def patient_mark_delivered(message_id):
    db.mark_message_delivered(message_id)
    return jsonify({"status": "success"})


@app.route('/patient/mark_read/<int:message_id>', methods=['POST'])
@patient_login_required
def patient_mark_read(message_id):
    db.mark_message_read(message_id)
    return jsonify({"status": "success"})


@app.route('/patient/messages_with_status')
@patient_login_required
def patient_messages_with_status():
    patient_id = session['patient_id']
    messages, pinned = db.get_messages_with_status(patient_id)
    msg_list = []
    for m in messages:
        msg_list.append({
            'id': m[0], 'direction': m[1], 'type': m[2], 'content': m[3], 'timestamp': m[4],
            'is_delivered': m[5], 'is_read_by_receiver': m[6], 'is_pinned': m[7],
            'audio_file': m[8], 'video_file': m[9], 'reply_to_id': m[10],
            'reply_to_content': m[11],
        })
    pinned_list = [{'id': p[0], 'content': p[1], 'timestamp': p[2]} for p in pinned]
    return jsonify({"messages": msg_list, "pinned_messages": pinned_list})


@app.route('/patient/delete_message/<int:message_id>', methods=['DELETE'])
@patient_login_required
def patient_delete_message(message_id):
    db.delete_message(message_id, session['patient_id'])
    return jsonify({"status": "success"})


@app.route('/patient/pin_message', methods=['POST'])
@patient_login_required
def patient_pin_message():
    db.pin_message(request.json.get('message_id'), session['patient_id'])
    return jsonify({"status": "success"})


@app.route('/patient/unpin_message', methods=['POST'])
@patient_login_required
def patient_unpin_message():
    db.unpin_message(request.json.get('message_id'), session['patient_id'])
    return jsonify({"status": "success"})


@app.route('/patient/save_reminder_preference', methods=['POST'])
@patient_login_required
def save_reminder_preference():
    data = request.json
    db.save_reminder_preference(
        session['patient_id'],
        data.get('custom_audio_message', ''),
        data.get('custom_text_message', ''),
        data.get('reminder_voice_enabled', 1),
        data.get('reminder_sms_enabled', 0),
    )
    return jsonify({"status": "success"})


@app.route('/patient/mark_medication_taken', methods=['POST'])
@patient_login_required
def mark_medication_taken():
    data = request.json
    db.log_medication_taken(session['patient_id'], data.get('medication_id'), data.get('scheduled_time'))
    db.add_adherence_record(session['patient_id'], 1)
    return jsonify({"status": "success"})


@app.route('/patient/update_location', methods=['POST'])
@patient_login_required
def patient_update_location():
    new_location = request.form.get('location')
    db.update_patient_location(session['patient_id'], new_location)
    session['patient_location'] = new_location
    return jsonify({'status': 'success', 'message': 'Location updated to ' + new_location})


@app.route('/patient/emergency_contacts')
@patient_login_required
def patient_emergency_contacts():
    return jsonify(db.get_emergency_contacts(session['patient_id']))


@app.route('/patient/add_emergency_contact', methods=['POST'])
@patient_login_required
def patient_add_emergency_contact():
    data = request.json
    if not data.get('name') or not data.get('phone_number'):
        return jsonify({"error": "Name and phone required"}), 400
    db.add_emergency_contact(
        session['patient_id'], data['name'], data['phone_number'],
        data.get('relationship', ''), data.get('is_primary', 0),
        data.get('shared_with_doctor', 0),
    )
    return jsonify({"status": "success"})


@app.route('/patient/delete_emergency_contact/<int:contact_id>', methods=['DELETE'])
@patient_login_required
def patient_delete_emergency_contact(contact_id):
    db.delete_emergency_contact(contact_id, session['patient_id'])
    return jsonify({"status": "success"})


@app.route('/patient/toggle_share_contact', methods=['POST'])
@patient_login_required
def patient_toggle_share_contact():
    data = request.json
    db.toggle_share_contact(data['contact_id'], session['patient_id'], data.get('shared_with_doctor', 0))
    return jsonify({"status": "success"})


@app.route('/patient/send_emergency', methods=['POST'])
@patient_login_required
def patient_send_emergency():
    patient_id = session['patient_id']
    patient = db.get_patient_by_id(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    data = request.json or {}
    active = db.get_active_emergencies()
    for e in active:
        if e['patient_id'] == patient_id:
            return jsonify({"status": "error", "message": "You already have an active emergency."}), 400
    emergency_message = "🚨 EMERGENCY SOS: I need immediate medical help! 🚨"
    emergency_id = db.create_emergency(
        patient_id, patient[2], emergency_message,
        data.get('communication_preference', 'either'),
        data.get('location_lat'), data.get('location_lng'), data.get('location_address'),
    )
    db.save_emergency_message(emergency_id, 'patient', 'text', emergency_message, None)
    db.add_audit_log('patient', patient_id, 'emergency_sos', 'Patient sent emergency SOS')
    hospital = db.get_nearest_hospital(patient[5] if patient[5] else "Siaya Town")
    return jsonify({"status": "success", "message": "Emergency alert sent",
                    "emergency_id": emergency_id, "hospital": hospital})


@app.route('/patient/emergency_status')
@patient_login_required
def patient_emergency_status():
    patient_id = session['patient_id']
    for e in db.get_active_emergencies():
        if e['patient_id'] == patient_id:
            return jsonify({
                "has_active_emergency": True,
                "emergency_id": e['id'],
                "communication_preference": e['communication_preference'],
                "timestamp": e['timestamp'],
                "doctor_responded": e['doctor_response_timestamp'] is not None,
                "response_time_minutes": db.get_emergency_response_time(e['id']),
            })
    return jsonify({"has_active_emergency": False})


@app.route('/patient/emergency_messages/<int:emergency_id>')
@patient_login_required
def patient_emergency_messages(emergency_id):
    return jsonify(db.get_emergency_messages(emergency_id))


@app.route('/patient/emergency_history')
@patient_login_required
def patient_emergency_history():
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, emergency_message, communication_preference, status, timestamp, resolved_timestamp FROM emergencies WHERE patient_id = ? ORDER BY timestamp DESC",
        (session['patient_id'],)
    )
    rows = cursor.fetchall()
    conn.close()
    return jsonify([
        {'id': r[0], 'emergency_message': r[1], 'communication_preference': r[2],
         'status': r[3], 'timestamp': r[4], 'resolved_timestamp': r[5]}
        for r in rows
    ])


@app.route('/patient/send_emergency_reply', methods=['POST'])
@patient_login_required
def patient_send_emergency_reply():
    emergency_id = request.form.get('emergency_id')
    message_type = request.form.get('message_type', 'text')
    content = request.form.get('content', '')
    audio_file = None
    if message_type == 'audio' and 'audio' in request.files:
        audio = request.files['audio']
        if audio and audio.filename != '':
            audio_file = upload_to_cloudinary(
                audio, "emergency/patient/" + str(emergency_id), "video"
            )
            content = "Voice message from patient"
    db.save_emergency_message(emergency_id, 'patient', message_type, content, audio_file)
    return jsonify({"status": "success"})


@app.route('/patient/start_live_location', methods=['POST'])
@patient_login_required
def start_live_location():
    data = request.json
    db.save_emergency_location(
        data.get('emergency_id'), data.get('lat'), data.get('lng'),
        data.get('accuracy'), data.get('speed'), data.get('heading'),
    )
    return jsonify({"status": "success"})


@app.route('/patient/request_refill', methods=['POST'])
@patient_login_required
def patient_request_refill():
    patient_id = session['patient_id']
    patient = db.get_patient_by_id(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    data = request.json or {}
    request_id, days_left = db.create_refill_request(
        patient_id, patient[2],
        data.get('medication_name', patient[6]),
        data.get('dosage', 'As prescribed'),
        data.get('last_dose_date', ''),
        data.get('preferred_pickup_date', ''),
        data.get('preferred_pickup_time', ''),
    )
    db.add_audit_log('patient', patient_id, 'refill_request', 'Refill requested')
    return jsonify({"status": "success", "request_id": request_id, "days_left": days_left})


@app.route('/patient/refill_status')
@patient_login_required
def patient_refill_status():
    return jsonify(db.get_refill_requests_for_patient(session['patient_id'], request.args.get('status', 'all')))


@app.route('/patient/cancel_refill/<int:request_id>', methods=['POST'])
@patient_login_required
def patient_cancel_refill(request_id):
    db.cancel_refill_request(request_id, (request.json or {}).get('reason', ''))
    return jsonify({"status": "success"})


@app.route('/patient/find_hospital', methods=['POST'])
@patient_login_required
def patient_find_hospital():
    village = request.form.get('village')
    if village:
        db.update_patient_location(session['patient_id'], village)
        session['patient_location'] = village
    hospital = db.get_nearest_hospital(village)
    if hospital:
        return jsonify({'status': 'success', 'hospital': hospital})
    return jsonify({'status': 'error', 'message': 'No hospital found'})


@app.route('/patient/delete_account', methods=['POST'])
@patient_login_required
def patient_delete_account():
    return jsonify({"status": "not_implemented", "error": "Feature not yet available"})


# ============ HOSPITAL DASHBOARD ============
@app.route('/doctor/dashboard')
@doctor_login_required
def doctor_dashboard():
    hospital_id = session.get('hospital_id')
    patients = db.get_all_patients(hospital_id=hospital_id)
    unread_messages = db.get_unread_messages(hospital_id=hospital_id)
    emergency_alerts = db.get_emergency_alerts(hospital_id=hospital_id)
    all_messages = db.get_all_messages_for_doctor_with_replies(hospital_id=hospital_id)
    villages = db.get_all_villages()
    current_language = session.get('doctor_language', 'English')
    treatments = db.get_all_treatments(hospital_id=hospital_id)

    patient_data = []
    for patient in patients:
        taken, total = db.get_adherence_stats(patient[1])
        adherence = (taken / total * 100) if total > 0 else 85
        patient_data.append({
            'id': patient[1], 'name': patient[2], 'location': patient[4],
            'arv_regimen': patient[5], 'medication_time': patient[6],
            'adherence': adherence,
        })

    return render_template('doctor_dashboard.html',
                         patients=patient_data,
                         unread_messages=unread_messages,
                         emergency_alerts=emergency_alerts,
                         all_messages=all_messages,
                         villages=villages,
                         session=session,
                         language=current_language,
                         treatments=treatments)


@app.route('/doctor/send_message', methods=['POST'])
@doctor_login_required
def doctor_send_message():
    patient_id = request.form.get('patient_id')
    message = request.form.get('message')
    reply_to_id = request.form.get('reply_to_id', None)
    patient = db.get_patient_by_id(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    sms_handler.send_sms(patient[3], message, 'English')
    db.send_message_to_patient(patient_id, message, session.get('hospital_name', 'Hospital'), reply_to_id)
    return jsonify({"status": "success"})


@app.route('/doctor/send_voice_reply', methods=['POST'])
@doctor_login_required
def doctor_send_voice_reply():
    patient_id = request.form.get('patient_id')
    reply_text = request.form.get('reply_text', 'Voice message')
    reply_to_id = request.form.get('reply_to_id', None)
    patient = db.get_patient_by_id(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    audio_filename = None
    if 'audio' in request.files:
        audio_file = request.files['audio']
        if audio_file and audio_file.filename != '':
            audio_filename = upload_to_cloudinary(
                audio_file, "voice/doctors/" + patient[1], "video"
            )
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (patient_id, direction, type, content, language, risk_level, response_sent, timestamp, audio_file, reply_to_id, is_delivered) VALUES (?, 'incoming', 'voice', ?, 'English', 'none', ?, ?, ?, ?, 0)",
        (patient[1], reply_text, "Voice reply from " + session.get('hospital_name', 'Hospital'),
         datetime.now().isoformat(), audio_filename, reply_to_id)
    )
    conn.commit()
    conn.close()
    sms_handler.send_sms(patient[3], "Voice reply from hospital: " + reply_text, 'English')
    return jsonify({"status": "success", "audio_file": audio_filename})


@app.route('/doctor/send_video_reply', methods=['POST'])
@doctor_login_required
def doctor_send_video_reply():
    patient_id = request.form.get('patient_id')
    reply_text = request.form.get('reply_text', 'Video message')
    reply_to_id = request.form.get('reply_to_id', None)
    patient = db.get_patient_by_id(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    video_filename = None
    if 'video' in request.files:
        video_file = request.files['video']
        if video_file and video_file.filename != '':
            video_filename = upload_to_cloudinary(
                video_file, "video/doctors/" + patient[1], "video"
            )
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO messages (patient_id, direction, type, content, language, risk_level, response_sent, timestamp, video_file, reply_to_id, is_delivered) VALUES (?, 'incoming', 'video', ?, 'English', 'none', ?, ?, ?, ?, 0)",
        (patient[1], reply_text, "Video reply from " + session.get('hospital_name', 'Hospital'),
         datetime.now().isoformat(), video_filename, reply_to_id)
    )
    conn.commit()
    conn.close()
    sms_handler.send_sms(patient[3], "Hospital sent you a video message. Check your dashboard.", 'English')
    return jsonify({"status": "success", "video_file": video_filename})


@app.route('/doctor/chat_list')
@doctor_login_required
def doctor_chat_list():
    return jsonify(db.get_chat_list_for_doctor(hospital_id=session.get('hospital_id')))


@app.route('/doctor/chat/<patient_id>')
@doctor_login_required
def doctor_chat(patient_id):
    messages = db.get_conversation(patient_id)
    patient = db.get_patient_by_id(patient_id)
    if not patient:
        return jsonify({"error": "Patient not found"}), 404
    message_list = []
    for msg in messages:
        display_direction = 'incoming' if msg['direction'] == 'outgoing' else 'outgoing'
        message_list.append({
            'id': msg['id'], 'direction': display_direction, 'type': msg['type'],
            'content': msg['content'], 'timestamp': msg['timestamp'],
            'audio_file': msg.get('audio_file'), 'video_file': msg.get('video_file'),
            'is_delivered': msg.get('is_delivered', 0),
            'is_read_by_receiver': msg.get('is_read_by_receiver', 0),
        })
    return jsonify({
        "patient": {"id": patient[1], "name": patient[2], "location": patient[5]},
        "messages": message_list,
    })


@app.route('/doctor/register_patient', methods=['POST'])
@doctor_login_required
def doctor_register_patient():
    patient_id = "PAT" + str(uuid.uuid4())[:5].upper()
    phone = format_phone(request.form.get('phone_number'))
    password = request.form.get('password')
    confirm = request.form.get('confirm_password')
    if not password or len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters"}), 400
    if password != confirm:
        return jsonify({"error": "Passwords do not match"}), 400
    db.register_patient(
        patient_id, request.form.get('full_name'), phone, password,
        request.form.get('location'), request.form.get('arv_regimen', 'TLD'),
        request.form.get('medication_time', '20:00'),
        hospital_id=session.get('hospital_id'), registration_source='hospital',
    )
    db.add_audit_log('hospital', session.get('hospital_name', ''), 'register_patient',
                     'Registered patient ' + patient_id)
    return jsonify({"status": "success", "patient_id": patient_id})


@app.route('/doctor/register')
@doctor_login_required
def doctor_register_page():
    return render_template('doctor_register.html')


# ============ TREATMENTS ============
@app.route('/doctor/create_treatment', methods=['POST'])
@doctor_login_required
def create_treatment():
    data = request.json
    patient_id = data.get('patient_id')
    if not patient_id:
        return jsonify({"error": "Patient ID required"}), 400
    hospital_name = session.get('hospital_name', 'Hospital')
    treatment_id = db.create_treatment(
        patient_id, hospital_name, data.get('diagnosis', ''),
        data.get('notes', ''), data.get('next_appointment_date', ''),
        data.get('next_appointment_reason', ''),
    )
    for med in data.get('medications', []):
        db.add_prescribed_medication(
            treatment_id, med.get('medication_name'), med.get('dosage_amount'),
            med.get('dosage_unit', 'pill(s)'), med.get('times_per_day'),
            med.get('schedule_times', []), med.get('duration_days'),
            med.get('instructions', ''),
        )
    if data.get('next_appointment_date'):
        db.create_appointment_alert(patient_id, treatment_id, data['next_appointment_date'])
    patient = db.get_patient_by_id(patient_id)
    if patient:
        message = "📋 New treatment record from " + hospital_name + ". Check your dashboard."
        db.send_message_to_patient(patient_id, message, hospital_name)
        sms_handler.send_sms(patient[3], message, 'English')
    db.add_audit_log('hospital', hospital_name, 'create_treatment',
                     'Created treatment #' + str(treatment_id) + ' for ' + patient_id)
    return jsonify({"status": "success", "treatment_id": treatment_id})


@app.route('/doctor/get_patient_treatments/<patient_id>')
@doctor_login_required
def get_patient_treatments(patient_id):
    return jsonify(db.get_patient_treatments(patient_id))


@app.route('/doctor/get_all_treatments')
@doctor_login_required
def get_all_treatments():
    return jsonify(db.get_all_treatments(hospital_id=session.get('hospital_id')))


@app.route('/doctor/complete_treatment/<int:treatment_id>', methods=['POST'])
@doctor_login_required
def complete_treatment(treatment_id):
    db.mark_treatment_completed(treatment_id)
    db.add_audit_log('hospital', session.get('hospital_name', ''), 'complete_treatment',
                     'Completed treatment #' + str(treatment_id))
    return jsonify({"status": "success"})


# ============ REFILLS ============
@app.route('/doctor/get_refill_requests')
@doctor_login_required
def doctor_get_refill_requests():
    status = request.args.get('status', 'pending')
    search = request.args.get('search', '')
    hid = session.get('hospital_id')
    if status == 'pending':
        return jsonify(db.get_pending_refill_requests(hospital_id=hid))
    return jsonify(db.get_all_refill_requests_with_filters(status, search, hospital_id=hid))


@app.route('/doctor/approve_refill/<int:request_id>', methods=['POST'])
@doctor_login_required
def doctor_approve_refill(request_id):
    data = request.json
    use_patient_time = data.get('use_patient_time', True)
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT patient_id, patient_name, medication_name, preferred_pickup_date, preferred_pickup_time FROM refill_requests WHERE id = ?", (request_id,))
    req = cursor.fetchone()
    conn.close()
    if not req:
        return jsonify({"error": "Request not found"}), 404
    patient_id, patient_name, medication_name, pref_date, pref_time = req
    final_date = pref_date if use_patient_time else data.get('approved_date', '')
    final_time = pref_time if use_patient_time else data.get('approved_time', '')
    db.approve_refill_request(request_id, final_date, final_time, data.get('doctor_notes', ''), data.get('new_medication_time'))
    if data.get('new_medication_time'):
        db.update_patient_medication_time(patient_id, data['new_medication_time'], session.get('hospital_name', ''))
    message = "✅ REFILL APPROVED!\nYour refill for " + medication_name + " has been approved.\nPickup: " + str(final_date) + " at " + str(final_time)
    db.send_message_to_patient(patient_id, message, session.get('hospital_name', 'Hospital'))
    db.add_audit_log('hospital', session.get('hospital_name', ''), 'approve_refill',
                     'Approved refill #' + str(request_id))
    return jsonify({"status": "success"})


@app.route('/doctor/deny_refill/<int:request_id>', methods=['POST'])
@doctor_login_required
def doctor_deny_refill(request_id):
    data = request.json
    notes = data.get('doctor_notes', 'No reason provided')
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT patient_id, patient_name, medication_name FROM refill_requests WHERE id = ?", (request_id,))
    req = cursor.fetchone()
    conn.close()
    if not req:
        return jsonify({"error": "Request not found"}), 404
    patient_id, patient_name, medication_name = req
    db.deny_refill_request(request_id, notes)
    message = "❌ REFILL DENIED\nYour request for " + medication_name + " could not be approved.\nReason: " + notes
    db.send_message_to_patient(patient_id, message, session.get('hospital_name', 'Hospital'))
    db.add_audit_log('hospital', session.get('hospital_name', ''), 'deny_refill',
                     'Denied refill #' + str(request_id))
    return jsonify({"status": "success"})


# ============ EMERGENCIES ============
@app.route('/doctor/get_emergencies')
@doctor_login_required
def doctor_get_emergencies():
    hid = session.get('hospital_id')
    conn = db.get_connection()
    cursor = conn.cursor()
    if hid is not None:
        cursor.execute(
            """SELECT e.id, e.patient_id, e.patient_name, e.emergency_message,
                      e.communication_preference, e.priority_level, e.location_lat,
                      e.location_lng, e.location_address, e.timestamp, e.status,
                      e.doctor_response_timestamp, e.resolved_timestamp, e.escalation_sent
               FROM emergencies e
               JOIN patients p ON e.patient_id = p.patient_id
               WHERE p.hospital_id = ?
               ORDER BY e.timestamp DESC""",
            (hid,),
        )
    else:
        cursor.execute(
            """SELECT id, patient_id, patient_name, emergency_message,
                      communication_preference, priority_level, location_lat, location_lng,
                      location_address, timestamp, status, doctor_response_timestamp,
                      resolved_timestamp, escalation_sent
               FROM emergencies ORDER BY timestamp DESC"""
        )
    rows = cursor.fetchall()
    conn.close()
    return jsonify([
        {'id': r[0], 'patient_id': r[1], 'patient_name': r[2], 'emergency_message': r[3],
         'communication_preference': r[4], 'priority_level': r[5], 'location_lat': r[6],
         'location_lng': r[7], 'location_address': r[8], 'timestamp': r[9],
         'status': r[10], 'doctor_response_timestamp': r[11], 'resolved_timestamp': r[12],
         'escalation_sent': r[13] if len(r) > 13 else 0}
        for r in rows
    ])


@app.route('/doctor/emergency/<int:emergency_id>')
@doctor_login_required
def doctor_emergency_detail(emergency_id):
    emergency = db.get_emergency_by_id(emergency_id)
    messages = db.get_emergency_messages(emergency_id)
    patient = db.get_patient_by_id(emergency['patient_id']) if emergency else None
    return jsonify({
        "emergency": emergency,
        "messages": messages,
        "patient": {
            "id": patient[1] if patient else None,
            "name": patient[2] if patient else None,
            "location": patient[5] if patient else None,
            "phone": patient[3] if patient else None,
        },
    })


@app.route('/doctor/send_emergency_reply', methods=['POST'])
@doctor_login_required
def doctor_send_emergency_reply():
    emergency_id = request.form.get('emergency_id')
    message_type = request.form.get('message_type', 'text')
    content = request.form.get('content', '')
    audio_file = None
    emergency = db.get_emergency_by_id(emergency_id)
    if not emergency:
        return jsonify({"error": "Emergency not found"}), 404
    preference = emergency['communication_preference']
    if preference == 'text_only' and message_type != 'text':
        return jsonify({"error": "Patient requested text-only communication."}), 400
    if preference == 'audio_only' and message_type != 'audio':
        return jsonify({"error": "Patient requested audio-only communication."}), 400
    if message_type == 'audio' and 'audio' in request.files:
        audio = request.files['audio']
        if audio and audio.filename != '':
            audio_file = upload_to_cloudinary(
                audio, "emergency/doctor/" + str(emergency_id), "video"
            )
            content = "Voice message from hospital"
    if not emergency['doctor_response_timestamp']:
        db.record_doctor_emergency_response(emergency_id)
    db.save_emergency_message(emergency_id, 'doctor', message_type, content, audio_file)
    return jsonify({"status": "success"})


@app.route('/doctor/resolve_emergency/<int:emergency_id>', methods=['POST'])
@doctor_login_required
def doctor_resolve_emergency(emergency_id):
    db.mark_emergency_resolved(emergency_id)
    db.add_audit_log('hospital', session.get('hospital_name', ''), 'resolve_emergency',
                     'Resolved emergency #' + str(emergency_id))
    return jsonify({"status": "success"})


@app.route('/doctor/get_live_location/<int:emergency_id>')
@doctor_login_required
def get_live_location(emergency_id):
    return jsonify({
        "current": db.get_latest_emergency_location(emergency_id),
        "history": db.get_emergency_locations(emergency_id),
    })


@app.route('/doctor/get_nearest_hospital_from_coords', methods=['POST'])
@doctor_login_required
def get_nearest_hospital_from_coords():
    data = request.json
    lat = data.get('lat')
    lng = data.get('lng')
    hospitals = [
        {"name": "Siaya County Referral Hospital", "lat": -0.0614, "lng": 34.2880, "phone": "057-123456", "address": "Siaya Town"},
        {"name": "Bondo Sub-County Hospital", "lat": -0.0980, "lng": 34.2730, "phone": "057-345678", "address": "Bondo Town"},
        {"name": "Jaramogi Oginga Odinga Hospital", "lat": -0.1035, "lng": 34.7550, "phone": "057-456789", "address": "Kisumu"},
        {"name": "Rangala Health Centre", "lat": 0.0720, "lng": 34.1580, "phone": "057-567890", "address": "Rangala"},
        {"name": "Ugunja Sub-County Hospital", "lat": 0.1650, "lng": 34.1200, "phone": "057-678901", "address": "Ugunja"},
    ]
    for h in hospitals:
        h['distance_km'] = round(haversine(lat, lng, h['lat'], h['lng']), 2)
    hospitals.sort(key=lambda x: x['distance_km'])
    return jsonify({"nearest": hospitals[0], "all": hospitals[:3]})


@app.route('/doctor/emergency_check')
@doctor_login_required
def doctor_emergency_check():
    emergencies = db.get_active_emergencies(hospital_id=session.get('hospital_id'))
    return jsonify({"has_emergency": len(emergencies) > 0, "count": len(emergencies)})


@app.route('/doctor/delete_message/<int:message_id>', methods=['DELETE'])
@doctor_login_required
def doctor_delete_message(message_id):
    db.delete_message(message_id)
    return jsonify({"status": "success"})


@app.route('/doctor/get_patient_emergency_contacts/<patient_id>')
@doctor_login_required
def doctor_get_patient_emergency_contacts(patient_id):
    return jsonify(db.get_shared_emergency_contacts(patient_id))


# ============ SIMULATORS ============
@app.route('/simulate/sms')
@login_required
def simulate_sms():
    return render_template('sms_simulator.html')


@app.route('/simulate/voice')
@login_required
def simulate_voice():
    return render_template('voice_simulator.html')


@app.route('/test_audio')
@login_required
def test_audio():
    return render_template('test_audio.html')


# ============ LOGOUT ============
@app.route('/logout')
def logout():
    if session.get('user_type') == 'patient':
        db.add_audit_log('patient', session.get('patient_id', ''), 'logout', 'User logged out')
    elif session.get('user_type') == 'hospital':
        db.add_audit_log('hospital', session.get('hospital_name', ''), 'logout', 'User logged out')
    session.clear()
    return redirect(url_for('index'))




# ============ FORGOT PASSWORD ============
from password_reset import (
    verify_patient_identity, reset_patient_password,
    verify_hospital_identity, reset_hospital_password,
)


@app.route('/forgot_password')
def forgot_password_page():
    return render_template('forgot_password.html')


@app.route('/forgot_password/patient', methods=['POST'])
def forgot_password_patient():
    patient_id = request.form.get('patient_id', '').strip()
    phone = request.form.get('phone_number', '').strip()
    new_password = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')

    if not patient_id or not phone or not new_password:
        return render_template('forgot_password.html', patient_error="Please fill all fields.", active_tab='patient')
    if len(new_password) < 4:
        return render_template('forgot_password.html', patient_error="Password must be at least 4 characters.", active_tab='patient')
    if new_password != confirm:
        return render_template('forgot_password.html', patient_error="Passwords do not match.", active_tab='patient')
    if not verify_patient_identity(db, patient_id, phone):
        return render_template('forgot_password.html', patient_error="Patient ID and phone number do not match our records.", active_tab='patient')

    try:
        reset_patient_password(db, patient_id, new_password)
        db.add_audit_log('patient', patient_id, 'password_reset', 'Password reset via forgot-password')
        return render_template('forgot_password.html', success=True, success_message="Password reset successfully.", active_tab='patient')
    except Exception as e:
        return render_template('forgot_password.html', patient_error="Reset failed: " + str(e), active_tab='patient')


@app.route('/forgot_password/hospital', methods=['POST'])
def forgot_password_hospital():
    username = request.form.get('username', '').strip().lower()
    phone = request.form.get('contact_phone', '').strip()
    new_password = request.form.get('new_password', '')
    confirm = request.form.get('confirm_password', '')

    if not username or not phone or not new_password:
        return render_template('forgot_password.html', hospital_error="Please fill all fields.", active_tab='hospital')
    if len(new_password) < 6:
        return render_template('forgot_password.html', hospital_error="Password must be at least 6 characters.", active_tab='hospital')
    if new_password != confirm:
        return render_template('forgot_password.html', hospital_error="Passwords do not match.", active_tab='hospital')
    if not verify_hospital_identity(db, username, phone):
        return render_template('forgot_password.html', hospital_error="Username and phone do not match our records.", active_tab='hospital')

    try:
        reset_hospital_password(db, username, new_password)
        db.add_audit_log('hospital', username, 'password_reset', 'Password reset via forgot-password')
        return render_template('forgot_password.html', success=True, success_message="Password reset successfully.", active_tab='hospital')
    except Exception as e:
        return render_template('forgot_password.html', hospital_error="Reset failed: " + str(e), active_tab='hospital')




# ============ SUPER ADMIN ============
def super_admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_type' not in session or session.get('user_type') != 'super_admin':
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


def _time_ago(iso_ts):
    if not iso_ts:
        return '—'
    try:
        t = datetime.fromisoformat(iso_ts)
        secs = int((datetime.now() - t).total_seconds())
        if secs < 60: return str(secs) + 's ago'
        if secs < 3600: return str(secs // 60) + 'm ago'
        if secs < 86400: return str(secs // 3600) + 'h ago'
        return str(secs // 86400) + 'd ago'
    except Exception:
        return str(iso_ts)[:19]


def _response_time(e):
    if not e.get('doctor_response_timestamp') or not e.get('timestamp'):
        return '—'
    try:
        sent = datetime.fromisoformat(e['timestamp'])
        resp = datetime.fromisoformat(e['doctor_response_timestamp'])
        return str(round((resp - sent).total_seconds() / 60, 1)) + ' min'
    except Exception:
        return '—'


@app.route('/super_admin/login', methods=['POST'])
def super_admin_login():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    if not username or not password:
        return render_template('login.html', error="Please enter username and password")
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, username, password_hash, full_name, email, phone, is_active, last_login
           FROM super_admins WHERE username = ? AND is_active = 1""",
        (username,),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return render_template('login.html', error="Invalid credentials")
    from password_utils import verify_password
    if not verify_password(password, row[2]):
        conn.close()
        return render_template('login.html', error="Invalid credentials")
    cursor.execute("UPDATE super_admins SET last_login = ? WHERE id = ?",
                   (datetime.now().isoformat(), row[0]))
    conn.commit()
    conn.close()
    session.clear()
    session['user_type'] = 'super_admin'
    session['super_admin_id'] = row[0]
    session['super_admin_username'] = row[1]
    session['super_admin_name'] = row[3]
    # Use the director's linked hospital
    hid = None
    try:
        conn2 = db.get_connection()
        c2 = conn2.cursor()
        c2.execute("SELECT hospital_id FROM super_admins WHERE id = ?", (row[0],))
        rr = c2.fetchone()
        if rr and rr[0]:
            hid = rr[0]
        conn2.close()
    except Exception:
        pass
    session['hospital_id'] = hid or 1
    session['hospital_name'] = 'FastAfya Hospital'
    if hid:
        try:
            h = db.get_hospital_by_id(hid)
            if h:
                session['hospital_name'] = h[1]
        except Exception:
            pass
    session.permanent = True
    db.add_audit_log('super_admin', username, 'login', 'Super Admin logged in')
    return redirect(url_for('super_admin_dashboard'))


@app.route('/super_admin/dashboard')
@super_admin_login_required
def super_admin_dashboard():
    super_admin = {
        'id': session.get('super_admin_id'),
        'username': session.get('super_admin_username'),
        'full_name': session.get('super_admin_name', 'Director'),
        'last_login': None,
    }
    try:
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("SELECT last_login FROM super_admins WHERE id = ?", (super_admin['id'],))
        r = c.fetchone()
        if r: super_admin['last_login'] = r[0]
        conn.close()
    except Exception:
        pass

    hid = session.get('hospital_id', 1)
    departments = db.get_hospital_departments(hid, active_only=False)
    patients_raw = db.get_all_patients(hospital_id=hid)
    patients = [{'patient_id': p[1], 'full_name': p[2], 'phone_number': p[3],
                 'location': p[4], 'registration_date': p[7], 'status': p[8]}
                for p in patients_raw]
    active_emergencies = db.get_active_emergencies(hospital_id=hid)

    stats = {
        'total_patients': len(patients),
        'active_departments': len([d for d in departments if d['is_active']]),
        'open_emergencies': len(active_emergencies),
        'unanswered': 0,
        'refills_week': 0,
    }

    activity = []
    try:
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("""SELECT user_type, user_id, action, details, timestamp
                     FROM audit_logs ORDER BY id DESC LIMIT 15""")
        for r in c.fetchall():
            activity.append({
                'text': str(r[0]) + ' "' + str(r[1] or '') + '" — ' + str(r[2] or '') + ': ' + str(r[3] or ''),
                'when': _time_ago(r[4]),
            })
        conn.close()
    except Exception:
        pass

    dept_health = [{
        'name': d['name'], 'open_chats': 0, 'unanswered': 0, 'last_response': '—',
        'status_class': 'ok' if d['is_active'] else 'danger',
        'status_label': 'Active' if d['is_active'] else 'Inactive',
    } for d in departments]

    alerts = []
    for d in departments:
        if d['is_active'] and not d['username']:
            alerts.append({'text': "Department '" + d['name'] + "' has no login credentials", 'level': 'warn'})

    resolved_emergencies = []
    try:
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("""SELECT patient_name, timestamp, resolved_timestamp, doctor_response_timestamp
                     FROM emergencies WHERE status = 'resolved' ORDER BY id DESC LIMIT 20""")
        for r in c.fetchall():
            rt = '—'
            if r[3] and r[1]:
                try:
                    rt = str(round((datetime.fromisoformat(r[3]) - datetime.fromisoformat(r[1])).total_seconds() / 60, 1)) + ' min'
                except Exception:
                    pass
            resolved_emergencies.append({
                'patient_name': r[0], 'when': _time_ago(r[1]),
                'resolved_when': _time_ago(r[2]), 'response_time': rt,
            })
        conn.close()
    except Exception:
        pass

    audit = []
    try:
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("""SELECT user_type, user_id, action, details, timestamp
                     FROM audit_logs ORDER BY id DESC LIMIT 100""")
        for r in c.fetchall():
            audit.append({
                'user_type': r[0], 'user_id': r[1], 'action': r[2],
                'details': r[3], 'when': str(r[4])[:19] if r[4] else '—',
            })
        conn.close()
    except Exception:
        pass

    return render_template(
        'super_admin_dashboard.html',
        super_admin=super_admin, stats=stats, activity=activity, alerts=alerts,
        dept_health=dept_health, departments=departments, patients=patients,
        active_emergencies=[{
            'patient_name': e['patient_name'],
            'location_address': e.get('location_address'),
            'when': _time_ago(e['timestamp']),
            'responded': e.get('doctor_response_timestamp') is not None,
            'response_time': _response_time(e),
        } for e in active_emergencies],
        resolved_emergencies=resolved_emergencies,
        conversations=[], referrals=[], prescriptions=[], refills=[],
        audit=audit, session=session,
    )


@app.route('/super_admin/change_password', methods=['POST'])
@super_admin_login_required
def super_admin_change_password():
    current = request.form.get('current_password', '')
    new = request.form.get('new_password', '')
    if len(new) < 6:
        return redirect(url_for('super_admin_dashboard'))
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("SELECT password_hash FROM super_admins WHERE id = ?", (session['super_admin_id'],))
    r = c.fetchone()
    if not r:
        conn.close()
        return redirect(url_for('super_admin_dashboard'))
    from password_utils import verify_password, hash_password
    if not verify_password(current, r[0]):
        conn.close()
        return redirect(url_for('super_admin_dashboard'))
    c.execute("UPDATE super_admins SET password_hash = ? WHERE id = ?",
              (hash_password(new), session['super_admin_id']))
    conn.commit()
    conn.close()
    db.add_audit_log('super_admin', session['super_admin_username'], 'change_password', 'Password changed')
    return redirect(url_for('super_admin_dashboard'))




# ============ DEPARTMENT MANAGEMENT (Director) ============
@app.route('/hospital/departments')
@doctor_login_required
def hospital_departments_page():
    hid = session.get('hospital_id') or 1
    departments = db.get_hospital_departments(hid, active_only=False)
    return render_template('hospital_departments.html',
                          departments=departments,
                          hospital_name=session.get('hospital_name', 'Hospital'),
                          message=request.args.get('message'),
                          error=request.args.get('error'))


@app.route('/hospital/departments/create', methods=['POST'])
@doctor_login_required
def hospital_create_department():
    hid = session.get('hospital_id') or 1
    name = request.form.get('name', '').strip()
    username = request.form.get('username', '').strip().lower()
    password = request.form.get('password', '')
    if not name or not username or not password:
        return redirect(url_for('hospital_departments_page', error="Name, username and password are required"))
    if len(password) < 6:
        return redirect(url_for('hospital_departments_page', error="Password must be at least 6 characters"))
    existing = db.get_department_by_username(username)
    if existing:
        return redirect(url_for('hospital_departments_page', error="That username is already taken"))
    try:
        db.create_department(
            hospital_id=hid, name=name,
            description=request.form.get('description', ''),
            head_doctor=request.form.get('head_doctor', ''),
            secretary_name=request.form.get('secretary_name', ''),
            phone=request.form.get('phone', ''),
            email=request.form.get('email', ''),
            consultation_fee=request.form.get('consultation_fee', ''),
            operating_hours=request.form.get('operating_hours', '24/7'),
            username=username, password=password,
        )
        db.add_audit_log('hospital', session.get('hospital_name', ''), 'create_department', 'Created ' + name)
        return redirect(url_for('hospital_departments_page', message="Department '" + name + "' created"))
    except Exception as e:
        return redirect(url_for('hospital_departments_page', error="Failed: " + str(e)))


@app.route('/hospital/departments/<int:dept_id>/update', methods=['POST'])
@doctor_login_required
def hospital_update_department(dept_id):
    d = db.get_department_by_id(dept_id)
    if not d or d['hospital_id'] != (session.get('hospital_id') or 1):
        return redirect(url_for('hospital_departments_page', error="Not found"))
    db.update_department(
        dept_id,
        name=request.form.get('name'),
        description=request.form.get('description'),
        head_doctor=request.form.get('head_doctor'),
        secretary_name=request.form.get('secretary_name'),
        phone=request.form.get('phone'),
        consultation_fee=request.form.get('consultation_fee'),
        operating_hours=request.form.get('operating_hours'),
    )
    return redirect(url_for('hospital_departments_page', message="Updated"))


@app.route('/hospital/departments/<int:dept_id>/credentials', methods=['POST'])
@doctor_login_required
def hospital_set_dept_credentials(dept_id):
    d = db.get_department_by_id(dept_id)
    if not d or d['hospital_id'] != (session.get('hospital_id') or 1):
        return redirect(url_for('hospital_departments_page', error="Not found"))
    username = request.form.get('username', '').strip().lower()
    password = request.form.get('password', '')
    if not username or len(password) < 6:
        return redirect(url_for('hospital_departments_page', error="Username and 6+ char password required"))
    try:
        db.update_department(dept_id, username=username, password=password)
        return redirect(url_for('hospital_departments_page', message="Credentials updated"))
    except Exception as e:
        return redirect(url_for('hospital_departments_page', error="Failed: " + str(e)))


@app.route('/hospital/departments/<int:dept_id>/delete', methods=['POST'])
@doctor_login_required
def hospital_delete_department(dept_id):
    d = db.get_department_by_id(dept_id)
    if not d or d['hospital_id'] != (session.get('hospital_id') or 1):
        return redirect(url_for('hospital_departments_page', error="Not found"))
    db.update_department(dept_id, is_active=0)
    return redirect(url_for('hospital_departments_page', message="Department deactivated"))


@app.route('/hospital/departments/<int:dept_id>/photo', methods=['POST'])
@doctor_login_required
def hospital_upload_dept_photo(dept_id):
    d = db.get_department_by_id(dept_id)
    if not d or d['hospital_id'] != (session.get('hospital_id') or 1):
        return redirect(url_for('hospital_departments_page', error="Not found"))
    if 'photo' not in request.files:
        return redirect(url_for('hospital_departments_page', error="No file uploaded"))
    file = request.files['photo']
    if not file.filename:
        return redirect(url_for('hospital_departments_page', error="No file selected"))
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
    if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
        return redirect(url_for('hospital_departments_page', error="Only image files allowed"))
    photo_dir = os.path.join('static', 'department_photos')
    os.makedirs(photo_dir, exist_ok=True)
    fname = "dept_" + str(dept_id) + "_" + uuid.uuid4().hex[:8] + "." + ext
    file.save(os.path.join(photo_dir, fname))
    db.add_department_photo(dept_id, fname, request.form.get('caption', ''))
    return redirect(url_for('hospital_departments_page', message="Photo uploaded"))




@app.route('/hospital/departments/toggle/<int:dept_id>', methods=['POST'])
@doctor_login_required
def hospital_toggle_department(dept_id):
    d = db.get_department_by_id(dept_id)
    if not d or d['hospital_id'] != (session.get('hospital_id') or 1):
        return redirect(url_for('hospital_departments_page', error="Not found"))
    new_status = 0 if d['is_active'] else 1
    db.update_department(dept_id, is_active=new_status)
    msg = "Department activated" if new_status else "Department deactivated"
    db.add_audit_log('hospital', session.get('hospital_name', ''), 'toggle_department', msg + ': ' + d['name'])
    return redirect(url_for('hospital_departments_page', message=msg))




# ============ DEPARTMENT ROUTES ============
def department_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_type' not in session or session.get('user_type') != 'department':
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/department/login', methods=['POST'])
def department_login():
    username = request.form.get('username', '').strip().lower()
    password = request.form.get('password', '')
    if not username or not password:
        return render_template('login.html', error="Please enter username and password")
    failed_count = db.get_failed_attempts(username=username)
    if failed_count >= 5:
        return render_template('login.html', error="Account locked. Try again later.")
    dept = db.authenticate_department(username, password)
    if dept:
        db.clear_failed_attempts(username=username)
        session.clear()
        session['user_type'] = 'department'
        session['department_id'] = dept['id']
        session['department_name'] = dept['name']
        session['hospital_id'] = dept['hospital_id']
        session['hospital_name'] = dept.get('hospital_name', 'Hospital')
        session['doctor_id'] = dept['id']
        session['doctor_name'] = dept['name']
        session['hospital'] = session['hospital_name']
        session.permanent = True
        db.add_audit_log('department', username, 'login', 'Department ' + dept['name'] + ' logged in')
        return redirect(url_for('department_dashboard'))
    db.record_failed_login(username=username)
    remaining = 4 - failed_count
    return render_template('login.html', error="Invalid credentials. " + str(remaining) + " attempts remaining.")


@app.route('/department/dashboard')
@department_login_required
def department_dashboard():
    dept_id = session['department_id']
    dept = db.get_department_by_id(dept_id)
    if not dept:
        session.clear()
        return redirect(url_for('index'))
    hospital = db.get_hospital_by_id(dept['hospital_id'])
    if hospital:
        dept['hospital_name'] = hospital[1]
        dept['hospital_county'] = hospital[10] if len(hospital) > 10 else ''
    else:
        dept['hospital_name'] = session.get('hospital_name', 'Hospital')
        dept['hospital_county'] = ''
    photos = db.get_department_photos(dept_id)
    services = db.get_department_services(dept_id)
    patients_raw = db.get_all_patients(hospital_id=dept['hospital_id'])
    patients = [{'patient_id': p[1], 'full_name': p[2], 'location': p[4]}
                for p in patients_raw]
    emergencies = db.get_active_emergencies(hospital_id=dept['hospital_id'])
    stats = db.get_department_stats(dept_id)
    return render_template('department_dashboard.html',
                          department=dept,
                          photos=photos,
                          services=services,
                          patients=patients,
                          patient_count=len(patients),
                          active_emergencies=len(emergencies),
                          stats=stats,
                          session=session)




@app.route('/favicon.ico')
def favicon():
    return "", 204




# ============ DEPARTMENT FULL FUNCTIONALITY ============
@app.route('/department/enquiries')
@department_login_required
def department_enquiries():
    dept_id = session['department_id']
    threads = db.get_department_threads(dept_id)
    return jsonify(threads)


@app.route('/department/enquiry/<patient_id>')
@department_login_required
def department_enquiry_thread(patient_id):
    dept_id = session['department_id']
    msgs = db.get_department_patient_thread(patient_id, dept_id)
    db.mark_department_thread_read(patient_id, dept_id)
    patient = db.get_patient_by_id(patient_id)
    return jsonify({
        "patient": {
            "id": patient_id,
            "name": patient[2] if patient else "",
            "phone": patient[3] if patient else "",
            "location": patient[5] if patient else "",
        },
        "messages": msgs,
    })


@app.route('/department/enquiry/<patient_id>/reply', methods=['POST'])
@department_login_required
def department_enquiry_reply(patient_id):
    dept_id = session['department_id']
    content = request.form.get('content', '').strip()
    if not content:
        return jsonify({"error": "Message required"}), 400
    db.send_department_message(patient_id, dept_id, 'incoming', content)
    patient = db.get_patient_by_id(patient_id)
    if patient:
        sms_handler.send_sms(patient[3], content, 'English')
    return jsonify({"status": "success"})


@app.route('/department/bookings')
@department_login_required
def department_bookings():
    dept_id = session['department_id']
    status = request.args.get('status')
    appts = db.get_department_appointments(dept_id, status)
    return jsonify(appts)


@app.route('/department/booking/<int:appt_id>/status', methods=['POST'])
@department_login_required
def department_booking_status(appt_id):
    dept_id = session['department_id']
    status = request.json.get('status') if request.is_json else request.form.get('status')
    if status not in ('pending', 'confirmed', 'checked_in', 'completed', 'cancelled', 'no_show'):
        return jsonify({"error": "Invalid status"}), 400
    db.update_appointment_status(appt_id, status, dept_id)
    return jsonify({"status": "success"})


@app.route('/department/my-patients')
@department_login_required
def department_my_patients():
    dept_id = session['department_id']
    return jsonify(db.get_department_patients(dept_id))


@app.route('/department/treatments')
@department_login_required
def department_treatments_list():
    dept_id = session['department_id']
    return jsonify(db.get_department_treatments(dept_id))


@app.route('/department/prescribe', methods=['POST'])
@department_login_required
def department_prescribe():
    dept_id = session['department_id']
    dept = db.get_department_by_id(dept_id)
    data = request.json
    patient_id = data.get('patient_id')
    if not patient_id:
        return jsonify({"error": "Patient ID required"}), 400
    tid = db.create_department_treatment(
        patient_id, dept_id, dept['name'],
        data.get('diagnosis', ''), data.get('notes', ''),
        data.get('next_appointment_date', ''),
        data.get('next_appointment_reason', ''),
    )
    # Prescribed meds
    for med in data.get('medications', []):
        db.add_prescribed_medication(
            tid, med.get('medication_name'), med.get('dosage_amount'),
            med.get('dosage_unit', 'pill(s)'), med.get('times_per_day'),
            med.get('schedule_times', []), med.get('duration_days'),
            med.get('instructions', ''),
        )
    # Notify patient
    patient = db.get_patient_by_id(patient_id)
    if patient:
        msg = "New treatment from " + dept['name'] + ". Check your dashboard."
        db.send_department_message(patient_id, dept_id, 'incoming', msg)
        sms_handler.send_sms(patient[3], msg, 'English')
    return jsonify({"status": "success", "treatment_id": tid})


@app.route('/department/photo/upload', methods=['POST'])
@department_login_required
def department_photo_upload():
    dept_id = session['department_id']
    if 'photo' not in request.files:
        return jsonify({"error": "No file"}), 400
    file = request.files['photo']
    if not file.filename:
        return jsonify({"error": "Empty file"}), 400
    url = upload_to_cloudinary(file, "departments/" + str(dept_id), "image")
    if not url:
        return jsonify({"error": "Upload failed"}), 500
    db.add_department_photo(dept_id, url, request.form.get('caption', ''))
    return jsonify({"status": "success", "url": url})


@app.route('/department/service/add', methods=['POST'])
@department_login_required
def department_service_add():
    dept_id = session['department_id']
    name = request.form.get('name', '').strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    db.add_department_service(dept_id, name, request.form.get('description', ''))
    return jsonify({"status": "success"})


# ============ MAIN ============
if __name__ == '__main__':
    for dir_name in ['static', 'static/voice_recordings', 'static/video_recordings', 'static/emergency_audio']:
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)

    print("\n" + "="*70)
    print("FastAfya - Hospital-Based Model")
    print("="*70)
    print("\nHospital Login: siaya.hospital / hospital123")
    print("Or register a new hospital at /hospital/register")
    print("Patients can self-register at /patient/register")
    print("\nAccess at: http://localhost:5000")
    print("="*70 + "\n")

    scheduler.start()
    schedule_all_reminders()
    atexit.register(lambda: scheduler.shutdown())

    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5000)
