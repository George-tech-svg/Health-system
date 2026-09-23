import sqlite3

conn = sqlite3.connect('fastafya.db')
cursor = conn.cursor()

cursor.execute("PRAGMA table_info(patients)")
columns = cursor.fetchall()
print("Table structure:")
for col in columns:
    print(f"  Index {col[0]}: {col[1]}")

cursor.execute("SELECT * FROM patients")
patients = cursor.fetchall()
print("\nAll data:")
for patient in patients:
    print(f"Row: {patient}")

conn.close()