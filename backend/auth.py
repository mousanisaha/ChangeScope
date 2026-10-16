"""Authentication and authorization utilities for ChangeScope.

Provides password hashing via bcrypt, JWT token creation and verification,
cookie management, rate limiting, and FastAPI user dependencies.
"""

from datetime import datetime, timedelta, timezone
import os
import threading
import time
from typing import Dict, List, Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend import models

# JWT configuration
# CHANGESCOPE_SECRET_KEY can be provided via environment variable; falls back to a 32+ character default
SECRET_KEY = os.getenv(
    "CHANGESCOPE_SECRET_KEY",
    "changescope-jwt-secret-key-production-hardened-32-chars-min",
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 days
COOKIE_NAME = "changescope_token"

# Environment flag for secure cookies (HTTPS in production)
IS_PRODUCTION = os.getenv("CHANGESCOPE_ENV", "development").lower() == "production"


def hash_password(password: str) -> str:
    """Hash a plaintext password securely using bcrypt."""
    if not password:
        raise ValueError("Password cannot be empty")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token containing user claims."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({
        "exp": expire,
        "iat": now,
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a signed JWT token. Returns payload dict or None on failure."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None


def extract_token_from_request(request: Request) -> Optional[str]:
    """Extract token from Authorization Bearer header or fallback HTTP-only cookie."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    cookie_token = request.cookies.get(COOKIE_NAME)
    if cookie_token and cookie_token.strip():
        return cookie_token.strip()

    return None


def set_auth_cookie(response: Response, token: str) -> None:
    """Set a secure HTTP-only session cookie for the client."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        samesite="lax",
        secure=IS_PRODUCTION,
        path="/",
    )


def delete_auth_cookie(response: Response) -> None:
    """Clear the HTTP-only session cookie upon logout."""
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=IS_PRODUCTION,
        path="/",
    )


class AuthRateLimiter:
    """Thread-safe sliding-window rate limiter for authentication attempts."""

    def __init__(self, max_attempts: int = 10, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def check_rate_limit(self, identifier: str) -> None:
        """Raise HTTP 429 if rate limit has been exceeded for this IP/identifier."""
        now = time.time()
        cutoff = now - self.window_seconds
        with self._lock:
            history = self._attempts.get(identifier, [])
            valid_history = [t for t in history if t > cutoff]
            self._attempts[identifier] = valid_history

            if len(valid_history) >= self.max_attempts:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many authentication attempts. Please try again in 1 minute.",
                )

    def record_failure(self, identifier: str) -> None:
        """Record a failed authentication attempt."""
        now = time.time()
        with self._lock:
            if identifier not in self._attempts:
                self._attempts[identifier] = []
            self._attempts[identifier].append(now)

    def reset(self, identifier: str) -> None:
        """Reset attempts after a successful authentication."""
        with self._lock:
            self._attempts.pop(identifier, None)


# Global rate limiter instance for auth endpoints
auth_limiter = AuthRateLimiter(max_attempts=10, window_seconds=60)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> models.User:
    """FastAPI dependency: require an authenticated, active user.
    
    Raises HTTP 401 if token is missing or invalid, or HTTP 403 if account is disabled.
    """
    token = extract_token_from_request(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(payload["sub"])
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or session revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    return user


def get_optional_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[models.User]:
    """FastAPI dependency: optionally identify authenticated user, or None if unauthenticated."""
    try:
        return get_current_user(request, db)
    except HTTPException:
        return None
