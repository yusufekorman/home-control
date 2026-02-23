import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Optional

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from models import User, ApiKey

pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


# ─── API Key helpers ───────────────────────────────────────────────────────────

def _hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key(db: Session, name: str) -> tuple[ApiKey, str]:
    """Creates an API key, stores hash, returns (model, raw_key)."""
    raw_key = "hck_" + secrets.token_urlsafe(32)
    prefix = raw_key[:8]
    hashed = _hash_key(raw_key)

    api_key = ApiKey(name=name, key_prefix=prefix, key_hash=hashed)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key, raw_key


def validate_api_key(db: Session, raw_key: str) -> Optional[ApiKey]:
    hashed = _hash_key(raw_key)
    key = db.query(ApiKey).filter(
        ApiKey.key_hash == hashed,
        ApiKey.is_active == True,
    ).first()
    if key:
        key.last_used_at = datetime.utcnow()
        db.commit()
    return key
