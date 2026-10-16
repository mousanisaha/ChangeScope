"""Pytest fixtures for ChangeScope test suite.

Configures an isolated in-memory SQLite database and TestClient for fast,
deterministic, and hermetic automated tests.
"""

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.auth import create_access_token, get_current_user, hash_password
from backend.database import Base, get_db
from backend.main import app
from backend import models, scheduler

# Create in-memory SQLite database engine shared across threads for testing
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def setup_test_db():
    """Create all database tables in memory before each test and drop after."""
    scheduler.set_session_factory(TestingSessionLocal)
    Base.metadata.create_all(bind=test_engine)
    yield
    scheduler.stop_scheduler()
    Base.metadata.drop_all(bind=test_engine)
    scheduler.set_session_factory(None)


@pytest.fixture
def db_session():
    """Yield an isolated database session for a test."""
    session = TestingSessionLocal()
    try:
        # Pre-seed default user 1 in the session
        user = session.query(models.User).filter(models.User.id == 1).first()
        if not user:
            user = models.User(
                id=1,
                email="testuser@example.com",
                hashed_password=hash_password("Password123!"),
                full_name="Default Test User",
                is_active=True,
                is_admin=True,
                auto_checks_enabled=True,
            )
            session.add(user)
            session.commit()
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    """Provide a TestClient pre-authenticated with default user 1 for backwards compatibility."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    def override_get_current_user(db: Session = Depends(override_get_db)):
        user = db.query(models.User).filter(models.User.id == 1).first()
        if not user:
            user = models.User(
                id=1,
                email="testuser@example.com",
                hashed_password=hash_password("Password123!"),
                full_name="Default Test User",
                is_active=True,
                is_admin=True,
                auto_checks_enabled=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def unauthed_client(db_session):
    """Provide an unauthenticated TestClient (no get_current_user override)."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides.pop(get_current_user, None)

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def user_factory(db_session):
    """Factory fixture to create test users with corresponding valid JWT auth headers."""
    def _create_user(email: str, password: str = "Password123!", full_name: str = None, is_admin: bool = False):
        user = models.User(
            email=email.strip().lower(),
            hashed_password=hash_password(password),
            full_name=full_name or email.split("@")[0],
            is_active=True,
            is_admin=is_admin,
            auto_checks_enabled=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        token = create_access_token({"sub": str(user.id), "email": user.email})
        headers = {"Authorization": f"Bearer {token}"}
        return user, token, headers

    return _create_user
