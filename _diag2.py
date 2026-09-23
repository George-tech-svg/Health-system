# _diag2.py
from database import Database, _conn_pool, _pool_initialized
import time

print(f"\nPool initialized: {_pool_initialized}")
print(f"Pool size at start: {_conn_pool.qsize()}")

db = Database()

for i in range(6):
    t = time.time()
    db.get_all_villages()
    elapsed = time.time() - t
    print(f"Call {i+1}: {elapsed*1000:.0f}ms  |  pool size: {_conn_pool.qsize()}")

print("\nDONE")