# Platform Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the multi-tenant auth, org, engagement, and invitation layer that all subsequent sub-projects depend on — producing a working API where a buyer org can be created, an engagement opened, and a seller invited and onboarded.

**Architecture:** FastAPI async backend with SQLAlchemy + asyncpg against RDS PostgreSQL. Cognito provides two user pools — one for buyer org users, one for seller engagement accounts. JWT middleware validates tokens on every protected route. All queries filter by `buyer_org_id` (the tenant key). A React frontend scaffold provides login, org dashboard, and seller invitation acceptance.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x (async), asyncpg, Alembic, pydantic-settings, python-jose[cryptography], React 18 + TypeScript, Vite, React Router, amazon-cognito-identity-js, Terraform

---

## File Map

### Backend (new files)
```
app/
  core/
    config.py          — Settings: all env vars via pydantic-settings
    database.py        — async engine, session factory, get_db dependency
    auth.py            — Cognito JWT validation, get_current_user dependency
  db/
    models/
      __init__.py      — imports all models so Alembic sees them
      buyer_org.py     — BuyerOrg ORM model
      user.py          — User ORM model (buyer-side)
      engagement.py    — Engagement ORM model
      engagement_user.py — EngagementUser (join: engagement ↔ user + role)
      seller_account.py  — SellerAccount (per-engagement seller user)
      invitation.py    — Invitation (token-based invite record)
    migrations/
      env.py           — Alembic env config (points at all models)
      versions/        — generated migration files
  schemas/
    buyer_org.py       — BuyerOrgCreate, BuyerOrgResponse
    user.py            — UserResponse, UserRole enum
    engagement.py      — EngagementCreate, EngagementResponse, EngagementStatus enum
    invitation.py      — InvitationCreate, InvitationResponse, AcceptInvitation
  services/
    invitation.py      — token generation, token validation, email stub
  api/
    dependencies.py    — require_role(), require_org_member() deps
    routes/
      orgs.py          — POST /orgs, GET /orgs/{org_id}
      engagements.py   — CRUD under /orgs/{org_id}/engagements
      invitations.py   — send invite, accept invite, get invite info
      users.py         — engagement user management
```

### Backend (modified)
```
app/main.py            — include all new routers
requirements.txt       — add new dependencies
alembic.ini            — Alembic config (new file at repo root)
```

### Infrastructure (new)
```
infra/
  main.tf              — root module, calls cognito + rds modules
  variables.tf
  outputs.tf
  modules/
    cognito/
      main.tf          — two user pools: buyer_orgs + sellers
      variables.tf
      outputs.tf
    rds/
      main.tf          — PostgreSQL db.t3.micro
      variables.tf
      outputs.tf
```

### Frontend (new)
```
frontend/
  src/
    main.tsx
    App.tsx                 — BrowserRouter + AuthProvider
    auth/
      cognito.ts            — CognitoUserPool instances + signIn/signUp/getIdToken helpers
      AuthContext.tsx       — React context: current session, loading flag, useAuth hook
    pages/
      Login.tsx             — sign-in form (buyer pool)
      OrgDashboard.tsx      — list engagements for the buyer org
      AcceptInvitation.tsx  — seller sign-up + invitation acceptance
    components/
      RoleGuard.tsx         — redirect to /login if no active session
      NavBar.tsx
    api/
      client.ts             — axios instance with auto-injected ID token
      engagements.ts        — API calls for engagements
    types/index.ts          — shared TypeScript types matching API schemas
  package.json
  tsconfig.json
  vite.config.ts
```

### Tests (new)
```
tests/
  conftest.py          — async test client, test DB session, fixtures
  test_orgs.py
  test_engagements.py
  test_invitations.py
  test_users.py
  test_auth.py
```

---

## Task 1: Dependencies & Directory Skeleton

**Files:**
- Modify: `requirements.txt`
- Create: `app/core/__init__.py`, `app/db/__init__.py`, `app/db/models/__init__.py`, `app/schemas/__init__.py`, `app/services/__init__.py`, `app/api/dependencies.py`

- [ ] **Step 1: Update requirements.txt**

```
fastapi>=0.100,<1.0
uvicorn>=0.23,<1.0
pydantic>=2.0,<3.0
pydantic-settings>=2.0,<3.0
sqlalchemy>=2.0,<3.0
asyncpg>=0.29,<1.0
alembic>=1.13,<2.0
python-jose[cryptography]>=3.3,<4.0
httpx>=0.26,<1.0
pytest>=8.0,<9.0
pytest-asyncio>=0.23,<1.0
pytest-httpx>=0.30,<1.0
anyio>=4.0,<5.0
```

- [ ] **Step 2: Create directory __init__.py files**

Create empty `__init__.py` in each new directory:
`app/core/`, `app/db/`, `app/db/models/`, `app/schemas/`, `app/services/`

- [ ] **Step 3: Install**

```bash
pip install -r requirements.txt
```

Expected: all packages install without error.

- [ ] **Step 4: Create `app/api/dependencies.py` stub**

```python
# Shared FastAPI dependencies — populated in Tasks 5 and 9
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt app/core/__init__.py app/db/__init__.py \
  app/db/models/__init__.py app/schemas/__init__.py \
  app/services/__init__.py app/api/dependencies.py
git commit -m "feat: add platform foundation dependencies and directory structure"
```

---

## Task 2: Core Config & Database Session

**Files:**
- Create: `app/core/config.py`, `app/core/database.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:
```python
import pytest
from pydantic import ValidationError


def test_settings_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("COGNITO_BUYER_USER_POOL_ID", raising=False)
    monkeypatch.delenv("COGNITO_SELLER_USER_POOL_ID", raising=False)
    monkeypatch.delenv("COGNITO_REGION", raising=False)
    from importlib import reload
    import app.core.config as cfg_module
    reload(cfg_module)
    with pytest.raises((ValidationError, Exception)):
        cfg_module.Settings()


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("COGNITO_BUYER_USER_POOL_ID", "us-east-1_BUYER")
    monkeypatch.setenv("COGNITO_SELLER_USER_POOL_ID", "us-east-1_SELLER")
    monkeypatch.setenv("COGNITO_REGION", "us-east-1")
    monkeypatch.setenv("INVITATION_SECRET_KEY", "test-secret-32-chars-minimum!!")
    from importlib import reload
    import app.core.config as cfg_module
    reload(cfg_module)
    s = cfg_module.Settings()
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.cognito_region == "us-east-1"
```

- [ ] **Step 2: Run test — expect FAIL**

```bash
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError` or `AttributeError`.

- [ ] **Step 3: Implement `app/core/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str
    cognito_buyer_user_pool_id: str
    cognito_seller_user_pool_id: str
    cognito_region: str
    invitation_secret_key: str  # min 32 chars, used for HMAC token signing
    environment: str = "development"
    invitation_ttl_hours: int = 72


settings = Settings()
```

- [ ] **Step 4: Implement `app/core/database.py`**

```python
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
pytest tests/test_config.py -v
```

- [ ] **Step 6: Commit**

```bash
git add app/core/config.py app/core/database.py tests/test_config.py
git commit -m "feat: add core config and async database session"
```

---

## Task 3: Database ORM Models

**Files:**
- Create: `app/db/models/buyer_org.py`, `app/db/models/user.py`, `app/db/models/engagement.py`, `app/db/models/engagement_user.py`, `app/db/models/seller_account.py`, `app/db/models/invitation.py`, `app/db/models/__init__.py`

- [ ] **Step 1: Write the failing test**

`tests/test_models.py`:
```python
from app.db.models.buyer_org import BuyerOrg
from app.db.models.engagement import Engagement, EngagementStatus
from app.db.models.invitation import Invitation, InvitationType
from app.db.models.user import User, UserRole


