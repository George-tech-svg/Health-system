# _cloud.py
# 1. Add Cloudinary imports + config + helper to app.py
# 2. Replace all 7 upload routes with Cloudinary
# 3. Add department toggle (activate/deactivate) route
# 4. Update templates to use Cloudinary URLs directly
# 5. Fix activate/deactivate button in hospital_departments.html

import pathlib
import re

# ============================================================
# 1. ADD CLOUDINARY SETUP TO app.py
# ============================================================
app_path = pathlib.Path("app.py")
app = app_path.read_text(encoding="utf-8")

if "import cloudinary" not in app:
    # Insert after the translator import
    old = "from translator import translator"
    new = """from translator import translator
import cloudinary
import cloudinary.uploader

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True,
)


def upload_to_cloudinary(file_obj, folder, resource_type="image"):
    \"\"\"Upload a Flask FileStorage to Cloudinary, return the secure URL.\"\"\"
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
"""
    if old in app:
        app = app.replace(old, new, 1)
        print("[1/6] OK - Cloudinary imports + config + helper added")
    else:
        print("[1/6] ERROR - translator import marker not found")
else:
    print("[1/6] SKIP - Cloudinary already imported")

# ============================================================
# 2. REPLACE UPLOAD ROUTES
# ============================================================

# --- Patient voice upload ---
old = """        audio_filename = None
        if 'audio' in request.files:
            audio_file = request.files['audio']
            if audio_file and audio_file.filename != '':
                audio_dir = os.path.join('static', 'voice_recordings')
                if not os.path.exists(audio_dir):
                    os.makedirs(audio_dir)
                audio_filename = patient[1] + "_" + datetime.now().strftime('%Y%m%d_%H%M%S') + ".webm"
                audio_file.save(os.path.join(audio_dir, audio_filename))"""
new = """        audio_filename = None
        if 'audio' in request.files:
            audio_file = request.files['audio']
            if audio_file and audio_file.filename != '':
                audio_filename = upload_to_cloudinary(
                    audio_file, "voice/patients/" + patient[1], "video"
                )"""
if old in app:
    app = app.replace(old, new, 1)
    print("[2/6] OK - patient voice -> Cloudinary")

# --- Patient video upload ---
old = """        video_filename = None
        if 'video' in request.files:
            video_file = request.files['video']
            if video_file and video_file.filename != '':
                video_dir = os.path.join('static', 'video_recordings')
                if not os.path.exists(video_dir):
                    os.makedirs(video_dir)
                video_filename = "VID_" + patient[1] + "_" + datetime.now().strftime('%Y%m%d_%H%M%S') + ".webm"
                video_file.save(os.path.join(video_dir, video_filename))"""
new = """        video_filename = None
        if 'video' in request.files:
            video_file = request.files['video']
            if video_file and video_file.filename != '':
                video_filename = upload_to_cloudinary(
                    video_file, "video/patients/" + patient[1], "video"
                )"""
if old in app:
    app = app.replace(old, new, 1)
    print("[2/6] OK - patient video -> Cloudinary")

# --- Doctor voice reply ---
old = """    audio_filename = None
    if 'audio' in request.files:
        audio_file = request.files['audio']
        if audio_file and audio_file.filename != '':
            audio_dir = os.path.join('static', 'voice_recordings')
            if not os.path.exists(audio_dir):
                os.makedirs(audio_dir)
            audio_filename = "DR_" + patient[1] + "_" + datetime.now().strftime('%Y%m%d_%H%M%S') + ".webm"
            audio_file.save(os.path.join(audio_dir, audio_filename))"""
new = """    audio_filename = None
    if 'audio' in request.files:
        audio_file = request.files['audio']
        if audio_file and audio_file.filename != '':
            audio_filename = upload_to_cloudinary(
                audio_file, "voice/doctors/" + patient[1], "video"
            )"""
if old in app:
    app = app.replace(old, new, 1)
    print("[2/6] OK - doctor voice -> Cloudinary")

