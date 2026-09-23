# password_utils.py
import hashlib
import secrets

DEFAULT_ITERATIONS = 100_000


def hash_password(password, iterations=DEFAULT_ITERATIONS):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password, stored_hash):
    try:
        algorithm, iterations, salt_hex, hash_hex = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return secrets.compare_digest(dk, expected)
    except Exception:
        return False