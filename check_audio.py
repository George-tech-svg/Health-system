import sqlite3

conn = sqlite3.connect('fastafya.db')
cursor = conn.cursor()

cursor.execute("SELECT id, patient_id, content, audio_file FROM messages WHERE type = 'voice' ORDER BY id DESC LIMIT 5")
messages = cursor.fetchall()

print("Last 5 voice messages:")
for msg in messages:
    print(f"ID: {msg[0]}, Patient: {msg[1]}, Content: {msg[2]}, Audio File: {msg[3]}")

conn.close()