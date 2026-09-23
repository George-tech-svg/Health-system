# migrations/verify.py
import os
import ssl
import pg8000.dbapi
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


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


def main():
    if not DATABASE_URL:
        print("DATABASE_URL not set.")
        return

    conn = pg8000.dbapi.connect(**parse_neon_url(DATABASE_URL))
    cursor = conn.cursor()

    print("\n=== HOSPITALS ===")
    cursor.execute("SELECT id, name, username, county FROM hospitals ORDER BY id")
    for row in cursor.fetchall():
        print(f"  {row[0]}  {row[1]}  |  username={row[2]}  |  county={row[3]}")

    print("\n=== TABLES IN DATABASE ===")
    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    for row in cursor.fetchall():
        print(f"  {row[0]}")

    print("\n=== PATIENTS LINKED TO HOSPITALS ===")
    cursor.execute("SELECT COUNT(*) FROM patients WHERE hospital_id IS NULL")
    unlinked = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM patients WHERE hospital_id IS NOT NULL")
    linked = cursor.fetchone()[0]
    print(f"  Unlinked: {unlinked}")
    print(f"  Linked:   {linked}")

    cursor.close()
    conn.close()
    print()


if __name__ == "__main__":
    main()