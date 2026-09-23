# database.py - PostgreSQL version for FastAfya
import os
import ssl
import pg8000.native
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from password_utils import hash_password, verify_password

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


def _parse_neon_url(url):
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    kwargs = {
        "user": parsed.username,
        "password": parsed.password,
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/"),
    }
    sslmode = params.get("sslmode", ["require"])[0]
    if sslmode in ("require", "verify-ca", "verify-full"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
    return kwargs


class PGCursor:
    def __init__(self, native_conn):
        self._conn = native_conn
        self._lastrowid = None
        self._results = []
        self._index = 0

    def execute(self, sql, params=None):
        if params is not None and "?" in sql:
            parts = sql.split("?")
            new_sql = parts[0]
            named = {}
            for i in range(1, len(parts)):
                key = "p" + str(i)
                new_sql += ":" + key + parts[i]
                named[key] = params[i - 1]
            sql = new_sql
            params = named
        elif params is not None:
            params = None

        stripped = sql.strip().rstrip(";")
        upper = stripped.upper()
        is_insert = upper.startswith("INSERT")
        has_returning = "RETURNING" in upper
        if is_insert and not has_returning:
            stripped = stripped + " RETURNING id"

        if params:
            self._results = self._conn.run(stripped, **params)
        else:
            self._results = self._conn.run(stripped)

        if is_insert and not has_returning:
            if self._results:
                row = self._results[0]
                self._lastrowid = row[0] if row else None
            else:
                self._lastrowid = None

        self._index = 0
        return self

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return len(self._results)

    def fetchone(self):
        if self._index < len(self._results):
            row = self._results[self._index]
            self._index += 1
            return row
        return None

    def fetchall(self):
        result = self._results[self._index:]
        self._index = len(self._results)
        return result

    def close(self):
        pass


class PGConnection:
    def __init__(self, native_conn):
        self._conn = native_conn

    def cursor(self):
        return PGCursor(self._conn)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Database:
    def __init__(self, db_path=None):
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set. Check your .env file.")

    def get_connection(self):
        parsed = _parse_neon_url(DATABASE_URL)
        conn = pg8000.native.Connection(
            user=parsed["user"],
            password=parsed["password"],
            host=parsed["host"],
            port=parsed["port"],
            database=parsed["database"],
            ssl_context=parsed.get("ssl_context"),
        )
        return PGConnection(conn)

    def record_failed_login(self, username=None, phone_number=None, ip_address=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO failed_logins (username, phone_number, attempt_time, ip_address) VALUES (?, ?, ?, ?)",
            (username, phone_number, datetime.now().isoformat(), ip_address),
        )
        conn.commit()
        conn.close()

    def get_failed_attempts(self, username=None, phone_number=None, minutes=15):
        conn = self.get_connection()
        cursor = conn.cursor()
        threshold = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        if username:
            cursor.execute(
                "SELECT COUNT(*) FROM failed_logins WHERE username = ? AND attempt_time > ?",
                (username, threshold),
            )
        elif phone_number:
            cursor.execute(
                "SELECT COUNT(*) FROM failed_logins WHERE phone_number = ? AND attempt_time > ?",
                (phone_number, threshold),
            )
        else:
            conn.close()
            return 0
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def clear_failed_attempts(self, username=None, phone_number=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if username:
            cursor.execute("DELETE FROM failed_logins WHERE username = ?", (username,))
        elif phone_number:
            cursor.execute("DELETE FROM failed_logins WHERE phone_number = ?", (phone_number,))
        conn.commit()
        conn.close()

    def add_audit_log(self, user_type, user_id, action, details=None, ip_address=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO audit_logs (user_type, user_id, action, details, ip_address, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (user_type, user_id, action, details, ip_address, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

    def get_all_patients(self, hospital_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if hospital_id is not None:
            cursor.execute(
                """SELECT id, patient_id, full_name, phone_number, location, arv_regimen,
                          medication_time, registration_date, status
                   FROM patients
                   WHERE status = 'active' AND hospital_id = ?
                   ORDER BY id DESC""",
                (hospital_id,),
            )
        else:
            cursor.execute(
                """SELECT id, patient_id, full_name, phone_number, location, arv_regimen,
                          medication_time, registration_date, status
                   FROM patients
                   WHERE status = 'active'
                   ORDER BY id DESC"""
            )
        patients = cursor.fetchall()
        conn.close()
        return patients

    def get_patient_by_id(self, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, patient_id, full_name, phone_number, password_hash, location,
                      arv_regimen, medication_time, registration_date, status, hospital_id
               FROM patients WHERE patient_id = ?""",
            (patient_id,),
        )
        patient = cursor.fetchone()
        conn.close()
        return patient

    def authenticate_patient(self, patient_id, password):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, patient_id, full_name, phone_number, password_hash, location,
                      arv_regimen, medication_time, registration_date, status, hospital_id
               FROM patients WHERE patient_id = ? AND status = 'active'""",
            (patient_id,),
        )
        patient = cursor.fetchone()
        conn.close()
        if patient and verify_password(password, patient[4]):
            return patient
        return None

    def register_patient(self, patient_id, full_name, phone_number, password, location,
                         arv_regimen, medication_time, hospital_id=None,
                         registration_source="hospital"):
        conn = self.get_connection()
        cursor = conn.cursor()
        password_hash = hash_password(password)
        cursor.execute(
            """INSERT INTO patients
               (patient_id, full_name, phone_number, password_hash, location,
                arv_regimen, medication_time, registration_date, hospital_id, registration_source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (patient_id, full_name, phone_number, password_hash, location,
             arv_regimen, medication_time, datetime.now().isoformat(),
             hospital_id, registration_source),
        )
        conn.commit()
        conn.close()

    def update_patient_location(self, patient_id, new_location):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE patients SET location = ? WHERE patient_id = ?", (new_location, patient_id))
        conn.commit()
        conn.close()

    def update_patient_medication_time(self, patient_id, new_time, updated_by="doctor"):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE patients SET medication_time = ? WHERE patient_id = ?", (new_time, patient_id))
        conn.commit()
        conn.close()

    def get_all_hospitals(self, active_only=True):
        conn = self.get_connection()
        cursor = conn.cursor()
        if active_only:
            cursor.execute(
                "SELECT id, name, village, county, sub_county, phone, address FROM hospitals WHERE is_active = 1 ORDER BY name"
            )
        else:
            cursor.execute("SELECT id, name, village, county, sub_county, phone, address FROM hospitals ORDER BY name")
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_hospital_by_id(self, hospital_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, name, village, latitude, longitude, level, phone, address,
                      opening_hours, username, county, sub_county, contact_person,
                      contact_email, is_active, created_at
               FROM hospitals WHERE id = ?""",
            (hospital_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return row

    def get_hospital_by_username(self, username):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, name, village, latitude, longitude, level, phone, address,
                      opening_hours, username, password_hash, county, sub_county,
                      contact_person, contact_email, is_active, created_at
               FROM hospitals WHERE username = ? AND is_active = 1""",
            (username,),
        )
        row = cursor.fetchone()
        conn.close()
        return row

    def authenticate_hospital(self, username, password):
        hospital = self.get_hospital_by_username(username)
        if not hospital:
            return None
        stored_hash = hospital[10]
        if verify_password(password, stored_hash):
            return hospital
        return None

    def register_hospital(self, name, village, county, sub_county, address,
                          phone, contact_person, contact_email, username, password,
                          latitude=0.0, longitude=0.0, level=3, opening_hours="24/7"):
        conn = self.get_connection()
        cursor = conn.cursor()
        password_hash = hash_password(password)
        cursor.execute(
            """INSERT INTO hospitals
               (name, village, latitude, longitude, level, phone, address, opening_hours,
                username, password_hash, county, sub_county, contact_person,
                contact_email, is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (name, village, latitude, longitude, level, phone, address, opening_hours,
             username, password_hash, county, sub_county, contact_person,
             contact_email, datetime.now().isoformat()),
        )
        hospital_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return hospital_id

    def save_message_with_parent_and_reply(self, patient_id, direction, msg_type, content,
                                           language, risk_level, symptoms, response,
                                           parent_id=None, audio_file=None, reply_to_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if msg_type not in ("sms", "voice", "ussd", "video"):
            msg_type = "sms"
        cursor.execute(
            """INSERT INTO messages
               (patient_id, direction, type, content, language, risk_level,
                symptoms_detected, response_sent, timestamp, is_emergency,
                audio_file, parent_message_id, reply_to_id, is_delivered)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 0)""",
            (patient_id, direction, msg_type, content, language, risk_level,
             symptoms, response, datetime.now().isoformat(),
             audio_file, parent_id, reply_to_id),
        )
        conn.commit()
        conn.close()

    def send_message_to_patient(self, patient_id, message, provider_name, reply_to_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO messages
               (patient_id, direction, type, content, language, risk_level,
                response_sent, timestamp, reply_to_id, is_delivered)
               VALUES (?, 'incoming', 'sms', ?, 'English', 'none', ?, ?, ?, 0)""",
            (patient_id, message, "Sent by " + provider_name, datetime.now().isoformat(), reply_to_id),
        )
        conn.commit()
        conn.close()
        return True

    def get_patient_messages_with_replies(self, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, patient_id, direction, type, content, language, risk_level,
                      symptoms_detected, response_sent, timestamp, is_read, is_emergency,
                      audio_file, video_file, parent_message_id, reply_to_id,
                      is_read_by_receiver, is_delivered, is_pinned, is_deleted
               FROM messages
               WHERE patient_id = ? AND (is_deleted IS NULL OR is_deleted = 0)
                 AND is_emergency = 0
               ORDER BY timestamp ASC""",
            (patient_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_conversation(self, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, direction, type, content, timestamp, audio_file, video_file,
                      parent_message_id, reply_to_id, is_read_by_receiver, is_delivered
               FROM messages
               WHERE patient_id = ? AND (is_deleted IS NULL OR is_deleted = 0)
                 AND is_emergency = 0
               ORDER BY timestamp ASC""",
            (patient_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        result = []
        for r in rows:
            result.append({
                "id": r[0], "direction": r[1], "type": r[2], "content": r[3],
                "timestamp": r[4], "audio_file": r[5], "video_file": r[6],
                "parent_id": r[7], "reply_to_id": r[8],
                "is_read_by_receiver": r[9] if len(r) > 9 else 0,
                "is_delivered": r[10] if len(r) > 10 else 0,
            })
        return result

    def mark_message_delivered(self, message_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE messages SET is_delivered = 1 WHERE id = ?", (message_id,))
        conn.commit()
        conn.close()

    def mark_message_read(self, message_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE messages SET is_read = 1, is_read_by_receiver = 1 WHERE id = ?", (message_id,))
        conn.commit()
        conn.close()

    def delete_message(self, message_id, patient_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if patient_id:
            cursor.execute("UPDATE messages SET is_deleted = 1 WHERE id = ? AND patient_id = ?", (message_id, patient_id))
        else:
            cursor.execute("UPDATE messages SET is_deleted = 1 WHERE id = ?", (message_id,))
        conn.commit()
        conn.close()

    def pin_message(self, message_id, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE messages SET is_pinned = 1 WHERE id = ? AND patient_id = ?", (message_id, patient_id))
        conn.commit()
        conn.close()

    def unpin_message(self, message_id, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE messages SET is_pinned = 0 WHERE id = ? AND patient_id = ?", (message_id, patient_id))
        conn.commit()
        conn.close()

    def get_messages_with_status(self, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT m.id, m.direction, m.type, m.content, m.timestamp,
                      m.is_delivered, m.is_read_by_receiver, m.is_pinned,
                      m.audio_file, m.video_file, m.reply_to_id,
                      (SELECT content FROM messages WHERE id = m.reply_to_id) as reply_to_content
               FROM messages m
               WHERE m.patient_id = ? AND (m.is_deleted IS NULL OR m.is_deleted = 0)
               ORDER BY m.timestamp ASC""",
            (patient_id,),
        )
        messages = cursor.fetchall()
        cursor.execute(
            """SELECT id, content, timestamp
               FROM messages
               WHERE patient_id = ? AND is_pinned = 1 AND (is_deleted IS NULL OR is_deleted = 0)
               ORDER BY timestamp DESC""",
            (patient_id,),
        )
        pinned = cursor.fetchall()
        conn.close()
        return messages, pinned

    def get_unread_messages(self, hospital_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if hospital_id is not None:
            cursor.execute(
                """SELECT m.id, m.patient_id, m.direction, m.type, m.content, m.language,
                          m.risk_level, m.symptoms_detected, m.response_sent, m.timestamp,
                          m.is_read, m.is_emergency, p.full_name, p.phone_number,
                          m.audio_file, m.video_file
                   FROM messages m
                   JOIN patients p ON m.patient_id = p.patient_id
                   WHERE m.direction = 'incoming' AND m.is_read = 0 AND m.is_emergency = 0
                     AND (m.is_deleted IS NULL OR m.is_deleted = 0)
                     AND p.hospital_id = ?
                   ORDER BY m.timestamp DESC""",
                (hospital_id,),
            )
        else:
            cursor.execute(
                """SELECT m.id, m.patient_id, m.direction, m.type, m.content, m.language,
                          m.risk_level, m.symptoms_detected, m.response_sent, m.timestamp,
                          m.is_read, m.is_emergency, p.full_name, p.phone_number,
                          m.audio_file, m.video_file
                   FROM messages m
                   JOIN patients p ON m.patient_id = p.patient_id
                   WHERE m.direction = 'incoming' AND m.is_read = 0 AND m.is_emergency = 0
                     AND (m.is_deleted IS NULL OR m.is_deleted = 0)
                   ORDER BY m.timestamp DESC"""
            )
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_emergency_alerts(self, hospital_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if hospital_id is not None:
            cursor.execute(
                """SELECT m.id, m.patient_id, m.direction, m.type, m.content, m.language,
                          m.risk_level, m.symptoms_detected, m.response_sent, m.timestamp,
                          m.is_read, m.is_emergency, p.full_name, p.phone_number, p.location,
                          m.audio_file, m.video_file
                   FROM messages m
                   JOIN patients p ON m.patient_id = p.patient_id
                   WHERE m.is_emergency = 1 AND m.direction = 'incoming'
                     AND (m.is_deleted IS NULL OR m.is_deleted = 0)
                     AND p.hospital_id = ?
                   ORDER BY m.timestamp DESC""",
                (hospital_id,),
            )
        else:
            cursor.execute(
                """SELECT m.id, m.patient_id, m.direction, m.type, m.content, m.language,
                          m.risk_level, m.symptoms_detected, m.response_sent, m.timestamp,
                          m.is_read, m.is_emergency, p.full_name, p.phone_number, p.location,
                          m.audio_file, m.video_file
                   FROM messages m
                   JOIN patients p ON m.patient_id = p.patient_id
                   WHERE m.is_emergency = 1 AND m.direction = 'incoming'
                     AND (m.is_deleted IS NULL OR m.is_deleted = 0)
                   ORDER BY m.timestamp DESC"""
            )
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_all_messages_for_doctor_with_replies(self, hospital_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if hospital_id is not None:
            cursor.execute(
                """SELECT m.id, m.patient_id, m.direction, m.type, m.content, m.language,
                          m.risk_level, m.symptoms_detected, m.response_sent, m.timestamp,
                          m.is_read, m.is_emergency, p.full_name, p.phone_number, p.location,
                          m.audio_file, m.video_file, m.parent_message_id, m.reply_to_id
                   FROM messages m
                   JOIN patients p ON m.patient_id = p.patient_id
                   WHERE (m.direction = 'incoming' OR m.direction = 'outgoing')
                     AND (m.is_deleted IS NULL OR m.is_deleted = 0)
                     AND p.hospital_id = ?
                   ORDER BY m.timestamp DESC LIMIT 100""",
                (hospital_id,),
            )
        else:
            cursor.execute(
                """SELECT m.id, m.patient_id, m.direction, m.type, m.content, m.language,
                          m.risk_level, m.symptoms_detected, m.response_sent, m.timestamp,
                          m.is_read, m.is_emergency, p.full_name, p.phone_number, p.location,
                          m.audio_file, m.video_file, m.parent_message_id, m.reply_to_id
                   FROM messages m
                   JOIN patients p ON m.patient_id = p.patient_id
                   WHERE (m.direction = 'incoming' OR m.direction = 'outgoing')
                     AND (m.is_deleted IS NULL OR m.is_deleted = 0)
                   ORDER BY m.timestamp DESC LIMIT 100"""
            )
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_chat_list_for_doctor(self, hospital_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if hospital_id is not None:
            cursor.execute(
                """SELECT p.patient_id, p.full_name, p.phone_number, p.location,
                          (SELECT content FROM messages WHERE patient_id = p.patient_id
                             AND is_emergency = 0 AND (is_deleted IS NULL OR is_deleted = 0)
                             ORDER BY timestamp DESC LIMIT 1) as last_message,
                          (SELECT timestamp FROM messages WHERE patient_id = p.patient_id
                             AND is_emergency = 0 AND (is_deleted IS NULL OR is_deleted = 0)
                             ORDER BY timestamp DESC LIMIT 1) as last_time,
                          (SELECT COUNT(*) FROM messages WHERE patient_id = p.patient_id
                             AND direction = 'incoming' AND is_read = 0 AND is_emergency = 0
                             AND (is_deleted IS NULL OR is_deleted = 0)) as unread_count
                   FROM patients p
                   WHERE p.status = 'active' AND p.hospital_id = ?
                   ORDER BY last_time DESC NULLS LAST""",
                (hospital_id,),
            )
        else:
            cursor.execute(
                """SELECT p.patient_id, p.full_name, p.phone_number, p.location,
                          (SELECT content FROM messages WHERE patient_id = p.patient_id
                             AND is_emergency = 0 AND (is_deleted IS NULL OR is_deleted = 0)
                             ORDER BY timestamp DESC LIMIT 1) as last_message,
                          (SELECT timestamp FROM messages WHERE patient_id = p.patient_id
                             AND is_emergency = 0 AND (is_deleted IS NULL OR is_deleted = 0)
                             ORDER BY timestamp DESC LIMIT 1) as last_time,
                          (SELECT COUNT(*) FROM messages WHERE patient_id = p.patient_id
                             AND direction = 'incoming' AND is_read = 0 AND is_emergency = 0
                             AND (is_deleted IS NULL OR is_deleted = 0)) as unread_count
                   FROM patients p
                   WHERE p.status = 'active'
                   ORDER BY last_time DESC NULLS LAST"""
            )
        rows = cursor.fetchall()
        conn.close()
        result = []
        for r in rows:
            result.append({
                "patient_id": r[0], "patient_name": r[1], "phone": r[2], "location": r[3],
                "last_message": r[4] if r[4] else "No messages yet",
                "last_time": r[5],
                "unread_count": r[6] if r[6] else 0,
            })
        return result

    def get_all_villages(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM villages ORDER BY name")
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]

    def get_nearest_hospital(self, village_name):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT h.name, h.village, h.level, h.phone, h.address, h.opening_hours,
                      hd.distance_km, hd.travel_time_minutes, hd.directions
               FROM hospital_distances hd
               JOIN hospitals h ON h.name = hd.hospital_name
               WHERE hd.village_name = ? LIMIT 1""",
            (village_name,),
        )
        r = cursor.fetchone()
        conn.close()
        if r:
            return {
                "name": r[0], "village": r[1], "level": r[2], "phone": r[3],
                "address": r[4], "opening_hours": r[5], "distance_km": r[6],
                "travel_time_minutes": r[7], "directions": r[8],
            }
        return None

    def get_adherence_stats(self, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM adherence WHERE patient_id = ? AND dose_taken = 1", (patient_id,))
        taken = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM adherence WHERE patient_id = ?", (patient_id,))
        total = cursor.fetchone()[0]
        conn.close()
        return (taken, total) if total > 0 else (0, 0)

    def add_adherence_record(self, patient_id, dose_taken=1):
        conn = self.get_connection()
        cursor = conn.cursor()
        today = datetime.now().date().isoformat()
        cursor.execute("SELECT id FROM adherence WHERE patient_id = ? AND date = ?", (patient_id, today))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO adherence (patient_id, date, dose_taken) VALUES (?, ?, ?)",
                (patient_id, today, dose_taken),
            )
            conn.commit()
        conn.close()

    def add_emergency_contact(self, patient_id, name, phone_number, relationship, is_primary=0, shared_with_doctor=0):
        conn = self.get_connection()
        cursor = conn.cursor()
        if is_primary:
            cursor.execute("UPDATE emergency_contacts SET is_primary = 0 WHERE patient_id = ?", (patient_id,))
        cursor.execute(
            """INSERT INTO emergency_contacts
               (patient_id, name, phone_number, relationship, is_primary, shared_with_doctor)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (patient_id, name, phone_number, relationship, is_primary, shared_with_doctor),
        )
        conn.commit()
        conn.close()

    def get_emergency_contacts(self, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, name, phone_number, relationship, is_primary, shared_with_doctor
               FROM emergency_contacts WHERE patient_id = ?
               ORDER BY is_primary DESC, name ASC""",
            (patient_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "name": r[1], "phone_number": r[2], "relationship": r[3],
             "is_primary": r[4], "shared_with_doctor": r[5] if len(r) > 5 else 0}
            for r in rows
        ]

    def delete_emergency_contact(self, contact_id, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM emergency_contacts WHERE id = ? AND patient_id = ?", (contact_id, patient_id))
        conn.commit()
        conn.close()

    def toggle_share_contact(self, contact_id, patient_id, shared_with_doctor):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE emergency_contacts SET shared_with_doctor = ? WHERE id = ? AND patient_id = ?",
            (shared_with_doctor, contact_id, patient_id),
        )
        conn.commit()
        conn.close()

    def get_shared_emergency_contacts(self, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, name, phone_number, relationship
               FROM emergency_contacts WHERE patient_id = ? AND shared_with_doctor = 1
               ORDER BY is_primary DESC""",
            (patient_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "name": r[1], "phone_number": r[2], "relationship": r[3]}
            for r in rows
        ]

    def create_emergency(self, patient_id, patient_name, message, preference, lat=None, lng=None, address=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO emergencies
               (patient_id, patient_name, emergency_message, communication_preference,
                priority_level, location_lat, location_lng, location_address, timestamp, status)
               VALUES (?, ?, ?, ?, 'high', ?, ?, ?, ?, 'active')""",
            (patient_id, patient_name, message, preference, lat, lng, address, datetime.now().isoformat()),
        )
        emergency_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return emergency_id

    def get_active_emergencies(self, hospital_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if hospital_id is not None:
            cursor.execute(
                """SELECT e.id, e.patient_id, e.patient_name, e.emergency_message,
                          e.communication_preference, e.priority_level, e.location_lat,
                          e.location_lng, e.location_address, e.timestamp, e.status,
                          e.doctor_response_timestamp
                   FROM emergencies e
                   JOIN patients p ON e.patient_id = p.patient_id
                   WHERE e.status = 'active' AND p.hospital_id = ?
                   ORDER BY e.timestamp DESC""",
                (hospital_id,),
            )
        else:
            cursor.execute(
                """SELECT id, patient_id, patient_name, emergency_message,
                          communication_preference, priority_level, location_lat,
                          location_lng, location_address, timestamp, status,
                          doctor_response_timestamp
                   FROM emergencies WHERE status = 'active'
                   ORDER BY timestamp DESC"""
            )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "patient_id": r[1], "patient_name": r[2], "emergency_message": r[3],
             "communication_preference": r[4], "priority_level": r[5], "location_lat": r[6],
             "location_lng": r[7], "location_address": r[8], "timestamp": r[9],
             "status": r[10], "doctor_response_timestamp": r[11]}
            for r in rows
        ]

    def get_emergency_by_id(self, emergency_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, patient_id, patient_name, emergency_message,
                      communication_preference, priority_level, location_lat, location_lng,
                      location_address, timestamp, status, doctor_response_timestamp,
                      resolved_timestamp, escalation_sent
               FROM emergencies WHERE id = ?""",
            (emergency_id,),
        )
        r = cursor.fetchone()
        conn.close()
        if r:
            return {
                "id": r[0], "patient_id": r[1], "patient_name": r[2], "emergency_message": r[3],
                "communication_preference": r[4], "priority_level": r[5], "location_lat": r[6],
                "location_lng": r[7], "location_address": r[8], "timestamp": r[9],
                "status": r[10], "doctor_response_timestamp": r[11],
                "resolved_timestamp": r[12], "escalation_sent": r[13] if len(r) > 13 else 0,
            }
        return None

    def mark_emergency_resolved(self, emergency_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE emergencies SET status = 'resolved', resolved_timestamp = ? WHERE id = ?",
            (datetime.now().isoformat(), emergency_id),
        )
        conn.commit()
        conn.close()

    def record_doctor_emergency_response(self, emergency_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE emergencies SET doctor_response_timestamp = ? WHERE id = ? AND doctor_response_timestamp IS NULL",
            (datetime.now().isoformat(), emergency_id),
        )
        conn.commit()
        conn.close()

    def get_emergency_response_time(self, emergency_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp, doctor_response_timestamp FROM emergencies WHERE id = ?", (emergency_id,))
        r = cursor.fetchone()
        conn.close()
        if r and r[1]:
            sent = datetime.fromisoformat(r[0])
            responded = datetime.fromisoformat(r[1])
            return (responded - sent).total_seconds() / 60
        return None

    def get_unresponded_emergencies_older_than(self, minutes=5):
        conn = self.get_connection()
        cursor = conn.cursor()
        threshold = (datetime.now() - timedelta(minutes=minutes)).isoformat()
        cursor.execute(
            """SELECT id, patient_id, patient_name, timestamp, escalation_sent
               FROM emergencies WHERE status = 'active'
                 AND doctor_response_timestamp IS NULL AND timestamp < ?""",
            (threshold,),
        )
        rows = cursor.fetchall()
        conn.close()
        return rows

    def mark_emergency_escalated(self, emergency_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE emergencies SET escalation_sent = 1, escalation_timestamp = ? WHERE id = ?",
            (datetime.now().isoformat(), emergency_id),
        )
        conn.commit()
        conn.close()

    def get_emergency_messages(self, emergency_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, sender_type, message_type, content, audio_file, timestamp, is_read
               FROM emergency_messages WHERE emergency_id = ?
               ORDER BY timestamp ASC""",
            (emergency_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "sender_type": r[1], "message_type": r[2], "content": r[3],
             "audio_file": r[4], "timestamp": r[5], "is_read": r[6]}
            for r in rows
        ]

    def save_emergency_message(self, emergency_id, sender_type, message_type, content, audio_file=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO emergency_messages
               (emergency_id, sender_type, message_type, content, audio_file, timestamp, is_read)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (emergency_id, sender_type, message_type, content, audio_file, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

    def save_emergency_location(self, emergency_id, lat, lng, accuracy=None, speed=None, heading=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO emergency_locations
               (emergency_id, latitude, longitude, accuracy, speed, heading, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (emergency_id, lat, lng, accuracy, speed, heading, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

    def get_emergency_locations(self, emergency_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT latitude, longitude, accuracy, speed, heading, timestamp
               FROM emergency_locations WHERE emergency_id = ?
               ORDER BY timestamp ASC""",
            (emergency_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"lat": r[0], "lng": r[1], "accuracy": r[2], "speed": r[3],
             "heading": r[4], "timestamp": r[5]}
            for r in rows
        ]

    def get_latest_emergency_location(self, emergency_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT latitude, longitude, accuracy, speed, heading, timestamp
               FROM emergency_locations WHERE emergency_id = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (emergency_id,),
        )
        r = cursor.fetchone()
        conn.close()
        if r:
            return {"lat": r[0], "lng": r[1], "accuracy": r[2], "speed": r[3],
                    "heading": r[4], "timestamp": r[5]}
        return None

    def create_refill_request(self, patient_id, patient_name, medication_name, dosage,
                              last_dose_date, preferred_pickup_date, preferred_pickup_time):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO refill_requests
               (patient_id, patient_name, medication_name, dosage, last_dose_date,
                preferred_pickup_date, preferred_pickup_time, request_date, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (patient_id, patient_name, medication_name, dosage, last_dose_date,
             preferred_pickup_date, preferred_pickup_time, datetime.now().isoformat()),
        )
        request_id = cursor.lastrowid
        conn.commit()
        conn.close()
        days_left = None
        if last_dose_date:
            try:
                last_dose = datetime.strptime(last_dose_date, "%Y-%m-%d")
                days_since = (datetime.now() - last_dose).days
                days_left = max(0, 30 - days_since)
            except Exception:
                pass
        return request_id, days_left

    def get_pending_refill_requests(self, hospital_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if hospital_id is not None:
            cursor.execute(
                """SELECT r.id, r.patient_id, r.patient_name, r.medication_name, r.dosage,
                          r.last_dose_date, r.preferred_pickup_date, r.preferred_pickup_time,
                          r.request_date, r.status, r.cancelled_by_patient
                   FROM refill_requests r
                   JOIN patients p ON r.patient_id = p.patient_id
                   WHERE r.status = 'pending' AND r.cancelled_by_patient = 0
                     AND p.hospital_id = ?
                   ORDER BY r.request_date DESC""",
                (hospital_id,),
            )
        else:
            cursor.execute(
                """SELECT id, patient_id, patient_name, medication_name, dosage,
                          last_dose_date, preferred_pickup_date, preferred_pickup_time,
                          request_date, status, cancelled_by_patient
                   FROM refill_requests
                   WHERE status = 'pending' AND cancelled_by_patient = 0
                   ORDER BY request_date DESC"""
            )
        rows = cursor.fetchall()
        conn.close()
        result = []
        for r in rows:
            days_since = None
            if r[5]:
                try:
                    last_date = datetime.strptime(r[5], "%Y-%m-%d")
                    days_since = (datetime.now() - last_date).days
                except Exception:
                    pass
            result.append({
                "id": r[0], "patient_id": r[1], "patient_name": r[2],
                "medication_name": r[3], "dosage": r[4], "last_dose_date": r[5],
                "preferred_pickup_date": r[6], "preferred_pickup_time": r[7],
                "request_date": r[8], "status": r[9],
                "days_since_last_dose": days_since,
                "cancelled_by_patient": r[10],
            })
        return result

    def get_all_refill_requests_with_filters(self, status_filter=None, search_term=None, hospital_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        query = """SELECT r.id, r.patient_id, r.patient_name, r.medication_name, r.dosage,
                          r.last_dose_date, r.preferred_pickup_date, r.preferred_pickup_time,
                          r.request_date, r.status, r.approved_date, r.approved_pickup_date,
                          r.approved_pickup_time, r.doctor_notes, r.new_medication_time
                   FROM refill_requests r"""
        params = []
        where = []
        if hospital_id is not None:
            query += " JOIN patients p ON r.patient_id = p.patient_id "
            where.append("p.hospital_id = ?")
            params.append(hospital_id)
        if status_filter and status_filter != "all" and status_filter != "pending":
            where.append("r.status = ?")
            params.append(status_filter)
        elif status_filter == "pending":
            where.append("r.status = 'pending' AND r.cancelled_by_patient = 0")
        if search_term:
            where.append("(r.patient_name LIKE ? OR r.medication_name LIKE ?)")
            params.append("%" + search_term + "%")
            params.append("%" + search_term + "%")
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY r.request_date DESC LIMIT 50"
        cursor.execute(query, tuple(params) if params else None)
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "patient_id": r[1], "patient_name": r[2], "medication_name": r[3],
             "dosage": r[4], "last_dose_date": r[5], "preferred_pickup_date": r[6],
             "preferred_pickup_time": r[7], "request_date": r[8], "status": r[9],
             "approved_date": r[10], "approved_pickup_date": r[11],
             "approved_pickup_time": r[12], "doctor_notes": r[13], "new_medication_time": r[14]}
            for r in rows
        ]

    def approve_refill_request(self, request_id, approved_pickup_date, approved_pickup_time,
                               doctor_notes, new_medication_time=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE refill_requests
               SET status = 'approved', approved_date = ?, approved_pickup_date = ?,
                   approved_pickup_time = ?, doctor_notes = ?, new_medication_time = ?
               WHERE id = ?""",
            (datetime.now().isoformat(), approved_pickup_date, approved_pickup_time,
             doctor_notes, new_medication_time, request_id),
        )
        conn.commit()
        conn.close()

    def deny_refill_request(self, request_id, doctor_notes):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE refill_requests SET status = 'denied', doctor_notes = ? WHERE id = ?",
            (doctor_notes, request_id),
        )
        conn.commit()
        conn.close()

    def cancel_refill_request(self, request_id, reason=""):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE refill_requests SET status = 'cancelled', cancelled_by_patient = 1, cancel_reason = ? WHERE id = ?",
            (reason, request_id),
        )
        conn.commit()
        conn.close()

    def get_refill_requests_for_patient(self, patient_id, status_filter=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if status_filter and status_filter != "all":
            cursor.execute(
                """SELECT id, medication_name, dosage, last_dose_date, preferred_pickup_date,
                          preferred_pickup_time, request_date, status, approved_date,
                          approved_pickup_date, approved_pickup_time, doctor_notes,
                          new_medication_time, cancelled_by_patient, cancel_reason
                   FROM refill_requests WHERE patient_id = ? AND status = ?
                   ORDER BY request_date DESC LIMIT 20""",
                (patient_id, status_filter),
            )
        else:
            cursor.execute(
                """SELECT id, medication_name, dosage, last_dose_date, preferred_pickup_date,
                          preferred_pickup_time, request_date, status, approved_date,
                          approved_pickup_date, approved_pickup_time, doctor_notes,
                          new_medication_time, cancelled_by_patient, cancel_reason
                   FROM refill_requests WHERE patient_id = ?
                   ORDER BY request_date DESC LIMIT 20""",
                (patient_id,),
            )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "medication_name": r[1], "dosage": r[2], "last_dose_date": r[3],
             "preferred_pickup_date": r[4], "preferred_pickup_time": r[5], "request_date": r[6],
             "status": r[7], "approved_date": r[8], "approved_pickup_date": r[9],
             "approved_pickup_time": r[10], "doctor_notes": r[11], "new_medication_time": r[12],
             "cancelled_by_patient": r[13] if len(r) > 13 else 0,
             "cancel_reason": r[14] if len(r) > 14 else None}
            for r in rows
        ]

    def create_treatment(self, patient_id, doctor_name, diagnosis, notes,
                         next_appointment_date, next_appointment_reason):
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            """INSERT INTO treatments
               (patient_id, doctor_name, treatment_date, diagnosis, notes,
                next_appointment_date, next_appointment_reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (patient_id, doctor_name, now, diagnosis, notes,
             next_appointment_date, next_appointment_reason, now),
        )
        treatment_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return treatment_id

    def add_prescribed_medication(self, treatment_id, medication_name, dosage_amount, dosage_unit,
                                  times_per_day, schedule_times, duration_days, instructions):
        import json
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO prescribed_medications
               (treatment_id, medication_name, dosage_amount, dosage_unit, times_per_day,
                schedule_times, duration_days, instructions, created_at, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (treatment_id, medication_name, dosage_amount, dosage_unit, times_per_day,
             json.dumps(schedule_times), duration_days, instructions, datetime.now().isoformat()),
        )
        med_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return med_id

    def get_patient_treatments(self, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT t.id, t.patient_id, t.doctor_name, t.treatment_date, t.diagnosis,
                      t.notes, t.next_appointment_date, t.next_appointment_reason,
                      t.status, t.created_at
               FROM treatments t WHERE t.patient_id = ?
               ORDER BY t.treatment_date DESC""",
            (patient_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        result = []
        for r in rows:
            meds = self.get_treatment_medications(r[0])
            result.append({
                "id": r[0], "patient_id": r[1], "doctor_name": r[2], "treatment_date": r[3],
                "diagnosis": r[4], "notes": r[5], "next_appointment_date": r[6],
                "next_appointment_reason": r[7], "status": r[8], "created_at": r[9],
                "medications": meds,
            })
        return result

    def get_treatment_medications(self, treatment_id):
        import json
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, medication_name, dosage_amount, dosage_unit, times_per_day,
                      schedule_times, duration_days, instructions, is_active
               FROM prescribed_medications WHERE treatment_id = ? AND is_active = 1
               ORDER BY id ASC""",
            (treatment_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "medication_name": r[1], "dosage_amount": r[2], "dosage_unit": r[3],
             "times_per_day": r[4],
             "schedule_times": json.loads(r[5]) if r[5] else [],
             "duration_days": r[6], "instructions": r[7], "is_active": r[8]}
            for r in rows
        ]

    def get_active_medications(self, patient_id):
        import json
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT pm.id, pm.medication_name, pm.dosage_amount, pm.dosage_unit,
                      pm.times_per_day, pm.schedule_times, pm.instructions, t.treatment_date
               FROM prescribed_medications pm
               JOIN treatments t ON pm.treatment_id = t.id
               WHERE t.patient_id = ? AND pm.is_active = 1 AND t.status = 'active'
               ORDER BY pm.created_at DESC""",
            (patient_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "medication_name": r[1], "dosage_amount": r[2], "dosage_unit": r[3],
             "times_per_day": r[4],
             "schedule_times": json.loads(r[5]) if r[5] else [],
             "instructions": r[6], "treatment_date": r[7]}
            for r in rows
        ]

    def mark_treatment_completed(self, treatment_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE treatments SET status = 'completed' WHERE id = ?", (treatment_id,))
        conn.commit()
        conn.close()

    def get_all_treatments(self, hospital_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if hospital_id is not None:
            cursor.execute(
                """SELECT t.id, t.patient_id, p.full_name, t.doctor_name, t.treatment_date,
                          t.diagnosis, t.next_appointment_date, t.status
                   FROM treatments t
                   JOIN patients p ON t.patient_id = p.patient_id
                   WHERE p.hospital_id = ?
                   ORDER BY t.treatment_date DESC LIMIT 50""",
                (hospital_id,),
            )
        else:
            cursor.execute(
                """SELECT t.id, t.patient_id, p.full_name, t.doctor_name, t.treatment_date,
                          t.diagnosis, t.next_appointment_date, t.status
                   FROM treatments t
                   JOIN patients p ON t.patient_id = p.patient_id
                   ORDER BY t.treatment_date DESC LIMIT 50"""
            )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "patient_id": r[1], "patient_name": r[2], "doctor_name": r[3],
             "treatment_date": r[4], "diagnosis": r[5], "next_appointment_date": r[6],
             "status": r[7]}
            for r in rows
        ]

    def save_reminder_preference(self, patient_id, custom_audio_message, custom_text_message,
                                 reminder_voice_enabled, reminder_sms_enabled):
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("SELECT id FROM reminder_preferences WHERE patient_id = ?", (patient_id,))
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                """UPDATE reminder_preferences
                   SET custom_audio_message = ?, custom_text_message = ?,
                       reminder_voice_enabled = ?, reminder_sms_enabled = ?, updated_at = ?
                   WHERE patient_id = ?""",
                (custom_audio_message, custom_text_message, reminder_voice_enabled,
                 reminder_sms_enabled, now, patient_id),
            )
        else:
            cursor.execute(
                """INSERT INTO reminder_preferences
                   (patient_id, custom_audio_message, custom_text_message,
                    reminder_voice_enabled, reminder_sms_enabled, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (patient_id, custom_audio_message, custom_text_message,
                 reminder_voice_enabled, reminder_sms_enabled, now, now),
            )
        conn.commit()
        conn.close()

    def get_reminder_preference(self, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reminder_preferences WHERE patient_id = ?", (patient_id,))
        r = cursor.fetchone()
        conn.close()
        if r:
            return {
                "id": r[0], "patient_id": r[1], "custom_audio_message": r[2],
                "custom_text_message": r[3], "reminder_voice_enabled": r[4],
                "reminder_sms_enabled": r[5], "created_at": r[6], "updated_at": r[7],
            }
        return None

    def log_medication_taken(self, patient_id, medication_id, scheduled_time):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE medication_adherence SET taken_at = ?, status = 'taken'
               WHERE patient_id = ? AND medication_id = ? AND scheduled_time = ?""",
            (datetime.now().isoformat(), patient_id, medication_id, scheduled_time),
        )
        conn.commit()
        conn.close()

    def create_adherence_record(self, patient_id, medication_id, scheduled_time):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO medication_adherence
               (patient_id, medication_id, scheduled_time, status, reminder_sent)
               VALUES (?, ?, ?, 'pending', 0)""",
            (patient_id, medication_id, scheduled_time),
        )
        conn.commit()
        conn.close()

    def get_today_adherence(self, patient_id):
        today = datetime.now().date().isoformat()
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT * FROM medication_adherence
               WHERE patient_id = ? AND DATE(CAST(scheduled_time AS TIMESTAMP)) = ?
               ORDER BY scheduled_time ASC""",
            (patient_id, today),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "patient_id": r[1], "medication_id": r[2], "scheduled_time": r[3],
             "taken_at": r[4], "status": r[5], "reminder_sent": r[6], "notes": r[7]}
            for r in rows
        ]

    def create_appointment_alert(self, patient_id, treatment_id, appointment_date):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO appointment_alerts (patient_id, treatment_id, appointment_date, is_active)
               VALUES (?, ?, ?, 1)""",
            (patient_id, treatment_id, appointment_date),
        )
        alert_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return alert_id

    def get_active_appointment_alerts(self, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT a.id, a.patient_id, a.treatment_id, a.appointment_date,
                      a.alert_dismissed, a.dismissed_by, a.dismissed_at,
                      t.doctor_name, t.next_appointment_reason
               FROM appointment_alerts a
               JOIN treatments t ON a.treatment_id = t.id
               WHERE a.patient_id = ? AND a.is_active = 1 AND a.alert_dismissed = 0
               ORDER BY a.appointment_date ASC""",
            (patient_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "patient_id": r[1], "treatment_id": r[2], "appointment_date": r[3],
             "alert_dismissed": r[4], "dismissed_by": r[5], "dismissed_at": r[6],
             "doctor_name": r[7], "reason": r[8]}
            for r in rows
        ]

    def dismiss_appointment_alert(self, alert_id, dismissed_by):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE appointment_alerts
               SET alert_dismissed = 1, dismissed_by = ?, dismissed_at = ?
               WHERE id = ?""",
            (dismissed_by, datetime.now().isoformat(), alert_id),
        )
        conn.commit()
        conn.close()
