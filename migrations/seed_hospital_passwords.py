# migrations/seed_hospital_passwords.py
import os
import ssl
import hashlib
import secrets
import pg8000.dbapi
from datetime import datetime
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
DEFAULT_PASSWORD = "hospital123"

HOSPITAL_CREDENTIALS = {
    "Siaya County Referral Hospital": {
        "username": "siaya.hospital",
        "county": "Siaya", "sub_county": "Siaya Town",
        "contact_person": "Hospital Administrator",
        "contact_email": "siaya@afyahiv.co.ke",
    },
    "Bondo Sub-County Hospital": {
        "username": "bondo.hospital",
        "county": "Siaya", "sub_county": "Bondo",
        "contact_person": "Hospital Administrator",
        "contact_email": "bondo@afyahiv.co.ke",
    },
    "Jaramogi Oginga Odinga Hospital": {
        "username": "kisumu.hospital",
        "county": "Kisumu", "sub_county": "Kisumu Central",
        "contact_person": "Hospital Administrator",
        "contact_email": "kisumu@afyahiv.co.ke",
    },
    "Rangala Health Centre": {
        "username": "rangala.hospital",
        "county": "Siaya", "sub_county": "Rangala",
        "contact_person": "Hospital Administrator",
        "contact_email": "rangala@afyahiv.co.ke",
    },
    "Ugunja Sub-County Hospital": {
        "username": "ugunja.hospital",
        "county": "Siaya", "sub_county": "Ugunja",
        "contact_person": "Hospital Administrator",
        "contact_email": "ugunja@afyahiv.co.ke",
    },
}


def parse_neon_url(url):
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


def hash_password(password, iterations=100_000):
    """
    pbkdf2_sha256 password hashing — pure Python stdlib.
    Format: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
    """
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def seed():
    if not DATABASE_URL:
        print("DATABASE_URL not set.")
        return

    conn = pg8000.dbapi.connect(**parse_neon_url(DATABASE_URL))
    conn.autocommit = True
    cursor = conn.cursor()

    print("\n=== Seeding Hospital Logins ===\n")

    seeded, skipped, missing = 0, 0, 0

    for hospital_name, creds in HOSPITAL_CREDENTIALS.items():
        cursor.execute(
            "SELECT id, username FROM hospitals WHERE name = %s",
            (hospital_name,)
        )
        row = cursor.fetchone()

        if not row:
            print(f"   Not found: {hospital_name}")
            missing += 1
            continue

        hospital_id, existing_username = row

        if existing_username:
            print(f"   Already seeded: {hospital_name} -> {existing_username}")
            skipped += 1
            continue

        password_hash = hash_password(DEFAULT_PASSWORD)

        cursor.execute("""
            UPDATE hospitals
            SET username = %s,
                password_hash = %s,
                county = %s,
                sub_county = %s,
                contact_person = %s,
                contact_email = %s,
                is_active = 1,
                created_at = %s
            WHERE id = %s
        """, (
            creds["username"], password_hash,
            creds["county"], creds["sub_county"],
            creds["contact_person"], creds["contact_email"],
            datetime.now().isoformat(), hospital_id,
        ))

        print(f"   Seeded: {hospital_name}")
        print(f"      username: {creds['username']}")
        print(f"      password: {DEFAULT_PASSWORD}")
        seeded += 1

    cursor.close()
    conn.close()

    print(f"\n--- Summary ---")
    print(f"   Seeded:  {seeded}")
    print(f"   Skipped: {skipped}")
    print(f"   Missing: {missing}\n")


if __name__ == "__main__":
    seed()