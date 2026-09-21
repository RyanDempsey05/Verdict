import os

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from itsdangerous import BadSignature, URLSafeTimedSerializer

SECRET_KEY = os.environ["SECRET_KEY"]
SESSION_COOKIE = "__Host-session"

# enforced by the server on every request, not just by the browser's cookie expiry
SESSION_MAX_AGE = 60 * 60 * 24 * 14

_hasher = PasswordHasher()
# timed signer: each cookie carries its own issue time. the salt changed from
# "session" so every cookie from the old format is rejected cleanly
_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="session-v2")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def sign_session(user_id: int, version: int = 0) -> str:
    return _serializer.dumps({"uid": user_id, "v": version})


def read_session(cookie_value: str) -> tuple[int, int] | None:
    """(user_id, session_version) for a valid, unexpired cookie, else None."""
    try:
        data = _serializer.loads(cookie_value, max_age=SESSION_MAX_AGE)
    except BadSignature:  # SignatureExpired is a subclass, so this covers expiry too
        return None
    if not isinstance(data, dict):
        return None
    uid, version = data.get("uid"), data.get("v", 0)
    if not isinstance(uid, int) or not isinstance(version, int):
        return None
    return uid, version
