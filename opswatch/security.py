from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict

from cryptography.fernet import Fernet, InvalidToken

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(digest_b64)
    actual = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected)
    )
    return hmac.compare_digest(actual, expected)


def new_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_link_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def safe_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class Crypto:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self._fernet.encrypt(value.encode("utf-8")).decode()

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            return self._fernet.decrypt(value.encode()).decode("utf-8")
        except InvalidToken:
            return ""

    def encrypt_json(self, data: dict) -> str:
        if not data:
            return ""
        return self.encrypt(json.dumps(data, ensure_ascii=False))

    def decrypt_json(self, value: str) -> dict:
        raw = self.decrypt(value)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            return {}


class LoginThrottle:
    def __init__(self, attempts: int = 5, window: int = 60, lock: int = 60) -> None:
        self.attempts = attempts
        self.window = window
        self.lock = lock
        self._failures: dict[str, list[float]] = defaultdict(list)
        self._locked: dict[str, float] = {}

    def locked_for(self, key: str) -> int:
        until = self._locked.get(key)
        if until is None:
            return 0
        remaining = int(until - time.monotonic())
        if remaining <= 0:
            self._locked.pop(key, None)
            return 0
        return remaining

    def failure(self, key: str) -> None:
        now = time.monotonic()
        history = [t for t in self._failures[key] if now - t < self.window]
        history.append(now)
        self._failures[key] = history
        if len(history) >= self.attempts:
            self._locked[key] = now + self.lock
            self._failures[key] = []

    def success(self, key: str) -> None:
        self._failures.pop(key, None)
        self._locked.pop(key, None)
