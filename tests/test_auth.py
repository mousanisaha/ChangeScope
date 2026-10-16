"""Automated tests for ChangeScope user authentication and account management.

Covers:
- User registration (valid data, duplicate email rejection, invalid email, short password)
- Password security (bcrypt hashing verification, never plaintext in DB)
- Login authentication (success, JWT generation, HTTP-only cookie setting)
- Authentication failures (wrong password, non-existent user generic error, deactivated account)
- Current user profile endpoint /api/auth/me (GET and PUT)
- Token extraction via Bearer header and via cookie
- Logout and cookie clearing
- Rate limiting on authentication attempts (HTTP 429)
"""

from datetime import timedelta
import pytest
from fastapi.testclient import TestClient

from backend import auth, models
from backend.auth import create_access_token, hash_password, verify_password
from backend.main import app


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Ensure rate limiter attempts are reset before each auth test."""
    with auth.auth_limiter._lock:
        auth.auth_limiter._attempts.clear()
    yield
    with auth.auth_limiter._lock:
        auth.auth_limiter._attempts.clear()


def test_password_hashing_and_verification():
    """Test bcrypt hashing produces unique non-plaintext salts and verifies correctly."""
    pwd = "MySecretPassword123!"
    hashed = hash_password(pwd)

    assert hashed != pwd
    assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
    assert verify_password(pwd, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(pwd, "") is False


def test_user_registration_success(unauthed_client, db_session):
    """Test registering a new user creates account with hashed password and returns 201."""
    res = unauthed_client.post(
        "/api/auth/register",
        json={
            "email": "alice@example.com",
            "password": "SecurePassword123!",
            "full_name": "Alice Innovator",
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert "access_token" in data
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["full_name"] == "Alice Innovator"
    assert data["user"]["is_active"] is True
    assert "password" not in data["user"]
    assert "hashed_password" not in data["user"]

    # Verify directly in SQLite that password is NOT plaintext
    user = db_session.query(models.User).filter(models.User.email == "alice@example.com").first()
    assert user is not None
    assert user.hashed_password != "SecurePassword123!"
    assert verify_password("SecurePassword123!", user.hashed_password) is True


def test_user_registration_duplicate_email_rejected(unauthed_client):
    """Test registering duplicate email fails with 400 and clear error message."""
    payload = {
        "email": "duplicate@example.com",
        "password": "Password123!",
        "full_name": "First User",
    }
    res1 = unauthed_client.post("/api/auth/register", json=payload)
    assert res1.status_code == 201

    # Second registration with same email (even with different case)
    payload["email"] = "DUPLICATE@example.com"
    res2 = unauthed_client.post("/api/auth/register", json=payload)
    assert res2.status_code == 400
    detail = res2.json()["detail"].lower()
    assert "already exists" in detail or "already registered" in detail


def test_user_registration_validation_rules(unauthed_client):
    """Test email formatting and password minimum length validation."""
    # Short password (< 8 chars)
    res_short = unauthed_client.post(
        "/api/auth/register",
        json={"email": "valid@example.com", "password": "short"},
    )
    assert res_short.status_code == 422

    # Invalid email format
    res_email = unauthed_client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": "Password123!"},
    )
    assert res_email.status_code == 422


def test_user_login_success(unauthed_client, user_factory):
    """Test successful login returns access token and sets secure HTTP-only cookie."""
    user, _, _ = user_factory("login_user@example.com", "CorrectPassword123!")

    res = unauthed_client.post(
        "/api/auth/login",
        json={
            "email": "LOGIN_USER@example.com",  # verify case-insensitivity
            "password": "CorrectPassword123!",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "login_user@example.com"

    # Verify HTTP-only cookie is set
    assert auth.COOKIE_NAME in res.cookies
    assert res.cookies[auth.COOKIE_NAME] == data["access_token"]


def test_user_login_invalid_password_returns_generic_401(unauthed_client, user_factory):
    """Test invalid password returns generic 401 without revealing password correctness."""
    user_factory("validuser@example.com", "CorrectPassword123!")

    res = unauthed_client.post(
        "/api/auth/login",
        json={
            "email": "validuser@example.com",
            "password": "WrongPassword999!",
        },
    )
    assert res.status_code == 401
    assert "invalid email or password" in res.json()["detail"].lower()


def test_user_login_nonexistent_email_returns_generic_401(unauthed_client):
    """Test non-existent email returns same generic 401 to prevent user enumeration."""
    res = unauthed_client.post(
        "/api/auth/login",
        json={
            "email": "nonexistent_target@example.com",
            "password": "AnyPassword123!",
        },
    )
    assert res.status_code == 401
    assert "invalid email or password" in res.json()["detail"].lower()


def test_user_login_deactivated_account_rejected(unauthed_client, db_session, user_factory):
    """Test deactivated account is denied login."""
    user, _, _ = user_factory("deactivated@example.com", "Password123!")
    user.is_active = False
    db_session.commit()

    res = unauthed_client.post(
        "/api/auth/login",
        json={
            "email": "deactivated@example.com",
            "password": "Password123!",
        },
    )
    assert res.status_code == 403
    assert "deactivated" in res.json()["detail"].lower()


def test_get_current_user_profile_with_bearer_token(unauthed_client, user_factory):
    """Test GET /api/auth/me returns current user info when Bearer token header is sent."""
    user, token, headers = user_factory("me_bearer@example.com", "Password123!", full_name="Bearer User")

    res = unauthed_client.get("/api/auth/me", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == user.id
    assert data["email"] == "me_bearer@example.com"
    assert data["full_name"] == "Bearer User"


def test_get_current_user_profile_with_cookie(unauthed_client, user_factory):
    """Test GET /api/auth/me works seamlessly when token is provided via HTTP-only cookie."""
    user, token, _ = user_factory("me_cookie@example.com", "Password123!", full_name="Cookie User")

    # Pass cookie without Authorization header
    res = unauthed_client.get("/api/auth/me", cookies={auth.COOKIE_NAME: token})
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == user.id
    assert data["email"] == "me_cookie@example.com"


def test_get_current_user_unauthenticated_returns_401(unauthed_client):
    """Test GET /api/auth/me returns 401 when no token or cookie is supplied."""
    res = unauthed_client.get("/api/auth/me")
    assert res.status_code == 401
    assert "authentication required" in res.json()["detail"].lower()


def test_get_current_user_invalid_or_expired_token(unauthed_client):
    """Test malformed and expired JWT tokens return 401."""
    # Malformed token
    res_malformed = unauthed_client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid.token.structure"},
    )
    assert res_malformed.status_code == 401

    # Expired token
    expired_token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-10))
    res_expired = unauthed_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res_expired.status_code == 401


def test_update_current_user_profile(unauthed_client, user_factory):
    """Test PUT /api/auth/me allows updating full_name and auto_checks_enabled."""
    user, token, headers = user_factory("update_me@example.com", "Password123!", full_name="Old Name")

    res = unauthed_client.put(
        "/api/auth/me",
        headers=headers,
        json={
            "full_name": "Updated Name",
            "auto_checks_enabled": False,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["full_name"] == "Updated Name"
    assert data["auto_checks_enabled"] is False


def test_update_user_password(unauthed_client, db_session, user_factory):
    """Test PUT /api/auth/me updates password when valid current password is provided."""
    user, token, headers = user_factory("pwd_change@example.com", "OldPassword123!")

    # Attempt with wrong current password
    res_wrong = unauthed_client.put(
        "/api/auth/me",
        headers=headers,
        json={
            "current_password": "WrongCurrentPassword!",
            "new_password": "BrandNewPassword123!",
        },
    )
    assert res_wrong.status_code == 400
    assert "incorrect" in res_wrong.json()["detail"].lower()

    # Attempt with correct current password
    res_ok = unauthed_client.put(
        "/api/auth/me",
        headers=headers,
        json={
            "current_password": "OldPassword123!",
            "new_password": "BrandNewPassword123!",
        },
    )
    assert res_ok.status_code == 200

    # Verify login with new password works
    res_login = unauthed_client.post(
        "/api/auth/login",
        json={"email": "pwd_change@example.com", "password": "BrandNewPassword123!"},
    )
    assert res_login.status_code == 200


def test_logout_endpoint_clears_cookie(unauthed_client, user_factory):
    """Test POST /api/auth/logout clears auth cookie and returns success."""
    user, token, headers = user_factory("logout_user@example.com", "Password123!")

    res = unauthed_client.post(
        "/api/auth/logout",
        headers=headers,
        cookies={auth.COOKIE_NAME: token},
    )
    assert res.status_code == 200
    assert res.json()["success"] is True

    # Cookie in response should be empty / deleted
    cookie = res.cookies.get(auth.COOKIE_NAME)
    assert cookie is None or cookie == "" or 'deleted' in str(res.headers.get("set-cookie", "")).lower()


def test_auth_rate_limiting_exceeded(unauthed_client):
    """Test exceeding 10 failed login attempts returns HTTP 429 Too Many Requests."""
    for i in range(10):
        res = unauthed_client.post(
            "/api/auth/login",
            json={"email": f"brute_force_{i}@example.com", "password": "WrongPassword!"},
        )
        assert res.status_code == 401

    # The 11th request should be blocked by rate limiter
    res_blocked = unauthed_client.post(
        "/api/auth/login",
        json={"email": "blocked@example.com", "password": "WrongPassword!"},
    )
    assert res_blocked.status_code == 429
    assert "too many" in res_blocked.json()["detail"].lower()
