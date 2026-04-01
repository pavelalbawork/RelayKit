"""
Simple auth module — used as the example target in the RelayKit walkthrough.
"""

import hashlib
import secrets
from dataclasses import dataclass


@dataclass
class User:
    id: str
    email: str
    password_hash: str


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    return salt + ":" + hashlib.sha256((salt + password).encode()).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    salt, digest = stored_hash.split(":", 1)
    return hashlib.sha256((salt + password).encode()).hexdigest() == digest


def login(email: str, password: str, users: dict[str, User]) -> User | None:
    user = users.get(email)
    if user and verify_password(password, user.password_hash):
        return user
    return None