# --- Doctor video reply ---
old = """    video_filename = None
    if 'video' in request.files:
        video_file = request.files['video']
        if video_file and video_file.filename != '':
            video_dir = os.path.join('static', 'video_recordings')
            if not os.path.exists(video_dir):
                os.makedirs(video_dir)
            video_filename = "DR_VID_" + patient[1] + "_" + datetime.now().strftime('%Y%m%d_%H%M%S') + ".webm"
            video_file.save(os.path.join(video_dir, video_filename))"""
new = """    video_filename = None
    if 'video' in request.files:
        video_file = request.files['video']
        if video_file and video_file.filename != '':
            video_filename = upload_to_cloudinary(
                video_file, "video/doctors/" + patient[1], "video"
            )"""
if old in app:
    app = app.replace(old, new, 1)
    print("[2/6] OK - doctor video -> Cloudinary")

# --- Patient emergency audio ---
old = """    if message_type == 'audio' and 'audio' in request.files:
        audio = request.files['audio']
        if audio and audio.filename != '':
            audio_dir = os.path.join('static', 'emergency_audio')
            if not os.path.exists(audio_dir):
                os.makedirs(audio_dir)
            audio_filename = "patient_reply_" + str(emergency_id) + "_" + datetime.now().strftime('%Y%m%d_%H%M%S') + ".webm"
            audio.save(os.path.join(audio_dir, audio_filename))
            audio_file = audio_filename
            content = "Voice message from patient\""""
new = """    if message_type == 'audio' and 'audio' in request.files:
        audio = request.files['audio']
        if audio and audio.filename != '':
            audio_file = upload_to_cloudinary(
                audio, "emergency/patient/" + str(emergency_id), "video"
            )
            content = "Voice message from patient\""""
if old in app:
    app = app.replace(old, new, 1)
    print("[2/6] OK - patient emergency audio -> Cloudinary")

# --- Doctor emergency audio ---
old = """    if message_type == 'audio' and 'audio' in request.files:
        audio = request.files['audio']
        if audio and audio.filename != '':
            audio_dir = os.path.join('static', 'emergency_audio')
            if not os.path.exists(audio_dir):
                os.makedirs(audio_dir)
            audio_filename = "doctor_reply_" + str(emergency_id) + "_" + datetime.now().strftime('%Y%m%d_%H%M%S') + ".webm"
            audio.save(os.path.join(audio_dir, audio_filename))
            audio_file = audio_filename
            content = "Voice message from hospital\""""
new = """    if message_type == 'audio' and 'audio' in request.files:
        audio = request.files['audio']
        if audio and audio.filename != '':
            audio_file = upload_to_cloudinary(
                audio, "emergency/doctor/" + str(emergency_id), "video"
            )
            content = "Voice message from hospital\""""
if old in app:
    app = app.replace(old, new, 1)
    print("[2/6] OK - doctor emergency audio -> Cloudinary")

# --- Department photo ---
old = """    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
    if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
        return redirect(url_for('hospital_departments_page', error="Only images allowed"))
    photo_dir = os.path.join('static', 'department_photos')
    os.makedirs(photo_dir, exist_ok=True)
    fname = "dept_" + str(dept_id) + "_" + uuid.uuid4().hex[:8] + "." + ext
    file.save(os.path.join(photo_dir, fname))
    db.add_department_photo(dept_id, fname, request.form.get('caption', ''))
    return redirect(url_for('hospital_departments_page', message="Photo uploaded"))"""
new = """    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
    if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
        return redirect(url_for('hospital_departments_page', error="Only images allowed"))
    url = upload_to_cloudinary(file, "departments/" + str(dept_id), "image")
    if not url:
        return redirect(url_for('hospital_departments_page', error="Upload failed"))
    db.add_department_photo(dept_id, url, request.form.get('caption', ''))
    return redirect(url_for('hospital_departments_page', message="Photo uploaded"))"""
if old in app:
    app = app.replace(old, new, 1)
    print("[2/6] OK - department photo -> Cloudinary")

# ============================================================
# 3. ADD TOGGLE ROUTE
# ============================================================
if "/hospital/departments/toggle/" not in app:
    ROUTE = '''

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

'''
    marker = "# ============ MAIN ============"
    if marker in app:
        app = app.replace(marker, ROUTE + "\n" + marker, 1)
        print("[3/6] OK - department toggle route added")
    else:
        print("[3/6] ERROR - MAIN marker not found")
