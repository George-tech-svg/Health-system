# _diag_pool.py
from database import Database, _thread_local
import time

db = Database()

print("\n=== Call 1 ===")
t = time.time()
db.get_all_villages()
print(f"Time: {time.time()-t:.2f}s")
conn1 = getattr(_thread_local, "conn", None)
print(f"Connection id: {id(conn1)}")

print("\n=== Wait 3 seconds ===")
time.sleep(3)

print("\n=== Call 2 ===")
t = time.time()
db.get_all_villages()
print(f"Time: {time.time()-t:.2f}s")
conn2 = getattr(_thread_local, "conn", None)
print(f"Connection id: {id(conn2)}")

print(f"\nSame connection? {conn1 is conn2}")

if conn1 is not None:
    try:
        conn1.run("SELECT 1")
        print("conn1 still alive: YES")
    except Exception as e:
        print(f"conn1 still alive: NO - {e}")

print("\nDONE")