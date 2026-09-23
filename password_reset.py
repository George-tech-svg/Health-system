# password_reset.py
import re
from password_utils import hash_password


def _norm_phone(p):
    """Normalize phone: strip everything but digits, remove leading 254 or 0."""
    d = re.sub(r'\D', '', str(p or ''))
    if d.startswith('254'):
        d = d[3:]
    elif d.startswith('0'):
        d = d[1:]
    return d


def verify_patient_identity(db, patient_id, phone_number):
    """Return True if patient_id exists AND phone matches."""
    target = _norm_phone(phone_number)
    if not target:
        return False
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT phone_number FROM patients WHERE patient_id = ?", (patient_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False
    return _norm_phone(row[0]) == target


def reset_patient_password(db, patient_id, new_password):
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE patients SET password_hash = ? WHERE patient_id = ?",
        (hash_password(new_password), patient_id)
    )
    conn.commit()
    conn.close()


def verify_hospital_identity(db, username, phone):
    """Return True if hospital username exists AND phone matches."""
    target = _norm_phone(phone)
    if not target:
        return False
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT phone FROM hospitals WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False
    return _norm_phone(row[0]) == target


def reset_hospital_password(db, username, new_password):
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE hospitals SET password_hash = ? WHERE username = ?",
        (hash_password(new_password), username)
    )
    conn.commit()
    conn.close()