# database.py - PostgreSQL version for FastAfya
import os
import ssl
import pg8000.native
import threading
import queue
from cache import get_or_set, invalidate
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from password_utils import hash_password, verify_password

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


_thread_local = threading.local()

# Global connection pool — shared across all threads/requests
_conn_pool = queue.Queue(maxsize=10)
_pool_lock = threading.Lock()
_pool_initialized = False


def _init_pool(pool_size=5):
    """Warm up the pool in parallel — 5 connections take ~3s instead of ~15s."""
    global _pool_initialized
    with _pool_lock:
        if _pool_initialized:
            return
        _pool_initialized = True

    parsed = _parse_neon_url(DATABASE_URL)
    created_conns = []
    errors = []
    lock = threading.Lock()

    def _warm_one():
        try:
            c = pg8000.native.Connection(
                user=parsed["user"],
                password=parsed["password"],
                host=parsed["host"],
                port=parsed["port"],
                database=parsed["database"],
                ssl_context=parsed.get("ssl_context"),
            )
            with lock:
                created_conns.append(c)
        except Exception as e:
            with lock:
                errors.append(str(e))

    # Fire all warm-ups in parallel
    threads = [threading.Thread(target=_warm_one, daemon=True) for _ in range(pool_size)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    for c in created_conns:
        try:
            _conn_pool.put_nowait(c)
        except queue.Full:
            try:
                c.close()
            except Exception:
                pass

    print(f"Connection pool warmed with {len(created_conns)} connections (parallel)")
    if errors:
        print(f"  {len(errors)} warm-up errors (first: {errors[0][:80]})")



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




def _reconnect(old_conn):
    """Rebuild a pg8000.native.Connection from the same DATABASE_URL."""
    parsed = _parse_neon_url(DATABASE_URL)
    return pg8000.native.Connection(
        user=parsed["user"],
        password=parsed["password"],
        host=parsed["host"],
        port=parsed["port"],
        database=parsed["database"],
        ssl_context=parsed.get("ssl_context"),
    )


class PGCursor:
    def __init__(self, native_conn, parent=None):
        self._conn = native_conn
        self._parent = parent
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

        def _run():
            if params:
                return self._conn.run(stripped, **params)
            return self._conn.run(stripped)

        try:
            self._results = _run()
        except Exception as e:
            err = str(e)
            if "prepared statement" in err or "26000" in err or "connection is closed" in err:
                # statement cache lost or connection dropped — reconnect and retry
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = _reconnect(self._conn)
                if self._parent is not None:
                    self._parent._conn = self._conn
                self._results = _run()
            else:
                raise

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
        if self._results is None:
            return 0
        try:
            return len(self._results)
        except TypeError:
            return 0

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
    def __init__(self, native_conn, pooled=False):
        self._conn = native_conn
        self._pooled = pooled

    def cursor(self):
        return PGCursor(self._conn, parent=self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        # If pooled, return connection to the global pool
        if self._pooled:
            try:
                _conn_pool.put_nowait(self._conn)
            except queue.Full:
                try:
                    self._conn.close()
                except Exception:
                    pass
            return
        try:
            self._conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Database:
    def __init__(self, db_path=None):
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set. Check your .env file.")

    def get_connection(self):
        """Return a warm connection from the global pool."""
        if not _pool_initialized:
            _init_pool()
        try:
            conn = _conn_pool.get(timeout=10)
            return PGConnection(conn, pooled=True)
        except queue.Empty:
            # Pool exhausted — create a one-off
            parsed = _parse_neon_url(DATABASE_URL)
            conn = pg8000.native.Connection(
                user=parsed["user"],
                password=parsed["password"],
                host=parsed["host"],
                port=parsed["port"],
                database=parsed["database"],
                ssl_context=parsed.get("ssl_context"),
            )
            return PGConnection(conn, pooled=False)

    def close_all_connections(self):
        """Force-close this thread's connection (used on shutdown)."""
        existing = getattr(_thread_local, "conn", None)
        if existing is not None:
            try:
                existing.close()
            except Exception:
                pass
            _thread_local.conn = None

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
        def _fetch():
            conn = self.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM villages ORDER BY name")
            rows = cursor.fetchall()
            conn.close()
            return [r[0] for r in rows]
        return get_or_set("all_villages", _fetch, ttl_seconds=300)

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


    # ============================================================
    # DEPARTMENTS
    # ============================================================
    def get_hospital_departments(self, hospital_id, active_only=True):
        def _fetch():
            conn = self.get_connection()
            cursor = conn.cursor()
            sql = """SELECT id, name, description, head_doctor, secretary_name, phone,
                            email, consultation_fee, operating_hours, username, is_active
                     FROM departments WHERE hospital_id = ?"""
            if active_only:
                sql += " AND is_active = 1"
            sql += " ORDER BY name"
            cursor.execute(sql, (hospital_id,))
            rows = cursor.fetchall()
            conn.close()
            return [
                {"id": r[0], "name": r[1], "description": r[2], "head_doctor": r[3],
                 "secretary_name": r[4], "phone": r[5], "email": r[6],
                 "consultation_fee": r[7], "operating_hours": r[8],
                 "username": r[9], "is_active": r[10]}
                for r in rows
            ]
        return get_or_set(f"depts_{hospital_id}_{active_only}", _fetch, ttl_seconds=120)

    def get_department_by_id(self, department_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, hospital_id, name, description, head_doctor, secretary_name,
                      phone, email, consultation_fee, operating_hours, username,
                      is_active, created_at
               FROM departments WHERE id = ?""",
            (department_id,),
        )
        r = cursor.fetchone()
        conn.close()
        if r:
            return {
                "id": r[0], "hospital_id": r[1], "name": r[2], "description": r[3],
                "head_doctor": r[4], "secretary_name": r[5], "phone": r[6],
                "email": r[7], "consultation_fee": r[8], "operating_hours": r[9],
                "username": r[10], "is_active": r[11], "created_at": r[12],
            }
        return None

    def get_department_by_username(self, username):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT d.id, d.hospital_id, d.name, d.description, d.head_doctor,
                      d.secretary_name, d.phone, d.email, d.consultation_fee,
                      d.operating_hours, d.username, d.password_hash, d.is_active,
                      h.name, h.county, h.sub_county
               FROM departments d
               JOIN hospitals h ON d.hospital_id = h.id
               WHERE d.username = ? AND d.is_active = 1""",
            (username,),
        )
        r = cursor.fetchone()
        conn.close()
        if r:
            return {
                "id": r[0], "hospital_id": r[1], "name": r[2], "description": r[3],
                "head_doctor": r[4], "secretary_name": r[5], "phone": r[6],
                "email": r[7], "consultation_fee": r[8], "operating_hours": r[9],
                "username": r[10], "password_hash": r[11], "is_active": r[12],
                "hospital_name": r[13], "hospital_county": r[14],
                "hospital_sub_county": r[15],
            }
        return None

    def create_department(self, hospital_id, name, description="", head_doctor="",
                          secretary_name="", phone="", email="", consultation_fee="",
                          operating_hours="24/7", username=None, password=None):
        from password_utils import hash_password
        conn = self.get_connection()
        cursor = conn.cursor()
        pw_hash = hash_password(password) if password else None
        cursor.execute(
            """INSERT INTO departments
               (hospital_id, name, description, head_doctor, secretary_name, phone,
                email, consultation_fee, operating_hours, username, password_hash,
                is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (hospital_id, name, description, head_doctor, secretary_name, phone,
             email, consultation_fee, operating_hours, username, pw_hash,
             datetime.now().isoformat()),
        )
        invalidate('depts_')
        dept_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return dept_id

    def update_department(self, department_id, **kwargs):
        allowed = ["name", "description", "head_doctor", "secretary_name", "phone",
                   "email", "consultation_fee", "operating_hours", "username",
                   "is_active"]
        fields = []
        params = []
        for k, v in kwargs.items():
            if k in allowed and v is not None:
                fields.append(k + " = ?")
                params.append(v)
        if kwargs.get("password"):
            from password_utils import hash_password
            fields.append("password_hash = ?")
            params.append(hash_password(kwargs["password"]))
        if not fields:
            return False
        params.append(department_id)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE departments SET " + ", ".join(fields) + " WHERE id = ?",
            tuple(params),
        )
        invalidate('depts_')
        conn.commit()
        conn.close()
        return True

    def delete_department(self, department_id, hospital_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if hospital_id:
            cursor.execute(
                "DELETE FROM departments WHERE id = ? AND hospital_id = ?",
                (department_id, hospital_id),
            )
        else:
            cursor.execute("DELETE FROM departments WHERE id = ?", (department_id,))
        conn.commit()
        conn.close()

    def authenticate_department(self, username, password):
        from password_utils import verify_password
        dept = self.get_department_by_username(username)
        if not dept:
            return None
        if not dept.get("password_hash"):
            return None
        if verify_password(password, dept["password_hash"]):
            return dept
        return None

    # ============================================================
    # DEPARTMENT PHOTOS
    # ============================================================
    def add_department_photo(self, department_id, filename, caption=""):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO department_photos (department_id, filename, caption, created_at)
               VALUES (?, ?, ?, ?)""",
            (department_id, filename, caption, datetime.now().isoformat()),
        )
        pid = cursor.lastrowid
        conn.commit()
        conn.close()
        return pid

    def get_department_photos(self, department_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, filename, caption, created_at
               FROM department_photos WHERE department_id = ?
               ORDER BY id DESC""",
            (department_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "filename": r[1], "caption": r[2], "created_at": r[3]}
            for r in rows
        ]

    def delete_department_photo(self, photo_id, department_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM department_photos WHERE id = ? AND department_id = ?",
            (photo_id, department_id),
        )
        conn.commit()
        conn.close()

    # ============================================================
    # DEPARTMENT SERVICES
    # ============================================================
    def add_department_service(self, department_id, name, description=""):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO department_services (department_id, name, description, created_at)
               VALUES (?, ?, ?, ?)""",
            (department_id, name, description, datetime.now().isoformat()),
        )
        sid = cursor.lastrowid
        conn.commit()
        conn.close()
        return sid

    def get_department_services(self, department_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, name, description FROM department_services
               WHERE department_id = ? ORDER BY name""",
            (department_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"id": r[0], "name": r[1], "description": r[2]} for r in rows]

    def delete_department_service(self, service_id, department_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM department_services WHERE id = ? AND department_id = ?",
            (service_id, department_id),
        )
        conn.commit()
        conn.close()

    # ============================================================
    # TRIAGE ENGINE
    # ============================================================
    def get_triage_rules(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, keywords, department_name, priority, is_emergency
               FROM triage_rules ORDER BY priority DESC"""
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {"id": r[0], "keywords": r[1], "department_name": r[2],
             "priority": r[3], "is_emergency": r[4]}
            for r in rows
        ]

    def suggest_department(self, symptom_text):
        if not symptom_text:
            return None
        text = symptom_text.lower()
        best = None
        for rule in self.get_triage_rules():
            kws = [k.strip().lower() for k in rule["keywords"].split(",") if k.strip()]
            matched = [k for k in kws if k in text]
            if matched:
                score = rule["priority"] + len(matched) * 5
                if rule["is_emergency"]:
                    score += 50
                if best is None or score > best["score"]:
                    best = {
                        "department_name": rule["department_name"],
                        "is_emergency": bool(rule["is_emergency"]),
                        "matched_keywords": matched,
                        "score": score,
                    }
        return best

    # ============================================================
    # SUPER ADMIN METHODS
    # ============================================================
    def create_super_admin(self, username, password, full_name, hospital_id,
                            email="", phone=""):
        from password_utils import hash_password
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO super_admins
               (username, password_hash, full_name, hospital_id, email, phone,
                is_active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
            (username, hash_password(password), full_name, hospital_id,
             email, phone, datetime.now().isoformat()),
        )
        sid = cursor.lastrowid
        conn.commit()
        conn.close()
        return sid

    def get_super_admin_by_username(self, username):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, username, password_hash, full_name, hospital_id,
                      email, phone, is_active, last_login, created_at
               FROM super_admins WHERE username = ? AND is_active = 1""",
            (username,),
        )
        r = cursor.fetchone()
        conn.close()
        if r:
            return {
                "id": r[0], "username": r[1], "password_hash": r[2],
                "full_name": r[3], "hospital_id": r[4], "email": r[5],
                "phone": r[6], "is_active": r[7], "last_login": r[8],
                "created_at": r[9],
            }
        return None

    def update_super_admin_hospital(self, super_admin_id, hospital_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE super_admins SET hospital_id = ? WHERE id = ?",
            (hospital_id, super_admin_id),
        )
        conn.commit()
        conn.close()



    # ============================================================
    # APPOINTMENTS
    # ============================================================
    def create_appointment(self, patient_id, department_id, appointment_date,
                            time_slot="", purpose="", symptoms=""):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO appointments
               (patient_id, department_id, appointment_date, time_slot, purpose,
                symptoms, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (patient_id, department_id, appointment_date, time_slot, purpose,
             symptoms, datetime.now().isoformat()),
        )
        appt_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return appt_id

    def get_patient_appointments(self, patient_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT a.id, a.department_id, d.name, a.appointment_date,
                      a.time_slot, a.purpose, a.symptoms, a.status, a.created_at
               FROM appointments a
               JOIN departments d ON a.department_id = d.id
               WHERE a.patient_id = ?
               ORDER BY a.appointment_date DESC""",
            (patient_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [{
            "id": r[0], "department_id": r[1], "department_name": r[2],
            "appointment_date": r[3], "time_slot": r[4], "purpose": r[5],
            "symptoms": r[6], "status": r[7], "created_at": r[8],
        } for r in rows]

    def get_department_appointments(self, department_id, status_filter=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        base = """SELECT a.id, a.patient_id, p.full_name, a.appointment_date,
                         a.time_slot, a.purpose, a.symptoms, a.status, a.created_at
                  FROM appointments a
                  JOIN patients p ON a.patient_id = p.patient_id
                  WHERE a.department_id = ?"""
        params = [department_id]
        if status_filter:
            base += " AND a.status = ?"
            params.append(status_filter)
        base += " ORDER BY a.appointment_date DESC"
        cursor.execute(base, tuple(params))
        rows = cursor.fetchall()
        conn.close()
        return [{
            "id": r[0], "patient_id": r[1], "patient_name": r[2],
            "appointment_date": r[3], "time_slot": r[4], "purpose": r[5],
            "symptoms": r[6], "status": r[7], "created_at": r[8],
        } for r in rows]

    def update_appointment_status(self, appt_id, status, department_id=None):
        conn = self.get_connection()
        cursor = conn.cursor()
        if department_id:
            cursor.execute(
                "UPDATE appointments SET status = ?, updated_at = ? WHERE id = ? AND department_id = ?",
                (status, datetime.now().isoformat(), appt_id, department_id),
            )
        else:
            cursor.execute(
                "UPDATE appointments SET status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.now().isoformat(), appt_id),
            )
        conn.commit()
        conn.close()

    # ============================================================
    # DEPARTMENT ENQUIRIES
    # ============================================================
    def get_department_threads(self, department_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT m.patient_id, p.full_name,
                      (SELECT content FROM messages WHERE patient_id = m.patient_id AND department_id = ? ORDER BY timestamp DESC LIMIT 1),
                      (SELECT timestamp FROM messages WHERE patient_id = m.patient_id AND department_id = ? ORDER BY timestamp DESC LIMIT 1),
                      (SELECT COUNT(*) FROM messages WHERE patient_id = m.patient_id AND department_id = ? AND direction = 'outgoing' AND is_read = 0)
               FROM messages m
               JOIN patients p ON m.patient_id = p.patient_id
               WHERE m.department_id = ? AND (m.is_deleted IS NULL OR m.is_deleted = 0)
               GROUP BY m.patient_id, p.full_name
               ORDER BY MAX(m.timestamp) DESC""",
            (department_id, department_id, department_id, department_id),
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"patient_id": r[0], "patient_name": r[1], "last_message": r[2] or "",
                 "last_time": r[3], "unread": r[4] or 0} for r in rows]

    def get_department_patient_thread(self, patient_id, department_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, direction, type, content, timestamp, audio_file, video_file, is_read
               FROM messages
               WHERE patient_id = ? AND department_id = ? AND (is_deleted IS NULL OR is_deleted = 0)
               ORDER BY timestamp ASC""",
            (patient_id, department_id),
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"id": r[0], "direction": r[1], "type": r[2], "content": r[3],
                 "timestamp": r[4], "audio_file": r[5], "video_file": r[6],
                 "is_read": r[7]} for r in rows]

    def send_department_message(self, patient_id, department_id, direction,
                                 content, audio_file=None, video_file=None, msg_type="sms"):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO messages
               (patient_id, department_id, direction, type, content, language,
                risk_level, timestamp, audio_file, video_file, is_delivered)
               VALUES (?, ?, ?, ?, ?, 'English', 'none', ?, ?, ?, 0)""",
            (patient_id, department_id, direction, msg_type, content,
             datetime.now().isoformat(), audio_file, video_file),
        )
        mid = cursor.lastrowid
        conn.commit()
        conn.close()
        return mid

    def mark_department_thread_read(self, patient_id, department_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE messages SET is_read = 1 WHERE patient_id = ? AND department_id = ? AND direction = 'outgoing' AND is_read = 0",
            (patient_id, department_id),
        )
        conn.commit()
        conn.close()

    # ============================================================
    # DEPARTMENT TREATMENTS
    # ============================================================
    def create_department_treatment(self, patient_id, department_id, department_name,
                                     diagnosis, notes, next_appointment_date,
                                     next_appointment_reason):
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            """INSERT INTO treatments
               (patient_id, department_id, doctor_name, treatment_date, diagnosis,
                notes, next_appointment_date, next_appointment_reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (patient_id, department_id, department_name, now, diagnosis,
             notes, next_appointment_date, next_appointment_reason, now),
        )
        tid = cursor.lastrowid
        conn.commit()
        conn.close()
        return tid

    def get_department_treatments(self, department_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT t.id, t.patient_id, p.full_name, t.treatment_date, t.diagnosis,
                      t.notes, t.next_appointment_date, t.status
               FROM treatments t
               JOIN patients p ON t.patient_id = p.patient_id
               WHERE t.department_id = ?
               ORDER BY t.treatment_date DESC""",
            (department_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"id": r[0], "patient_id": r[1], "patient_name": r[2],
                 "treatment_date": r[3], "diagnosis": r[4], "notes": r[5],
                 "next_appointment_date": r[6], "status": r[7]} for r in rows]

    def get_department_patients(self, department_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT DISTINCT p.patient_id, p.full_name, p.phone_number, p.location
               FROM patients p
               WHERE p.patient_id IN (
                   SELECT patient_id FROM treatments WHERE department_id = ?
                   UNION SELECT patient_id FROM messages WHERE department_id = ?
                   UNION SELECT patient_id FROM appointments WHERE department_id = ?
               )
               ORDER BY p.full_name""",
            (department_id, department_id, department_id),
        )
        rows = cursor.fetchall()
        conn.close()
        return [{"patient_id": r[0], "full_name": r[1], "phone_number": r[2], "location": r[3]} for r in rows]

    def get_department_stats(self, department_id):
        """One combined query — safer and faster than 4 separate round trips."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """SELECT
                       (SELECT COUNT(*) FROM treatments WHERE department_id = ?) AS t_count,
                       (SELECT COUNT(*) FROM appointments WHERE department_id = ? AND status = 'pending') AS p_count,
                       (SELECT COUNT(DISTINCT patient_id) FROM messages WHERE department_id = ? AND direction = 'outgoing' AND is_read = 0) AS u_count,
                       (SELECT COUNT(DISTINCT patient_id) FROM messages WHERE department_id = ?) AS pt_count""",
                (department_id, department_id, department_id, department_id),
            )
            row = cursor.fetchone()
        except Exception as e:
            print("get_department_stats error: " + str(e))
            row = None
        finally:
            conn.close()

        if not row:
            return {"treatments": 0, "pending_appointments": 0, "unread_threads": 0, "patients": 0}

        return {
            "treatments": int(row[0] or 0),
            "pending_appointments": int(row[1] or 0),
            "unread_threads": int(row[2] or 0),
            "patients": int(row[3] or 0),
        }

