import sqlite3

conn = sqlite3.connect('afyahiv_care.db')
cursor = conn.cursor()

# Check and add is_delivered column if not exists
try:
    cursor.execute("ALTER TABLE messages ADD COLUMN is_delivered INTEGER DEFAULT 0")
    print("✅ Added is_delivered column")
except Exception as e:
    if "duplicate column" in str(e):
        print("⚠️ is_delivered column already exists")
    else:
        print(f"Error: {e}")

# Check and add is_read_by_receiver column if not exists
try:
    cursor.execute("ALTER TABLE messages ADD COLUMN is_read_by_receiver INTEGER DEFAULT 0")
    print("✅ Added is_read_by_receiver column")
except Exception as e:
    if "duplicate column" in str(e):
        print("⚠️ is_read_by_receiver column already exists")
    else:
        print(f"Error: {e}")

conn.commit()
conn.close()

print("\n✅ Database update complete!")
print("\nNow restart your app and the read receipts will work!")