# migrations/run_migrations.py
import os
import sys
import ssl
import pg8000.dbapi
from pathlib import Path
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
MIGRATIONS_DIR = Path(__file__).parent

SQL_FILES = [
    "000_schema.sql",                  # creates all tables
    "001_hospitals_auth.sql",          # adds auth columns (idempotent)
    "002_patients_hospital_link.sql",  # links patients (idempotent)
    "003_indexes.sql",                 # performance indexes
]


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


def split_sql_statements(sql):
    """Split SQL on semicolons, but respect $$ ... $$ blocks."""
    statements = []
    buffer = ""
    in_dollar = False
    i = 0
    while i < len(sql):
        if sql[i:i+2] == "$$":
            in_dollar = not in_dollar
            buffer += "$$"
            i += 2
            continue
        if sql[i] == ";" and not in_dollar:
            stmt = buffer.strip()
            if stmt:
                statements.append(stmt)
            buffer = ""
            i += 1
            continue
        buffer += sql[i]
        i += 1
    if buffer.strip():
        statements.append(buffer.strip())
    return statements


def run_sql_file(cursor, filepath):
    print(f"\n--- Running: {filepath.name} ---")
    sql = filepath.read_text(encoding="utf-8")

    # Strip line comments that start at the beginning of a line
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        lines.append(line)
    sql = "\n".join(lines)

    statements = split_sql_statements(sql)
    for stmt in statements:
        try:
            cursor.execute(stmt)
        except Exception as e:
            first_line = stmt.strip().split("\n")[0][:80]
            print(f"   FAILED on statement: {first_line}...")
            print(f"   Error: {e}")
            raise

    print(f"   OK: {filepath.name}  ({len(statements)} statement(s))")


def main():
    if not DATABASE_URL:
        print("DATABASE_URL not set. Check your .env file.")
        sys.exit(1)

    print("\n=== FastAfya - PostgreSQL Migration ===\n")
    print(f"Target: {DATABASE_URL.split('@')[-1]}\n")

    try:
        conn = pg8000.dbapi.connect(**parse_neon_url(DATABASE_URL))
        conn.autocommit = True
        cursor = conn.cursor()

        for sql_file in SQL_FILES:
            path = MIGRATIONS_DIR / sql_file
            if not path.exists():
                print(f"   Missing file: {sql_file}")
                continue
            run_sql_file(cursor, path)

        print("\nAll migrations applied.\n")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"\nMigration failed: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()