def test_buyer_org_has_required_columns():
    cols = {c.key for c in BuyerOrg.__table__.columns}
    assert {"id", "name", "created_at"}.issubset(cols)


def test_engagement_status_enum_has_expected_values():
    assert "seller_invited" in EngagementStatus.__members__
    assert "active" in EngagementStatus.__members__
    assert "offboarding" in EngagementStatus.__members__
    assert "closed" in EngagementStatus.__members__
    assert "abandoned" in EngagementStatus.__members__


def test_user_role_enum_has_expected_values():
    assert "org_admin" in UserRole.__members__
    assert "buyer" in UserRole.__members__
    assert "external_advisor" in UserRole.__members__


def test_invitation_type_enum_has_expected_values():
    assert "seller" in InvitationType.__members__
    assert "advisor" in InvitationType.__members__
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_models.py -v
```

- [ ] **Step 3: Implement `app/db/models/buyer_org.py`**

```python
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class BuyerOrg(Base):
    __tablename__ = "buyer_orgs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    users: Mapped[list["User"]] = relationship("User", back_populates="org")
    engagements: Mapped[list["Engagement"]] = relationship("Engagement", back_populates="org")
```

- [ ] **Step 4: Implement `app/db/models/user.py`**

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserRole(enum.Enum):
    org_admin = "org_admin"
    buyer = "buyer"
    external_advisor = "external_advisor"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    buyer_org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("buyer_orgs.id"), nullable=False)
    cognito_sub: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    org: Mapped["BuyerOrg"] = relationship("BuyerOrg", back_populates="users")
    engagement_users: Mapped[list["EngagementUser"]] = relationship("EngagementUser", back_populates="user")
```

- [ ] **Step 5: Implement `app/db/models/engagement.py`**

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EngagementStatus(enum.Enum):
    created = "created"
    seller_invited = "seller_invited"
    seller_accepted = "seller_accepted"
    active = "active"
    offboarding = "offboarding"
    closed = "closed"
    abandoned = "abandoned"


class Engagement(Base):
    __tablename__ = "engagements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    buyer_org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("buyer_orgs.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[EngagementStatus] = mapped_column(Enum(EngagementStatus), nullable=False, default=EngagementStatus.created)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    org: Mapped["BuyerOrg"] = relationship("BuyerOrg", back_populates="engagements")
    engagement_users: Mapped[list["EngagementUser"]] = relationship("EngagementUser", back_populates="engagement")
    seller_accounts: Mapped[list["SellerAccount"]] = relationship("SellerAccount", back_populates="engagement")
    invitations: Mapped[list["Invitation"]] = relationship("Invitation", back_populates="engagement")
```

- [ ] **Step 6: Implement `app/db/models/engagement_user.py`**

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class EngagementRole(enum.Enum):
    buyer = "buyer"
    external_advisor = "external_advisor"


class EngagementUser(Base):
    __tablename__ = "engagement_users"
    __table_args__ = (UniqueConstraint("engagement_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    engagement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("engagements.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    role: Mapped[EngagementRole] = mapped_column(Enum(EngagementRole), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    engagement: Mapped["Engagement"] = relationship("Engagement", back_populates="engagement_users")
    user: Mapped["User"] = relationship("User", back_populates="engagement_users")
```

- [ ] **Step 7: Implement `app/db/models/seller_account.py`**

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SellerAccountStatus(enum.Enum):
    invited = "invited"
    active = "active"
    offboarding = "offboarding"
    revoked = "revoked"


class SellerAccount(Base):
    __tablename__ = "seller_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    engagement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("engagements.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    cognito_sub: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    status: Mapped[SellerAccountStatus] = mapped_column(Enum(SellerAccountStatus), nullable=False, default=SellerAccountStatus.invited)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    engagement: Mapped["Engagement"] = relationship("Engagement", back_populates="seller_accounts")
```

- [ ] **Step 8: Implement `app/db/models/invitation.py`**

```python
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class InvitationType(enum.Enum):
    seller = "seller"
    advisor = "advisor"


