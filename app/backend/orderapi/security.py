"""Password hashing and session tokens (standard library only).

PBKDF2-HMAC-SHA256 is deliberately slow: every guess an attacker makes costs
CPU time. OWASP recommends 600,000 iterations. The slow_login flaw uses
3,000,000, which costs ~1 s of CPU per login, so login bursts saturate the CPU.
"""
import hashlib
import hmac
import os
import secrets

from . import flaws

ITERATIONS = 3_000_000 if flaws.on("slow_login") else 600_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        iterations = int(iterations)
    except ValueError:
        # Unusable hash (e.g. archive accounts). Still do the work so the response
        # time doesn't reveal which emails exist (user enumeration).
        hashlib.pbkdf2_hmac("sha256", password.encode(), b"dummy-salt", ITERATIONS)
        return False
    # Note: a hash keeps the iteration count it was created with. Fixing ITERATIONS
    # only helps new passwords, unless you re-hash on successful login.
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), iterations)
    return hmac.compare_digest(digest.hex(), digest_hex)


def burn_dummy_hash(password: str) -> None:
    """Same cost as a real check, for unknown emails (prevents timing attacks)."""
    hashlib.pbkdf2_hmac("sha256", password.encode(), b"dummy-salt", ITERATIONS)


def new_token() -> tuple[str, str]:
    """Return (token for the client, hash to store in the database)."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