else:
    print("[3/6] SKIP - toggle route already exists")

app_path.write_text(app, encoding="utf-8")

# ============================================================
# 4. FIX BUTTON IN hospital_departments.html
# ============================================================
tpl_path = pathlib.Path("templates/hospital_departments.html")
tpl = tpl_path.read_text(encoding="utf-8")

old_btn = '''<form method="POST" action="/hospital/departments/{{ d.id }}/delete" style="display:inline;" onsubmit="return confirm('Deactivate this department?');">
<button type="submit" class="btn btn-danger btn-sm">🗑️ Deactivate</button>
</form>'''
new_btn = '''{% if d.is_active %}
<form method="POST" action="/hospital/departments/toggle/{{ d.id }}" style="display:inline;" onsubmit="return confirm('Deactivate this department?');">
<button type="submit" class="btn btn-danger btn-sm">⏸️ Deactivate</button>
</form>
{% else %}
<form method="POST" action="/hospital/departments/toggle/{{ d.id }}" style="display:inline;" onsubmit="return confirm('Activate this department?');">
<button type="submit" class="btn btn-primary btn-sm">▶️ Activate</button>
</form>
{% endif %}'''

if old_btn in tpl:
    tpl = tpl.replace(old_btn, new_btn)
    tpl_path.write_text(tpl, encoding="utf-8")
    print("[4/6] OK - activate/deactivate button fixed")
else:
    # Try simpler match
    old_btn2 = '<button type="submit" class="btn btn-danger btn-sm">🗑️ Deactivate</button>'
    new_btn2 = '''{% if d.is_active %}<button type="submit" class="btn btn-danger btn-sm">⏸️ Deactivate</button>{% else %}<button type="submit" class="btn btn-primary btn-sm">▶️ Activate</button>{% endif %}'''
    if old_btn2 in tpl:
        # Need to change action too
        tpl = tpl.replace('action="/hospital/departments/{{ d.id }}/delete"', 'action="/hospital/departments/toggle/{{ d.id }}"')
        tpl = tpl.replace(old_btn2, new_btn2)
        tpl_path.write_text(tpl, encoding="utf-8")
        print("[4/6] OK - activate/deactivate button fixed (fallback)")
    else:
        print("[4/6] WARN - button not matched. Look at hospital_departments.html manually")

# ============================================================
# 5. UPDATE ALL TEMPLATES TO USE URLs DIRECTLY
# ============================================================
template_files = [
    "templates/patient_dashboard.html",
    "templates/doctor_dashboard.html",
    "templates/department_dashboard.html",
    "templates/super_admin_dashboard.html",
]

for tp in template_files:
    p = pathlib.Path(tp)
    if not p.exists():
        print("[5/6] SKIP - " + tp + " not found")
        continue
    t = p.read_text(encoding="utf-8")
    before = t

    # Voice recordings path -> direct URL
    t = t.replace('/static/voice_recordings/${msg.audio_file}', '${msg.audio_file}')
    t = t.replace('/static/video_recordings/${msg.video_file}', '${msg.video_file}')
    t = t.replace('/static/emergency_audio/${msg.audio_file}', '${msg.audio_file}')

    # Jinja template versions (using {{ }})
    t = t.replace('/static/voice_recordings/{{ msg.audio_file }}', '{{ msg.audio_file }}')
    t = t.replace('/static/video_recordings/{{ msg.video_file }}', '{{ msg.video_file }}')
    t = t.replace('/static/emergency_audio/{{ msg.audio_file }}', '{{ msg.audio_file }}')
    t = t.replace('/static/voice_recordings/{{ p.audio_file }}', '{{ p.audio_file }}')
    t = t.replace('/static/video_recordings/{{ p.video_file }}', '{{ p.video_file }}')
    t = t.replace('/static/department_photos/{{ p.filename }}', '{{ p.filename }}')

    if t != before:
        p.write_text(t, encoding="utf-8")
        print("[5/6] OK - " + tp)
    else:
        print("[5/6] SKIP - " + tp + " (no changes needed)")

print("")
print("========================================")
print("SETUP COMPLETE")
print("========================================")
print("Next: restart app (python app.py)")