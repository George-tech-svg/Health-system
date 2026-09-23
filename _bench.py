import time
from database import Database

db = Database()

# Time 10 sequential calls
start = time.time()
for i in range(10):
    db.get_all_villages()
elapsed = time.time() - start

print(f"\n10 sequential get_all_villages() calls: {elapsed:.2f}s")
print(f"Average per call: {elapsed/10*1000:.0f}ms")
print(f"\nProjected time for a 15-call dashboard: {elapsed/10*15:.2f}s")