class InvitationStatus(enum.Enum):
    pending = "pending"
    accepted = "accepted"
    expired = "expired"
    revoked = "revoked"


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    engagement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("engagements.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    token: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    invitation_type: Mapped[InvitationType] = mapped_column(Enum(InvitationType), nullable=False)
    status: Mapped[InvitationStatus] = mapped_column(Enum(InvitationStatus), nullable=False, default=InvitationStatus.pending)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    engagement: Mapped["Engagement"] = relationship("Engagement", back_populates="invitations")
```

- [ ] **Step 9: Update `app/db/models/__init__.py`**

```python
from app.db.models.buyer_org import BuyerOrg
from app.db.models.engagement import Engagement, EngagementStatus
from app.db.models.engagement_user import EngagementRole, EngagementUser
from app.db.models.invitation import Invitation, InvitationStatus, InvitationType
from app.db.models.seller_account import SellerAccount, SellerAccountStatus
from app.db.models.user import User, UserRole

__all__ = [
    "BuyerOrg", "User", "UserRole", "Engagement", "EngagementStatus",
    "EngagementUser", "EngagementRole", "SellerAccount", "SellerAccountStatus",
    "Invitation", "InvitationStatus", "InvitationType",
]
```

- [ ] **Step 10: Run tests — expect PASS**

```bash
pytest tests/test_models.py -v
```

- [ ] **Step 11: Commit**

```bash
git add app/db/models/ tests/test_models.py
git commit -m "feat: add SQLAlchemy ORM models for all platform entities"
```

---

## Task 4: Alembic Migrations

**Files:**
- Create: `alembic.ini`, `app/db/migrations/env.py`, `app/db/migrations/versions/0001_initial_schema.py`

- [ ] **Step 1: Initialise Alembic**

```bash
alembic init app/db/migrations
```

- [ ] **Step 2: Update `alembic.ini`**

Set `script_location = app/db/migrations` (already set by init).
Set `sqlalchemy.url =` (leave blank — env.py will handle it).

- [ ] **Step 3: Update `app/db/migrations/env.py`**

Replace the generated file with:

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.database import Base
import app.db.models  # noqa: F401 — registers all models with Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Generate the initial migration**

```bash
alembic revision --autogenerate -m "initial_schema"
```

Expected: a file created in `app/db/migrations/versions/` with all six tables.

- [ ] **Step 5: Verify the migration looks correct**

Open the generated file. Confirm it creates tables: `buyer_orgs`, `users`, `engagements`, `engagement_users`, `seller_accounts`, `invitations`. Confirm all enums are present. Confirm foreign keys are correct.

- [ ] **Step 6: Run migration against a local test database**

```bash
# Start a local Postgres (docker or local install)
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost/nova_test \
COGNITO_BUYER_USER_POOL_ID=dummy COGNITO_SELLER_USER_POOL_ID=dummy \
COGNITO_REGION=us-east-1 INVITATION_SECRET_KEY=test-secret-32-chars-minimum!! \
alembic upgrade head
```

Expected: `Running upgrade -> <rev>, initial_schema` with no errors.

- [ ] **Step 7: Commit**

```bash
git add alembic.ini app/db/migrations/
git commit -m "feat: add Alembic migrations for initial schema"
```

---

## Task 5: Auth Service — Cognito JWT Validation

**Files:**
- Create: `app/core/auth.py`, `app/api/dependencies.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write the failing test**

`tests/test_auth.py`:
```python
import time
from unittest.mock import AsyncMock, patch
import pytest
from fastapi import HTTPException

from app.core.auth import validate_token, TokenClaims


def make_claims(sub="user-123", pool="buyer", email="test@example.com", role="buyer"):
    return {
        "sub": sub,
        "email": email,
        "custom:role": role,
        "custom:pool": pool,
        "exp": int(time.time()) + 3600,
    }


@pytest.mark.asyncio
async def test_validate_token_returns_claims_on_valid_token():
    fake_claims = make_claims()
    with patch("app.core.auth._decode_cognito_jwt", new=AsyncMock(return_value=fake_claims)):
        claims = await validate_token("valid.jwt.token")
    assert claims.sub == "user-123"
    assert claims.email == "test@example.com"


@pytest.mark.asyncio
async def test_validate_token_raises_401_on_expired_token():
    with patch("app.core.auth._decode_cognito_jwt", side_effect=Exception("Token expired")):
        with pytest.raises(HTTPException) as exc:
            await validate_token("expired.token")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_validate_token_raises_401_on_invalid_token():
    with patch("app.core.auth._decode_cognito_jwt", side_effect=Exception("Invalid")):
        with pytest.raises(HTTPException) as exc:
            await validate_token("garbage")
    assert exc.value.status_code == 401
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_auth.py -v
```

- [ ] **Step 3: Implement `app/core/auth.py`**

```python
import json
from dataclasses import dataclass
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt

from app.core.config import settings

_bearer = HTTPBearer()


@dataclass
class TokenClaims:
    sub: str
    email: str
    role: str          # org_admin | buyer | external_advisor | seller
    pool: str          # "buyer" | "seller"
    raw: dict


@lru_cache(maxsize=2)
def _get_jwks_url(pool_id: str) -> str:
    region = settings.cognito_region
    return f"https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json"


async def _fetch_jwks(pool_id: str) -> dict:
    url = _get_jwks_url(pool_id)
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=5.0)
        resp.raise_for_status()
        return resp.json()


async def _decode_cognito_jwt(token: str) -> dict:
    # Try buyer pool first, then seller pool
    for pool_id in (settings.cognito_buyer_user_pool_id, settings.cognito_seller_user_pool_id):
        try:
            jwks = await _fetch_jwks(pool_id)
            header = jwt.get_unverified_header(token)
            key = next(k for k in jwks["keys"] if k["kid"] == header["kid"])
            public_key = jwk.construct(key)
            issuer = f"https://cognito-idp.{settings.cognito_region}.amazonaws.com/{pool_id}"
            claims = jwt.decode(token, public_key, algorithms=["RS256"], issuer=issuer)
            claims["custom:pool"] = "seller" if pool_id == settings.cognito_seller_user_pool_id else "buyer"
            return claims
        except Exception:
            continue
    raise ValueError("Token not valid for any known pool")


async def validate_token(token: str) -> TokenClaims:
    try:
        claims = await _decode_cognito_jwt(token)
        return TokenClaims(
            sub=claims["sub"],
            email=claims.get("email", ""),
            role=claims.get("custom:role", "buyer"),
            pool=claims.get("custom:pool", "buyer"),
            raw=claims,
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> TokenClaims:
    return await validate_token(credentials.credentials)
```

- [ ] **Step 4: Update `app/api/dependencies.py`**

```python
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import TokenClaims, get_current_user
from app.core.database import get_db
from app.db.models.user import UserRole


def require_role(*roles: UserRole):
    """FastAPI dependency — raises 403 if current user's role is not in allowed roles."""
    async def _check(current_user: TokenClaims = Depends(get_current_user)) -> TokenClaims:
        if current_user.role not in {r.value for r in roles}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user
    return _check


def org_admin_only():
    return require_role(UserRole.org_admin)
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
pytest tests/test_auth.py -v
```

- [ ] **Step 6: Commit**

```bash
git add app/core/auth.py app/api/dependencies.py tests/test_auth.py
git commit -m "feat: add Cognito JWT validation and role-based dependencies"
```

---

## Task 6: Pydantic Schemas

**Files:**
- Create: `app/schemas/buyer_org.py`, `app/schemas/user.py`, `app/schemas/engagement.py`, `app/schemas/invitation.py`

- [ ] **Step 1: Write the failing test**

`tests/test_schemas.py`:
```python
import uuid
from datetime import datetime, timezone
from app.schemas.engagement import EngagementCreate, EngagementResponse
from app.schemas.invitation import InvitationCreate


def test_engagement_create_requires_name_and_target():
    e = EngagementCreate(name="Deal Alpha", target_company_name="Acme Corp")
    assert e.name == "Deal Alpha"


def test_engagement_create_rejects_empty_name():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        EngagementCreate(name="", target_company_name="Acme")


def test_invitation_create_requires_valid_email():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        InvitationCreate(email="not-an-email", invitation_type="seller")


import pytest
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_schemas.py -v
```

- [ ] **Step 3: Implement `app/schemas/buyer_org.py`**

```python
import uuid
from datetime import datetime
from pydantic import BaseModel, field_validator


class BuyerOrgCreate(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be empty")
        return v.strip()


class BuyerOrgResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str
    created_at: datetime
```

- [ ] **Step 4: Implement `app/schemas/engagement.py`**

```python
import uuid
from datetime import datetime
from pydantic import BaseModel, field_validator
from app.db.models.engagement import EngagementStatus


class EngagementCreate(BaseModel):
    name: str
    target_company_name: str

    @field_validator("name", "target_company_name")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field must not be empty")
        return v.strip()


class EngagementResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    buyer_org_id: uuid.UUID
    name: str
    target_company_name: str
    status: EngagementStatus
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 5: Implement `app/schemas/invitation.py`**

```python
import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr
from app.db.models.invitation import InvitationType, InvitationStatus


class InvitationCreate(BaseModel):
    email: EmailStr
    invitation_type: InvitationType


class InvitationResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    engagement_id: uuid.UUID
    email: str
    invitation_type: InvitationType
    status: InvitationStatus
    expires_at: datetime


class AcceptInvitation(BaseModel):
    token: str
    cognito_sub: str  # set by frontend after Cognito signup completes
```

- [ ] **Step 6: Implement `app/schemas/user.py`**

```python
import uuid
from datetime import datetime
from pydantic import BaseModel
from app.db.models.user import UserRole
from app.db.models.engagement_user import EngagementRole


class UserResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    email: str
    role: UserRole


class EngagementUserAdd(BaseModel):
    user_id: uuid.UUID
    role: EngagementRole


class EngagementUserResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    user_id: uuid.UUID
    engagement_id: uuid.UUID
    role: EngagementRole
```

- [ ] **Step 7: Run tests — expect PASS**

```bash
pytest tests/test_schemas.py -v
```

- [ ] **Step 8: Commit**

```bash
git add app/schemas/ tests/test_schemas.py
git commit -m "feat: add Pydantic schemas for all platform entities"
```

---

## Task 7: Test Fixtures & Conftest

**Files:**
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `tests/conftest.py`**

```python
import asyncio
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import TokenClaims
from app.core.database import Base, get_db
from app.db.models.buyer_org import BuyerOrg
from app.db.models.engagement import Engagement, EngagementStatus
from app.db.models.user import User, UserRole
from app.main import app

TEST_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost/nova_test"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    async with TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    app.dependency_overrides[get_db] = lambda: db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


def make_token_claims(role: str = "buyer", sub: str | None = None, org_id: str | None = None) -> TokenClaims:
    return TokenClaims(
        sub=sub or str(uuid.uuid4()),
        email="test@example.com",
        role=role,
        pool="buyer",
        raw={"custom:org_id": org_id or str(uuid.uuid4())},
    )


@pytest_asyncio.fixture
async def buyer_org(db: AsyncSession) -> BuyerOrg:
    org = BuyerOrg(name="Test PE Firm")
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@pytest_asyncio.fixture
async def org_admin_user(db: AsyncSession, buyer_org: BuyerOrg) -> User:
    user = User(
        buyer_org_id=buyer_org.id,
        cognito_sub=str(uuid.uuid4()),
        email="admin@pe.com",
        role=UserRole.org_admin,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest_asyncio.fixture
async def engagement(db: AsyncSession, buyer_org: BuyerOrg) -> Engagement:
    eng = Engagement(
        buyer_org_id=buyer_org.id,
        name="Deal Alpha",
        target_company_name="Acme Corp",
        status=EngagementStatus.created,
    )
    db.add(eng)
    await db.commit()
    await db.refresh(eng)
    return eng
```

- [ ] **Step 2: Run existing tests to ensure nothing broken**

```bash
pytest tests/test_version_endpoint.py -v
```

Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "feat: add async test fixtures and conftest"
```

---

## Task 8: Buyer Org & Engagement Routes

**Files:**
- Create: `app/api/routes/orgs.py`, `app/api/routes/engagements.py`
- Test: `tests/test_orgs.py`, `tests/test_engagements.py`

- [ ] **Step 1: Write failing org tests**

`tests/test_orgs.py`:
```python
import pytest
from unittest.mock import patch
from app.core.auth import TokenClaims


@pytest.mark.asyncio
async def test_create_org_returns_201(client, make_token_claims):
    claims = make_token_claims(role="org_admin")
    with patch("app.api.routes.orgs.get_current_user", return_value=claims):
        resp = await client.post("/orgs", json={"name": "Apex Partners"})
    assert resp.status_code == 201
    assert resp.json()["name"] == "Apex Partners"
    assert "id" in resp.json()


@pytest.mark.asyncio
async def test_create_org_empty_name_returns_422(client, make_token_claims):
    claims = make_token_claims(role="org_admin")
    with patch("app.api.routes.orgs.get_current_user", return_value=claims):
        resp = await client.post("/orgs", json={"name": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_org_returns_org(client, buyer_org, make_token_claims):
    claims = make_token_claims(role="org_admin")
    with patch("app.api.routes.orgs.get_current_user", return_value=claims):
        resp = await client.get(f"/orgs/{buyer_org.id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == buyer_org.name


@pytest.mark.asyncio
async def test_get_org_not_found_returns_404(client, make_token_claims):
    import uuid
    claims = make_token_claims(role="org_admin")
    with patch("app.api.routes.orgs.get_current_user", return_value=claims):
        resp = await client.get(f"/orgs/{uuid.uuid4()}")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_orgs.py -v
```

- [ ] **Step 3: Implement `app/api/routes/orgs.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, TokenClaims
from app.core.database import get_db
from app.db.models.buyer_org import BuyerOrg
from app.schemas.buyer_org import BuyerOrgCreate, BuyerOrgResponse

router = APIRouter(prefix="/orgs", tags=["orgs"])


@router.post(
    "",
    response_model=BuyerOrgResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a buyer organisation",
)
async def create_org(
    body: BuyerOrgCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: TokenClaims = Depends(get_current_user),
) -> BuyerOrgResponse:
    org = BuyerOrg(name=body.name)
    db.add(org)
    await db.commit()
    await db.refresh(org)
    return org


@router.get(
    "/{org_id}",
    response_model=BuyerOrgResponse,
    summary="Get a buyer organisation",
)
async def get_org(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: TokenClaims = Depends(get_current_user),
) -> BuyerOrgResponse:
    result = await db.execute(select(BuyerOrg).where(BuyerOrg.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")
    return org
```

- [ ] **Step 4: Write failing engagement tests**

`tests/test_engagements.py`:
```python
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_create_engagement_returns_201(client, buyer_org, make_token_claims):
    claims = make_token_claims(role="org_admin")
    with patch("app.api.routes.engagements.get_current_user", return_value=claims):
        resp = await client.post(
            f"/orgs/{buyer_org.id}/engagements",
            json={"name": "Deal Alpha", "target_company_name": "Acme Corp"},
        )
    assert resp.status_code == 201
    assert resp.json()["status"] == "created"
    assert resp.json()["target_company_name"] == "Acme Corp"


@pytest.mark.asyncio
async def test_list_engagements_returns_only_org_engagements(client, buyer_org, engagement, make_token_claims):
    claims = make_token_claims(role="buyer")
    with patch("app.api.routes.engagements.get_current_user", return_value=claims):
        resp = await client.get(f"/orgs/{buyer_org.id}/engagements")
    assert resp.status_code == 200
    ids = [e["id"] for e in resp.json()]
    assert str(engagement.id) in ids


@pytest.mark.asyncio
async def test_get_engagement_returns_correct_data(client, buyer_org, engagement, make_token_claims):
    claims = make_token_claims(role="buyer")
    with patch("app.api.routes.engagements.get_current_user", return_value=claims):
        resp = await client.get(f"/orgs/{buyer_org.id}/engagements/{engagement.id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == engagement.name


@pytest.mark.asyncio
async def test_get_engagement_wrong_org_returns_404(client, buyer_org, engagement, make_token_claims):
    import uuid
    other_org_id = uuid.uuid4()
    claims = make_token_claims(role="buyer")
    with patch("app.api.routes.engagements.get_current_user", return_value=claims):
        resp = await client.get(f"/orgs/{other_org_id}/engagements/{engagement.id}")
    assert resp.status_code == 404
```

- [ ] **Step 5: Implement `app/api/routes/engagements.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import TokenClaims, get_current_user
from app.core.database import get_db
from app.db.models.buyer_org import BuyerOrg
from app.db.models.engagement import Engagement
from app.schemas.engagement import EngagementCreate, EngagementResponse

router = APIRouter(prefix="/orgs/{org_id}/engagements", tags=["engagements"])


async def _get_org_or_404(org_id: uuid.UUID, db: AsyncSession) -> BuyerOrg:
    result = await db.execute(select(BuyerOrg).where(BuyerOrg.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")
    return org


@router.post("", response_model=EngagementResponse, status_code=status.HTTP_201_CREATED,
             summary="Create an engagement within an org")
async def create_engagement(
    org_id: uuid.UUID,
    body: EngagementCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: TokenClaims = Depends(get_current_user),
) -> EngagementResponse:
    await _get_org_or_404(org_id, db)
    eng = Engagement(buyer_org_id=org_id, name=body.name, target_company_name=body.target_company_name)
    db.add(eng)
    await db.commit()
    await db.refresh(eng)
    return eng


@router.get("", response_model=list[EngagementResponse], summary="List engagements for an org")
async def list_engagements(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: TokenClaims = Depends(get_current_user),
) -> list[EngagementResponse]:
    await _get_org_or_404(org_id, db)
    result = await db.execute(select(Engagement).where(Engagement.buyer_org_id == org_id))
    return list(result.scalars().all())


@router.get("/{engagement_id}", response_model=EngagementResponse, summary="Get an engagement")
async def get_engagement(
    org_id: uuid.UUID,
    engagement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: TokenClaims = Depends(get_current_user),
) -> EngagementResponse:
    result = await db.execute(
        select(Engagement).where(Engagement.id == engagement_id, Engagement.buyer_org_id == org_id)
    )
    eng = result.scalar_one_or_none()
    if not eng:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    return eng
```

- [ ] **Step 6: Run org + engagement tests — expect PASS**

```bash
pytest tests/test_orgs.py tests/test_engagements.py -v
```

- [ ] **Step 7: Commit**

```bash
git add app/api/routes/orgs.py app/api/routes/engagements.py \
  tests/test_orgs.py tests/test_engagements.py
git commit -m "feat: add org and engagement CRUD routes"
```

---

## Task 9: Invitation Service & Routes

**Files:**
- Create: `app/services/invitation.py`, `app/services/email.py`, `app/api/routes/invitations.py`
- Test: `tests/test_invitations.py`

- [ ] **Step 1: Write failing tests**

`tests/test_invitations.py`:
```python
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_send_seller_invitation_returns_201(client, buyer_org, engagement, make_token_claims):
    claims = make_token_claims(role="org_admin")
    with patch("app.api.routes.invitations.get_current_user", return_value=claims), \
         patch("app.services.email.send_invitation_email") as mock_email:
        resp = await client.post(
            f"/orgs/{buyer_org.id}/engagements/{engagement.id}/invitations",
            json={"email": "cto@acme.com", "invitation_type": "seller"},
        )
    assert resp.status_code == 201
    assert resp.json()["email"] == "cto@acme.com"
    assert resp.json()["status"] == "pending"
    mock_email.assert_called_once()


@pytest.mark.asyncio
async def test_get_invitation_by_token_returns_info(client, buyer_org, engagement, db, make_token_claims):
    from app.services.invitation import generate_invitation_token
    from app.db.models.invitation import Invitation, InvitationType
    from datetime import datetime, timedelta, timezone
    token = generate_invitation_token()
    inv = Invitation(
        engagement_id=engagement.id,
        email="cto@acme.com",
        token=token,
        invitation_type=InvitationType.seller,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=72),
    )
    db.add(inv)
    await db.commit()
    resp = await client.get(f"/invitations/{token}")
    assert resp.status_code == 200
    assert resp.json()["email"] == "cto@acme.com"


@pytest.mark.asyncio
async def test_accept_invitation_sets_status_accepted(client, buyer_org, engagement, db):
    from app.services.invitation import generate_invitation_token
    from app.db.models.invitation import Invitation, InvitationType
    from datetime import datetime, timedelta, timezone
    import uuid
    token = generate_invitation_token()
    inv = Invitation(
        engagement_id=engagement.id,
        email="cto@acme.com",
        token=token,
        invitation_type=InvitationType.seller,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=72),
    )
    db.add(inv)
    await db.commit()
    resp = await client.post(f"/invitations/{token}/accept", json={"token": token, "cognito_sub": str(uuid.uuid4())})
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"


@pytest.mark.asyncio
async def test_accept_expired_invitation_returns_410(client, buyer_org, engagement, db):
    from app.services.invitation import generate_invitation_token
    from app.db.models.invitation import Invitation, InvitationType
    from datetime import datetime, timedelta, timezone
    import uuid
    token = generate_invitation_token()
    inv = Invitation(
        engagement_id=engagement.id,
        email="cto@acme.com",
        token=token,
        invitation_type=InvitationType.seller,
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # expired
    )
    db.add(inv)
    await db.commit()
    resp = await client.post(f"/invitations/{token}/accept", json={"token": token, "cognito_sub": str(uuid.uuid4())})
    assert resp.status_code == 410
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_invitations.py -v
```

- [ ] **Step 3: Implement `app/services/invitation.py`**

```python
import secrets


def generate_invitation_token() -> str:
    """Generate a 64-character URL-safe token."""
    return secrets.token_urlsafe(48)
```

- [ ] **Step 4: Implement `app/services/email.py`**

```python
import logging

logger = logging.getLogger(__name__)


def send_invitation_email(to_email: str, invitation_token: str, invitation_type: str) -> None:
    """Send invitation email. Stub — replace with SES integration in production."""
    # TODO: integrate with AWS SES
    logger.info("INVITATION EMAIL (stub): to=%s type=%s token=%s", to_email, invitation_type, invitation_token)
```

- [ ] **Step 5: Implement `app/api/routes/invitations.py`**

```python
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import TokenClaims, get_current_user
from app.core.database import get_db
from app.db.models.engagement import Engagement, EngagementStatus
from app.db.models.invitation import Invitation, InvitationStatus, InvitationType
from app.db.models.seller_account import SellerAccount, SellerAccountStatus
from app.core.config import settings
from app.schemas.invitation import AcceptInvitation, InvitationCreate, InvitationResponse
from app.services.email import send_invitation_email
from app.services.invitation import generate_invitation_token
from datetime import timedelta

router = APIRouter(tags=["invitations"])


@router.post(
    "/orgs/{org_id}/engagements/{engagement_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Send an invitation to a seller or advisor",
)
async def send_invitation(
    org_id: uuid.UUID,
    engagement_id: uuid.UUID,
    body: InvitationCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: TokenClaims = Depends(get_current_user),
) -> InvitationResponse:
    result = await db.execute(
        select(Engagement).where(Engagement.id == engagement_id, Engagement.buyer_org_id == org_id)
    )
    engagement = result.scalar_one_or_none()
    if not engagement:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")

    token = generate_invitation_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.invitation_ttl_hours)
    invitation = Invitation(
        engagement_id=engagement_id,
        email=str(body.email),
        token=token,
        invitation_type=body.invitation_type,
        expires_at=expires_at,
    )
    db.add(invitation)

    if body.invitation_type == InvitationType.seller:
        seller = SellerAccount(engagement_id=engagement_id, email=str(body.email))
        db.add(seller)
        engagement.status = EngagementStatus.seller_invited

    await db.commit()
    await db.refresh(invitation)
    send_invitation_email(str(body.email), token, body.invitation_type.value)
    return invitation


@router.get(
    "/invitations/{token}",
    response_model=InvitationResponse,
    summary="Look up an invitation by token (for frontend pre-validation)",
)
async def get_invitation(token: str, db: AsyncSession = Depends(get_db)) -> InvitationResponse:
    result = await db.execute(select(Invitation).where(Invitation.token == token))
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    return invitation


@router.post(
    "/invitations/{token}/accept",
    response_model=InvitationResponse,
    summary="Accept an invitation — called after Cognito signup completes",
)
async def accept_invitation(
    token: str,
    body: AcceptInvitation,
    db: AsyncSession = Depends(get_db),
) -> InvitationResponse:
    result = await db.execute(select(Invitation).where(Invitation.token == token))
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if invitation.status != InvitationStatus.pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invitation already used")
    if invitation.expires_at < datetime.now(timezone.utc):
        invitation.status = InvitationStatus.expired
        await db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invitation has expired")

    invitation.status = InvitationStatus.accepted

    if invitation.invitation_type == InvitationType.seller:
        sel_result = await db.execute(
            select(SellerAccount).where(
                SellerAccount.engagement_id == invitation.engagement_id,
                SellerAccount.email == invitation.email,
            )
        )
        seller = sel_result.scalar_one_or_none()
        if seller:
            seller.cognito_sub = body.cognito_sub
            seller.status = SellerAccountStatus.active

        eng_result = await db.execute(select(Engagement).where(Engagement.id == invitation.engagement_id))
        engagement = eng_result.scalar_one_or_none()
        if engagement:
            engagement.status = EngagementStatus.seller_accepted

    await db.commit()
    await db.refresh(invitation)
    return invitation
```

- [ ] **Step 6: Run tests — expect PASS**

```bash
pytest tests/test_invitations.py -v
```

- [ ] **Step 7: Commit**

```bash
git add app/services/invitation.py app/services/email.py \
  app/api/routes/invitations.py tests/test_invitations.py
git commit -m "feat: add invitation service — send, look up, accept"
```

---

## Task 10: Engagement Users Route

**Files:**
- Create: `app/api/routes/users.py`
- Test: `tests/test_users.py`

- [ ] **Step 1: Write failing tests**

`tests/test_users.py`:
```python
import uuid
import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_add_user_to_engagement_returns_201(client, buyer_org, engagement, org_admin_user, make_token_claims):
    claims = make_token_claims(role="org_admin")
    with patch("app.api.routes.users.get_current_user", return_value=claims):
        resp = await client.post(
            f"/orgs/{buyer_org.id}/engagements/{engagement.id}/users",
            json={"user_id": str(org_admin_user.id), "role": "buyer"},
        )
    assert resp.status_code == 201
    assert resp.json()["role"] == "buyer"


@pytest.mark.asyncio
async def test_add_duplicate_user_returns_409(client, buyer_org, engagement, org_admin_user, db, make_token_claims):
    from app.db.models.engagement_user import EngagementUser, EngagementRole
    eu = EngagementUser(engagement_id=engagement.id, user_id=org_admin_user.id, role=EngagementRole.buyer)
    db.add(eu)
    await db.commit()
    claims = make_token_claims(role="org_admin")
    with patch("app.api.routes.users.get_current_user", return_value=claims):
        resp = await client.post(
            f"/orgs/{buyer_org.id}/engagements/{engagement.id}/users",
            json={"user_id": str(org_admin_user.id), "role": "buyer"},
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_engagement_users(client, buyer_org, engagement, org_admin_user, db, make_token_claims):
    from app.db.models.engagement_user import EngagementUser, EngagementRole
    eu = EngagementUser(engagement_id=engagement.id, user_id=org_admin_user.id, role=EngagementRole.buyer)
    db.add(eu)
    await db.commit()
    claims = make_token_claims(role="buyer")
    with patch("app.api.routes.users.get_current_user", return_value=claims):
        resp = await client.get(f"/orgs/{buyer_org.id}/engagements/{engagement.id}/users")
    assert resp.status_code == 200
    assert any(u["user_id"] == str(org_admin_user.id) for u in resp.json())
```

- [ ] **Step 2: Run — expect FAIL**

```bash
pytest tests/test_users.py -v
```

- [ ] **Step 3: Implement `app/api/routes/users.py`**

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import TokenClaims, get_current_user
from app.core.database import get_db
from app.db.models.engagement import Engagement
from app.db.models.engagement_user import EngagementUser
from app.schemas.user import EngagementUserAdd, EngagementUserResponse

router = APIRouter(prefix="/orgs/{org_id}/engagements/{engagement_id}/users", tags=["users"])


@router.post("", response_model=EngagementUserResponse, status_code=status.HTTP_201_CREATED,
             summary="Add a user to an engagement with a role")
async def add_engagement_user(
    org_id: uuid.UUID,
    engagement_id: uuid.UUID,
    body: EngagementUserAdd,
    db: AsyncSession = Depends(get_db),
    _current_user: TokenClaims = Depends(get_current_user),
) -> EngagementUserResponse:
    result = await db.execute(
        select(Engagement).where(Engagement.id == engagement_id, Engagement.buyer_org_id == org_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")

    eu = EngagementUser(engagement_id=engagement_id, user_id=body.user_id, role=body.role)
    db.add(eu)
    try:
        await db.commit()
        await db.refresh(eu)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already in engagement")
    return eu


@router.get("", response_model=list[EngagementUserResponse], summary="List users in an engagement")
async def list_engagement_users(
    org_id: uuid.UUID,
    engagement_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _current_user: TokenClaims = Depends(get_current_user),
) -> list[EngagementUserResponse]:
    result = await db.execute(
        select(Engagement).where(Engagement.id == engagement_id, Engagement.buyer_org_id == org_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Engagement not found")
    eu_result = await db.execute(select(EngagementUser).where(EngagementUser.engagement_id == engagement_id))
    return list(eu_result.scalars().all())
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
pytest tests/test_users.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/api/routes/users.py tests/test_users.py
git commit -m "feat: add engagement user management routes"
```

---

## Task 11: Wire Up main.py & Update OpenAPI Export

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Update `app/main.py`**

```python
import json
import os
from pathlib import Path

from fastapi import FastAPI

from app.api.routes import engagements, invitations, orgs, users, version

app = FastAPI(
    title="Tech DD Platform",
    description="Technical Due Diligence Platform API",
    version="0.1.0",
    openapi_url="/openapi.json",
)

app.include_router(version.router)
app.include_router(orgs.router)
app.include_router(engagements.router)
app.include_router(invitations.router)
app.include_router(users.router)


@app.on_event("startup")
async def export_openapi() -> None:
    schema = app.openapi()
    out = Path("docs/openapi.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema, indent=2))
```

- [ ] **Step 2: Run all tests**

```bash
pytest tests/ -v
```

Expected: all PASS. If any fail, fix before proceeding.

- [ ] **Step 3: Start the app and verify OpenAPI**

```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost/nova_test \
COGNITO_BUYER_USER_POOL_ID=dummy COGNITO_SELLER_USER_POOL_ID=dummy \
COGNITO_REGION=us-east-1 INVITATION_SECRET_KEY=test-secret-32-chars-minimum!! \
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` — confirm all routes appear: `/orgs`, `/orgs/{org_id}/engagements`, `/invitations/{token}`, etc.

- [ ] **Step 4: Run linting and type checks**

```bash
ruff check app/ tests/
mypy app/ --ignore-missing-imports
```

Fix any errors before committing.

- [ ] **Step 5: Commit**

```bash
git add app/main.py docs/openapi.json
git commit -m "feat: wire all routes into FastAPI app and export OpenAPI schema"
```

---

## Task 12: Terraform — Cognito & RDS

**Files:**
- Create: `infra/main.tf`, `infra/variables.tf`, `infra/outputs.tf`
- Create: `infra/modules/cognito/main.tf`, `infra/modules/cognito/variables.tf`, `infra/modules/cognito/outputs.tf`
- Create: `infra/modules/rds/main.tf`, `infra/modules/rds/variables.tf`, `infra/modules/rds/outputs.tf`

- [ ] **Step 1: Create `infra/modules/cognito/variables.tf`**

```hcl
variable "environment" {
  type        = string
  description = "Deployment environment (staging | production)"
}
```

- [ ] **Step 2: Create `infra/modules/cognito/main.tf`**

```hcl
# Buyer org user pool — for PE firm users (org_admin, buyer, external_advisor)
resource "aws_cognito_user_pool" "buyer" {
  name = "nova-buyer-${var.environment}"

  password_policy {
    minimum_length    = 12
    require_uppercase = true
    require_lowercase = true
    require_numbers   = true
    require_symbols   = true
  }

  schema {
    name                = "role"
    attribute_data_type = "String"
    mutable             = true
    string_attribute_constraints { min_length = "1" max_length = "50" }
  }

  schema {
    name                = "org_id"
    attribute_data_type = "String"
    mutable             = true
    string_attribute_constraints { min_length = "1" max_length = "36" }
  }

  auto_verified_attributes = ["email"]
  username_attributes      = ["email"]
}

resource "aws_cognito_user_pool_client" "buyer" {
  name         = "nova-buyer-client-${var.environment}"
  user_pool_id = aws_cognito_user_pool.buyer.id

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH",
  ]

  prevent_user_existence_errors = "ENABLED"
  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30
}

# Seller user pool — per-engagement seller accounts
resource "aws_cognito_user_pool" "seller" {
  name = "nova-seller-${var.environment}"

  password_policy {
    minimum_length    = 12
    require_uppercase = true
    require_lowercase = true
    require_numbers   = true
    require_symbols   = false
  }

  auto_verified_attributes = ["email"]
  username_attributes      = ["email"]
}

resource "aws_cognito_user_pool_client" "seller" {
  name         = "nova-seller-client-${var.environment}"
  user_pool_id = aws_cognito_user_pool.seller.id

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH",
  ]

  prevent_user_existence_errors = "ENABLED"
  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }
  access_token_validity  = 8
  id_token_validity      = 8
  refresh_token_validity = 7
}
```

- [ ] **Step 3: Create `infra/modules/cognito/outputs.tf`**

```hcl
output "buyer_user_pool_id"     { value = aws_cognito_user_pool.buyer.id }
output "buyer_client_id"        { value = aws_cognito_user_pool_client.buyer.id }
output "seller_user_pool_id"    { value = aws_cognito_user_pool.seller.id }
output "seller_client_id"       { value = aws_cognito_user_pool_client.seller.id }
output "cognito_region"         { value = data.aws_region.current.name }

data "aws_region" "current" {}
```

- [ ] **Step 4: Create `infra/modules/rds/variables.tf`**

```hcl
variable "environment"      { type = string }
variable "db_password"      { type = string; sensitive = true }
variable "vpc_id"           { type = string }
variable "subnet_ids"       { type = list(string) }
variable "app_sg_id"        { type = string; description = "Security group of the ECS app tasks" }
```

- [ ] **Step 5: Create `infra/modules/rds/main.tf`**

```hcl
resource "aws_db_subnet_group" "main" {
  name       = "nova-${var.environment}"
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "rds" {
  name   = "nova-rds-${var.environment}"
  vpc_id = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.app_sg_id]
    description     = "Allow app tasks to reach Postgres"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# cost_notes: db.t3.micro is free-tier eligible. Sufficient for staging.
# Production will require a larger instance — flag for human review before production deploy.
resource "aws_db_instance" "main" {
  identifier             = "nova-${var.environment}"
  engine                 = "postgres"
  engine_version         = "16"
  instance_class         = "db.t3.micro"
  allocated_storage      = 20
  db_name                = "nova"
  username               = "nova"
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  skip_final_snapshot    = var.environment != "production"
  deletion_protection    = var.environment == "production"
  storage_encrypted      = true

  tags = { Environment = var.environment }
}
```

- [ ] **Step 6: Create `infra/modules/rds/outputs.tf`**

```hcl
output "db_endpoint" { value = aws_db_instance.main.endpoint }
output "db_name"     { value = aws_db_instance.main.db_name }
```

- [ ] **Step 7: Create `infra/variables.tf`**

```hcl
variable "environment" { type = string }
variable "aws_region"  { type = string; default = "us-east-1" }
variable "db_password" { type = string; sensitive = true }
variable "vpc_id"      { type = string }
variable "subnet_ids"  { type = list(string) }
variable "app_sg_id"   { type = string }
```

- [ ] **Step 8: Create `infra/main.tf`**

```hcl
terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = { source = "hashicorp/aws"; version = "~> 5.0" }
  }
  backend "s3" {
    bucket         = "nova-terraform-state"
    key            = "nova/${var.environment}/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "nova-terraform-locks"
    encrypt        = true
  }
}

provider "aws" { region = var.aws_region }

module "cognito" {
  source      = "./modules/cognito"
  environment = var.environment
}

module "rds" {
  source      = "./modules/rds"
  environment = var.environment
  db_password = var.db_password
  vpc_id      = var.vpc_id
  subnet_ids  = var.subnet_ids
  app_sg_id   = var.app_sg_id
}
```

- [ ] **Step 9: Create `infra/outputs.tf`**

```hcl
output "buyer_user_pool_id"  { value = module.cognito.buyer_user_pool_id }
output "seller_user_pool_id" { value = module.cognito.seller_user_pool_id }
output "buyer_client_id"     { value = module.cognito.buyer_client_id }
output "seller_client_id"    { value = module.cognito.seller_client_id }
output "db_endpoint"         { value = module.rds.db_endpoint }
```

- [ ] **Step 10: Validate**

```bash
cd infra && terraform init && terraform validate
```

Expected: `Success! The configuration is valid.`

- [ ] **Step 11: Commit**

```bash
git add infra/
git commit -m "feat: add Terraform modules for Cognito user pools and RDS PostgreSQL"
```

---

## Task 13: React Frontend Scaffold

**Files:**
- Create: `frontend/` (full scaffold as described in file map)

- [ ] **Step 1: Scaffold the React app**

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
npm install amazon-cognito-identity-js axios react-router-dom
npm install -D @types/amazon-cognito-identity-js @types/react-router-dom
```

- [ ] **Step 2: Create `frontend/src/types/index.ts`**

```typescript
export interface BuyerOrg {
  id: string;
  name: string;
  created_at: string;
}

export interface Engagement {
  id: string;
  buyer_org_id: string;
  name: string;
  target_company_name: string;
  status: 'created' | 'seller_invited' | 'seller_accepted' | 'active' | 'offboarding' | 'closed' | 'abandoned';
  created_at: string;
  updated_at: string;
}

export interface Invitation {
  id: string;
  engagement_id: string;
  email: string;
  invitation_type: 'seller' | 'advisor';
  status: 'pending' | 'accepted' | 'expired' | 'revoked';
  expires_at: string;
}
```

- [ ] **Step 3: Create `frontend/src/auth/cognito.ts`**

```typescript
import {
  CognitoUserPool,
  CognitoUser,
  AuthenticationDetails,
  CognitoUserSession,
  CognitoUserAttribute,
  ISignUpResult,
} from 'amazon-cognito-identity-js';

export const buyerPool = new CognitoUserPool({
  UserPoolId: import.meta.env.VITE_COGNITO_BUYER_USER_POOL_ID as string,
  ClientId: import.meta.env.VITE_COGNITO_BUYER_CLIENT_ID as string,
});

export const sellerPool = new CognitoUserPool({
  UserPoolId: import.meta.env.VITE_COGNITO_SELLER_USER_POOL_ID as string,
  ClientId: import.meta.env.VITE_COGNITO_SELLER_CLIENT_ID as string,
});

export function signIn(
  email: string,
  password: string,
  pool: CognitoUserPool,
): Promise<CognitoUserSession> {
  return new Promise((resolve, reject) => {
    const user = new CognitoUser({ Username: email, Pool: pool });
    user.authenticateUser(
      new AuthenticationDetails({ Username: email, Password: password }),
      { onSuccess: resolve, onFailure: reject },
    );
  });
}

export function signUp(
  email: string,
  password: string,
  pool: CognitoUserPool,
): Promise<ISignUpResult> {
  return new Promise((resolve, reject) => {
    const attrs = [new CognitoUserAttribute({ Name: 'email', Value: email })];
    pool.signUp(email, password, attrs, [], (err, result) => {
      if (err || !result) return reject(err);
      resolve(result);
    });
  });
}

export function getIdToken(pool: CognitoUserPool): Promise<string | null> {
  return new Promise((resolve) => {
    const user = pool.getCurrentUser();
    if (!user) return resolve(null);
    user.getSession((err: Error | null, session: CognitoUserSession | null) => {
      if (err || !session?.isValid()) return resolve(null);
      resolve(session.getIdToken().getJwtToken());
    });
  });
}

export function signOut(pool: CognitoUserPool): void {
  pool.getCurrentUser()?.signOut();
}
```

- [ ] **Step 4: Create `frontend/src/auth/AuthContext.tsx`**

```typescript
import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from 'react';
import { type CognitoUserSession } from 'amazon-cognito-identity-js';
import { buyerPool } from './cognito';

interface AuthState {
  session: CognitoUserSession | null;
  loading: boolean;
}

const AuthContext = createContext<AuthState>({ session: null, loading: true });

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ session: null, loading: true });

  useEffect(() => {
    const cognitoUser = buyerPool.getCurrentUser();
    if (!cognitoUser) {
      setState({ session: null, loading: false });
      return;
    }
    cognitoUser.getSession((err: Error | null, session: CognitoUserSession | null) => {
      setState({ session: session?.isValid() ? session : null, loading: false });
    });
  }, []);

  return <AuthContext.Provider value={state}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
```

- [ ] **Step 5: Create `frontend/src/api/client.ts`**

```typescript
import axios from 'axios';
import { getIdToken, buyerPool } from '../auth/cognito';

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
});

client.interceptors.request.use(async (config) => {
  const token = await getIdToken(buyerPool);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default client;
```

- [ ] **Step 6: Create `frontend/src/api/engagements.ts`**

```typescript
import client from './client';
import type { Engagement } from '../types';

export const listEngagements = (orgId: string): Promise<Engagement[]> =>
  client.get(`/orgs/${orgId}/engagements`).then((r) => r.data);

export const createEngagement = (
  orgId: string,
  data: { name: string; target_company_name: string },
): Promise<Engagement> =>
  client.post(`/orgs/${orgId}/engagements`, data).then((r) => r.data);
```

- [ ] **Step 7: Create `frontend/src/components/RoleGuard.tsx`**

```typescript
import { Navigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';

interface RoleGuardProps {
  allowedRoles: string[];
  children: React.ReactNode;
}

export function RoleGuard({ allowedRoles: _allowedRoles, children }: RoleGuardProps) {
  const { session, loading } = useAuth();
  if (loading) return null;
  if (!session) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
```

- [ ] **Step 8: Create `frontend/src/pages/Login.tsx`**

```typescript
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { signIn, buyerPool } from '../auth/cognito';

export function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await signIn(email, password, buyerPool);
      navigate('/dashboard');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Sign in failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <h1>Sign In</h1>
      {error && <p role="alert">{error}</p>}
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email"
        required
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        required
      />
      <button type="submit" disabled={submitting}>
        {submitting ? 'Signing in…' : 'Sign In'}
      </button>
    </form>
  );
}
```

- [ ] **Step 9: Create `frontend/src/pages/OrgDashboard.tsx`**

```typescript
import { useEffect, useState } from 'react';
import { listEngagements } from '../api/engagements';
import type { Engagement } from '../types';

export function OrgDashboard({ orgId }: { orgId: string }) {
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listEngagements(orgId)
      .then(setEngagements)
      .finally(() => setLoading(false));
  }, [orgId]);

  if (loading) return <div>Loading engagements…</div>;

  return (
    <div>
      <h1>Engagements</h1>
      {engagements.length === 0 && <p>No engagements yet.</p>}
      <ul>
        {engagements.map((e) => (
          <li key={e.id}>
            <strong>{e.name}</strong> — {e.target_company_name} ({e.status})
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 10: Create `frontend/src/pages/AcceptInvitation.tsx`**

```typescript
import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { signUp, signIn, sellerPool } from '../auth/cognito';
import client from '../api/client';
import type { Invitation } from '../types';

export function AcceptInvitation() {
  const { token } = useParams<{ token: string }>();
  const [invitation, setInvitation] = useState<Invitation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [password, setPassword] = useState('');
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    // Public endpoint — no auth header needed
    client.get(`/invitations/${token}`)
      .then((r) => setInvitation(r.data))
      .catch(() => setError('Invitation not found or expired.'));
  }, [token]);

  const handleAccept = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!invitation) return;
    setSubmitting(true);
    setError(null);
    try {
      // Sign up in the seller pool (account is created on invitation acceptance)
      await signUp(invitation.email, password, sellerPool);
      // Sign in immediately to get a session
      const session = await signIn(invitation.email, password, sellerPool);
      const cognitoSub = session.getIdToken().payload['sub'] as string;
      await client.post(`/invitations/${token}/accept`, { token, cognito_sub: cognitoSub });
      setDone(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to accept invitation');
    } finally {
      setSubmitting(false);
    }
  };

  if (error) return <div role="alert">Error: {error}</div>;
  if (!invitation) return <div>Loading…</div>;
  if (done) return <div>Invitation accepted. You can now access the seller portal.</div>;

  return (
    <div>
      <h1>You have been invited to a Technical Due Diligence engagement</h1>
      <p>Email: {invitation.email}</p>
      <p>Role: {invitation.invitation_type}</p>
      <form onSubmit={handleAccept}>
        <p>Choose a password to create your account:</p>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          required
          minLength={8}
        />
        <button type="submit" disabled={submitting}>
          {submitting ? 'Creating account…' : 'Create account & accept'}
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 11: Create `frontend/src/App.tsx`**

```typescript
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext';
import { Login } from './pages/Login';
import { OrgDashboard } from './pages/OrgDashboard';
import { AcceptInvitation } from './pages/AcceptInvitation';

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/dashboard" element={<OrgDashboard orgId={import.meta.env.VITE_ORG_ID ?? ''} />} />
          <Route path="/invite/:token" element={<AcceptInvitation />} />
          <Route path="*" element={<Login />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
```

- [ ] **Step 12: Verify frontend builds**

```bash
cd frontend && npm run build
```

Expected: build succeeds with no TypeScript errors.

- [ ] **Step 13: Commit**

```bash
git add frontend/
git commit -m "feat: add React frontend scaffold with Cognito auth, org dashboard, seller invite acceptance"
```

---

## Task 14: Full Test Suite Pass & OpenAPI Export

- [ ] **Step 1: Run all tests**

```bash
pytest tests/ -v --tb=short
```

Fix any failures before proceeding. All tests must PASS.

- [ ] **Step 2: Run ruff**

```bash
ruff check app/ tests/
```

Fix all violations.

- [ ] **Step 3: Run mypy**

```bash
mypy app/ --ignore-missing-imports --strict
```

Fix all type errors.

- [ ] **Step 4: Confirm OpenAPI is committed**

```bash
ls docs/openapi.json
```

File must exist and contain all routes introduced in this plan.

- [ ] **Step 5: Final commit**

```bash
git add -u
git commit -m "chore: all tests passing, linting clean, OpenAPI exported for platform foundation"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by task |
|---|---|
| Buyer org model (1.1) | Tasks 3, 6, 8 |
| Role definitions (1.2) | Tasks 3, 5, 6 |
| Annotations model (1.3) | Schema defined; routes deferred to Sub-project 3 (no findings yet) |
| IP protection / advisor elevation (1.4) | Data model in place; elevation workflow deferred to Sub-project 5 |
| Deal outcome data policy (1.5) | Status enums + seller revocation in place; deletion pipeline deferred to Sub-project 5 |
| Auth (Cognito JWT) | Task 5 |
| Engagement lifecycle (Section 3) | Status transitions implemented in Tasks 8, 9 |
| Seller portal scaffold | Task 13 |
| Buyer org dashboard scaffold | Task 13 |
| Invitation flow | Task 9 |
| Terraform Cognito + RDS | Task 12 |
| OpenAPI export | Task 11 |

**Intentionally deferred to later sub-projects (correct):**
- Cloud connectors (Sub-project 2)
- Agents, AI synthesis, scoring (Sub-project 3)
- Advisor elevation workflow with seller confirmation (Sub-project 5)
- Data deletion pipeline for abandoned deals (Sub-project 5)
- Full seller portal with connector wizard (Sub-project 2)
- Full buyer report view (Sub-project 3)
