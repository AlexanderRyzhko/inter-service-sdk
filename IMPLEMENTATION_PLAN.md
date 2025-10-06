# Inter-Service SDK + User API Implementation Plan

## Executive Summary

This plan outlines the creation of a generic inter-service SDK for service-to-service communication, along with backend helpers for AutoLogin and new user management endpoints.

**Goal:** Enable services (like Browser Ninja) to easily communicate with AutoLogin via a clean, generic SDK while simplifying backend endpoint creation.

**Components:**
1. **Inter-Service SDK** - New public PyPI package (generic HTTP client)
2. **Backend Helpers** - Decorators/utilities for creating endpoints easily
3. **User Endpoints** - New APIs for user management and search

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [SDK Design](#sdk-design)
3. [Backend Helpers Design](#backend-helpers-design)
4. [New User Endpoints](#new-user-endpoints)
5. [Implementation Steps](#implementation-steps)
6. [Testing Strategy](#testing-strategy)
7. [Deployment Plan](#deployment-plan)

---

## Architecture Overview

### System Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                     Browser Ninja Service                     │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │         Inter-Service SDK (PyPI Package)                │ │
│  │                                                         │ │
│  │  client = InterServiceClient(                          │ │
│  │      base_url="https://stage.blazel.com",             │ │
│  │      api_key="secret"                                  │ │
│  │  )                                                      │ │
│  │                                                         │ │
│  │  user = client.request(                                │ │
│  │      endpoint="users/{user_id}",                       │ │
│  │      path_params={"user_id": 123}                      │ │
│  │  )                                                      │ │
│  └─────────────────────────────────────────────────────────┘ │
└────────────────────────┬─────────────────────────────────────┘
                         │
                         │ HTTPS + Bearer Token
                         │ Optional ECC Encryption
                         │
                         ▼
┌──────────────────────────────────────────────────────────────┐
│                     AutoLogin Service                         │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  app/routers/inter_service.py                           │ │
│  │                                                         │ │
│  │  router = create_inter_service_router()                │ │
│  │  # Auto sets prefix: /api/v1/inter-service             │ │
│  │                                                         │ │
│  │  @router.get("/users/{user_id}")                       │ │
│  │  @inter_service_endpoint()                             │ │
│  │  async def get_user(user_id: int, db: Session):        │ │
│  │      # Just business logic - rest is automatic         │ │
│  │      user = db.query(User).filter(...).first()         │ │
│  │      return {"user_id": user.id, ...}                  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  app/utils/inter_service_helpers.py                     │ │
│  │  - create_inter_service_router()                        │ │
│  │  - @inter_service_endpoint() decorator                  │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

### Key Principles

1. **SDK is Completely Agnostic**
   - No hardcoded endpoints
   - No service names
   - No business logic
   - Pure generic HTTP client

2. **Consistent Prefix Handling**
   - Default: `/api/v1/inter-service`
   - SDK and backend both use same default
   - Overridable if needed

3. **Automatic Everything**
   - Auth: Bearer token automatic
   - Encryption: Optional, automatic
   - Error handling: Consistent format
   - Logging: Structured with correlation IDs

4. **Clean Separation**
   - SDK: HTTP + Auth + Crypto
   - Backend Helpers: Response format + Error handling + Logging
   - Endpoints: Pure business logic

---

## SDK Design

### Package Information

**Name:** `inter-service-sdk`
**PyPI:** `https://pypi.org/project/inter-service-sdk/`
**Version:** 1.0.0
**License:** MIT

### Core API

#### InterServiceClient

```python
class InterServiceClient:
    """
    Generic HTTP client for inter-service communication.
    Supports bearer token auth and optional ECC encryption.
    """

    def __init__(
        self,
        base_url: str,                          # e.g., "https://stage.blazel.com"
        api_key: str,                           # Bearer token
        api_prefix: str = "/api/v1/inter-service",  # Default prefix
        timeout: int = 30,
        retry_attempts: int = 3,
        ecc_private_key: str = None,            # For decryption
        ecc_public_key: str = None              # For encryption
    ):
        """Initialize generic HTTP client."""

    def request(
        self,
        endpoint: str,                          # "users/{user_id}"
        path_params: dict = None,               # {"user_id": 123}
        query_params: dict = None,              # {"correlation_id": "..."}
        method: str = "GET",                    # GET, POST, PUT, DELETE, PATCH
        data: dict = None,                      # Request body (JSON)
        headers: dict = None,                   # Additional headers
        encrypt: bool = False,                  # Auto-encrypt data
        decrypt: bool = False,                  # Auto-decrypt response
        timeout: int = None,                    # Override timeout
        api_prefix: str = None                  # Override prefix
    ) -> dict:
        """
        Generic HTTP request with path parameter substitution.

        Returns:
            {
                "status": "success" | "error",
                "data": {...} | None,
                "status_code": int,
                "error": None | str
            }
        """
```

### Usage Examples

#### Basic Usage

```python
from inter_service_sdk import InterServiceClient

# Initialize
client = InterServiceClient(
    base_url="https://stage.blazel.com",
    api_key=os.getenv("INTER_SERVICE_SECRET")
)

# Get user
user = client.request(
    endpoint="users/{user_id}",
    path_params={"user_id": 123}
)
# Calls: GET https://stage.blazel.com/api/v1/inter-service/users/123

print(user["data"]["first_name"])
```

#### With Encryption

```python
# Initialize with ECC keys
client = InterServiceClient(
    base_url="https://stage.blazel.com",
    api_key=os.getenv("INTER_SERVICE_SECRET"),
    ecc_private_key=os.getenv("SERVICE_PRIVATE_KEY"),
    ecc_public_key=os.getenv("AUTOLOGIN_PUBLIC_KEY")
)

# Get credentials (auto-decrypted)
creds = client.request(
    endpoint="credentials/{platform}/{account_id}",
    path_params={"platform": "linkedin", "account_id": 456},
    query_params={"correlation_id": "verify-456"},
    decrypt=True
)

password = creds["data"]["credentials"]["password"]  # Decrypted automatically
```

#### Search with Query Parameters

```python
# Search users
results = client.request(
    endpoint="users/search",
    query_params={
        "q": "john@example.com",
        "type": "user_email",
        "limit": 10
    }
)

for user in results["data"]["results"]:
    print(f"{user['first_name']} {user['last_name']}")
```

#### POST Request with Encryption

```python
# Update cookies (auto-encrypted)
result = client.request(
    endpoint="callbacks/cookies_update/{platform}/{account_id}",
    path_params={"platform": "linkedin", "account_id": 456},
    method="POST",
    data={
        "cookies": [...],
        "user_agent": "Mozilla/5.0...",
        "status": "success",
        "correlation_id": "verify-456"
    },
    encrypt=True
)
```

### File Structure

```
inter-service-sdk/
├── .gitignore
├── .github/
│   └── workflows/
│       └── publish.yml              # Auto-publish to PyPI
├── README.md                        # Usage documentation
├── IMPLEMENTATION_PLAN.md           # This file
├── LICENSE                          # MIT License
├── setup.py                         # PyPI setup (legacy)
├── pyproject.toml                   # Modern Python packaging
├── requirements.txt                 # Runtime dependencies
├── requirements-dev.txt             # Development dependencies
├── inter_service_sdk/
│   ├── __init__.py                  # Package exports
│   ├── client.py                    # InterServiceClient
│   ├── crypto.py                    # ECC encrypt/decrypt
│   ├── exceptions.py                # Custom exceptions
│   └── utils.py                     # URL building, etc.
├── tests/
│   ├── __init__.py
│   ├── test_client.py               # Client tests
│   ├── test_crypto.py               # Crypto tests
│   └── test_utils.py                # Utility tests
└── examples/
    ├── basic_usage.py               # Simple GET request
    ├── with_encryption.py           # With ECC encryption
    ├── search_example.py            # Search with query params
    └── post_example.py              # POST request
```

### Dependencies

**Runtime:**
- `requests>=2.31.0` - HTTP client
- `cryptography>=41.0.0` - ECC encryption

**Development:**
- `pytest>=7.4.0`
- `pytest-cov>=4.1.0`
- `black>=23.0.0`
- `mypy>=1.5.0`

---

## Backend Helpers Design

### Purpose

Simplify creating inter-service endpoints by handling:
- Authentication (via router dependency)
- Response formatting
- Error handling
- Logging
- Optional encryption/decryption

### Helper Functions

#### create_inter_service_router()

```python
def create_inter_service_router(prefix: str = "/api/v1/inter-service") -> APIRouter:
    """
    Create FastAPI router for inter-service endpoints.

    Automatically sets:
    - Prefix: /api/v1/inter-service (default)
    - Auth: require_inter_service_auth dependency
    - Tags: ["Inter-Service API"]

    Returns:
        Configured APIRouter
    """
    return APIRouter(
        prefix=prefix,
        tags=["Inter-Service API"],
        dependencies=[Depends(require_inter_service_auth)]
    )
```

#### @inter_service_endpoint() Decorator

```python
def inter_service_endpoint(
    auto_decrypt: bool = False,
    auto_encrypt: bool = False,
    require_db: bool = True
):
    """
    Decorator for inter-service endpoints.

    Handles:
    - Response formatting: {"status": "success", "data": ...}
    - Error handling: ValueError -> error response, Exception -> 500
    - Logging: Request start/end with correlation ID
    - DB injection: Session from get_db()
    - Optional encryption/decryption

    Args:
        auto_decrypt: Auto-decrypt request body if encrypted
        auto_encrypt: Auto-encrypt response data
        require_db: Inject database session
    """
```

### Usage

#### Before (Manual - Verbose)

```python
@router.get("/users/{user_id}")
async def get_user_details(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    auth: dict = Depends(require_inter_service_auth)
):
    try:
        logger.info(f"Get user request for ID: {user_id}")
        logger.info(f"Client: {auth.get('client_ip')}")

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logger.warning(f"User {user_id} not found")
            return {
                "status": "error",
                "error": "User not found",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        logger.info(f"Successfully retrieved user {user_id}")
        return {
            "status": "success",
            "data": {
                "user_id": user.id,
                "first_name": user.first_name,
                "email": user.email
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
```

#### After (With Helper - Clean)

```python
router = create_inter_service_router()  # Sets prefix + auth

@router.get("/users/{user_id}")
@inter_service_endpoint()
async def get_user_details(user_id: int, db: Session):
    """Get user with all platform accounts."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")  # Auto-formatted as error response

    return {
        "user_id": user.id,
        "first_name": user.first_name,
        "email": user.email
    }
```

**Code Reduction:** ~70% less boilerplate

### File Location

```
app/utils/inter_service_helpers.py
```

---

## New User Endpoints

### Endpoint 1: Get User Details

**Path:** `GET /api/v1/inter-service/users/{user_id}`

**Purpose:** Retrieve user information with all associated platform accounts.

**Parameters:**
- `user_id` (path, int) - User ID

**Response:**
```json
{
  "status": "success",
  "data": {
    "user_id": 123,
    "first_name": "John",
    "last_name": "Doe",
    "email": "john@example.com",
    "platforms": [
      {
        "platform": "linkedin",
        "account_id": 456,
        "account_email": "john.work@linkedin.com",
        "is_verified": true,
        "last_verification": "2025-10-06T12:00:00Z"
      },
      {
        "platform": "linkedin",
        "account_id": 789,
        "account_email": "john.personal@gmail.com",
        "is_verified": true,
        "last_verification": "2025-10-05T10:00:00Z"
      }
    ]
  },
  "timestamp": "2025-10-06T12:00:00Z"
}
```

**Error Response:**
```json
{
  "status": "error",
  "error": "User not found",
  "timestamp": "2025-10-06T12:00:00Z"
}
```

### Endpoint 2: Search Users

**Path:** `GET /api/v1/inter-service/users/search`

**Purpose:** Search users by email, name, or account email.

**Query Parameters:**
- `q` (string, required) - Search query
- `type` (string, optional) - Search type: "user_email" | "account_email" | "name" | "all" (default: "all")
- `limit` (int, optional) - Max results (default: 50)

**Response:**
```json
{
  "status": "success",
  "data": {
    "results": [
      {
        "user_id": 123,
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "platforms": [
          {
            "platform": "linkedin",
            "account_id": 456,
            "account_email": "john.work@linkedin.com"
          }
        ]
      }
    ],
    "total": 1,
    "query": "john",
    "type": "all"
  },
  "timestamp": "2025-10-06T12:00:00Z"
}
```

### Implementation

```python
# app/routers/inter_service.py

from sqlalchemy import or_
from app.utils.inter_service_helpers import create_inter_service_router, inter_service_endpoint

router = create_inter_service_router()

@router.get("/users/{user_id}")
@inter_service_endpoint()
async def get_user_details(user_id: int, db: Session):
    """Get user with all platform accounts."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError("User not found")

    accounts = db.query(LinkedInAccount).filter(
        LinkedInAccount.user_id == user_id
    ).all()

    return {
        "user_id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "platforms": [
            {
                "platform": "linkedin",
                "account_id": acc.id,
                "account_email": acc.email,
                "is_verified": acc.is_verified,
                "last_verification": acc.last_verification.isoformat() if acc.last_verification else None
            }
            for acc in accounts
        ]
    }

@router.get("/users/search")
@inter_service_endpoint()
async def search_users(
    q: str,
    type: str = "all",
    limit: int = 50,
    db: Session = None
):
    """Search users by email, name, or account email."""
    results = []

    # Search by user email
    if type in ["user_email", "all"]:
        users = db.query(User).filter(User.email.ilike(f"%{q}%")).limit(limit).all()
        results.extend(users)

    # Search by name
    if type in ["name", "all"]:
        users = db.query(User).filter(
            or_(
                User.first_name.ilike(f"%{q}%"),
                User.last_name.ilike(f"%{q}%")
            )
        ).limit(limit).all()
        results.extend(users)

    # Search by account email
    if type in ["account_email", "all"]:
        accounts = db.query(LinkedInAccount).filter(
            LinkedInAccount.email.ilike(f"%{q}%")
        ).limit(limit).all()
        user_ids = set(acc.user_id for acc in accounts)
        users = db.query(User).filter(User.id.in_(user_ids)).all()
        results.extend(users)

    # Deduplicate users
    unique_users = {user.id: user for user in results}

    # Build response with platforms
    search_results = []
    for user in unique_users.values():
        accounts = db.query(LinkedInAccount).filter(
            LinkedInAccount.user_id == user.id
        ).all()

        search_results.append({
            "user_id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "platforms": [
                {
                    "platform": "linkedin",
                    "account_id": acc.id,
                    "account_email": acc.email
                }
                for acc in accounts
            ]
        })

    return {
        "results": search_results,
        "total": len(search_results),
        "query": q,
        "type": type
    }
```

---

## Implementation Steps

### Phase 1: SDK Repository Setup

#### Step 1.1: Create Repository
```bash
cd /Users/lex-tech/Documents/dev/blazel/
mkdir inter-service-sdk
cd inter-service-sdk
git init
git checkout -b main
```

#### Step 1.2: Create Basic Files
- `.gitignore`
- `README.md`
- `LICENSE` (MIT)
- Copy this `IMPLEMENTATION_PLAN.md`

#### Step 1.3: Create Package Structure
```bash
mkdir -p inter_service_sdk tests examples
touch inter_service_sdk/__init__.py
touch inter_service_sdk/client.py
touch inter_service_sdk/crypto.py
touch inter_service_sdk/exceptions.py
touch inter_service_sdk/utils.py
touch tests/__init__.py
```

#### Step 1.4: Initial Commit
```bash
git add .
git commit -m "Initial SDK structure"
```

### Phase 2: SDK Core Implementation

#### Step 2.1: Implement Exceptions
File: `inter_service_sdk/exceptions.py`

#### Step 2.2: Implement Utils
File: `inter_service_sdk/utils.py`
- URL building
- Parameter substitution

#### Step 2.3: Implement Crypto
File: `inter_service_sdk/crypto.py`
- ECC encryption
- ECC decryption

#### Step 2.4: Implement Client
File: `inter_service_sdk/client.py`
- `InterServiceClient` class
- `request()` method

#### Step 2.5: Package Exports
File: `inter_service_sdk/__init__.py`

### Phase 3: SDK Packaging

#### Step 3.1: Create setup.py
#### Step 3.2: Create pyproject.toml
#### Step 3.3: Create requirements.txt

### Phase 4: SDK Testing

#### Step 4.1: Write Client Tests
File: `tests/test_client.py`

#### Step 4.2: Write Crypto Tests
File: `tests/test_crypto.py`

#### Step 4.3: Run Tests
```bash
pytest tests/ -v
```

### Phase 5: SDK Examples

#### Step 5.1: Basic Usage Example
File: `examples/basic_usage.py`

#### Step 5.2: Encryption Example
File: `examples/with_encryption.py`

### Phase 6: Backend Helpers

#### Step 6.1: Implement Helpers
File: `app/utils/inter_service_helpers.py`
- `create_inter_service_router()`
- `inter_service_endpoint()` decorator

#### Step 6.2: Test Helpers
File: `tests/test_inter_service_helpers.py`

### Phase 7: New User Endpoints

#### Step 7.1: Refactor Router
File: `app/routers/inter_service.py`
- Use `create_inter_service_router()`
- Apply `@inter_service_endpoint()` to existing endpoints

#### Step 7.2: Add User Endpoints
- GET `/users/{user_id}`
- GET `/users/search`

#### Step 7.3: Test Endpoints
File: `tests/test_inter_service_users.py`

### Phase 8: Integration & Documentation

#### Step 8.1: Integration Testing
- SDK calling AutoLogin endpoints
- End-to-end encryption test

#### Step 8.2: Update Documentation
- Update CLAUDE.md
- API documentation

### Phase 9: Deployment

#### Step 9.1: Deploy to Stage
```bash
./deploy-stage.sh
```

#### Step 9.2: Verify Endpoints
```bash
curl -H "Authorization: Bearer $SECRET" \
  https://stage.blazel.com/api/v1/inter-service/users/1
```

#### Step 9.3: Publish SDK to PyPI
```bash
python setup.py sdist bdist_wheel
twine upload dist/*
```

---

## Testing Strategy

### SDK Tests

#### Unit Tests
- URL building with path/query params
- Request method (GET, POST, PUT, DELETE)
- Error handling
- Retry logic
- Header injection

#### Integration Tests
- Mock HTTP server
- Real encryption/decryption
- End-to-end request flow

### Backend Tests

#### Unit Tests
- Router creation
- Endpoint decorator
- Error formatting
- Response formatting

#### Integration Tests
- Full endpoint tests
- Database queries
- Authentication
- Search functionality

### Test Coverage Goal
- SDK: >90%
- Backend: >85%

---

## Deployment Plan

### Stage Environment

1. **Deploy Backend Changes**
   ```bash
   git checkout stage
   git merge feat-user-api
   ./deploy-stage.sh
   ```

2. **Verify Endpoints**
   ```bash
   # Test user endpoint
   curl -H "Authorization: Bearer $SECRET" \
     https://stage.blazel.com/api/v1/inter-service/users/1

   # Test search
   curl -H "Authorization: Bearer $SECRET" \
     "https://stage.blazel.com/api/v1/inter-service/users/search?q=test"
   ```

3. **Publish SDK**
   ```bash
   cd inter-service-sdk
   python -m build
   twine upload --repository testpypi dist/*  # Test first
   twine upload dist/*  # Production
   ```

4. **Update Browser Ninja**
   ```bash
   pip install inter-service-sdk
   # Update to use new SDK + new endpoints
   ```

### Production Deployment

1. Test thoroughly in stage
2. Merge to main
3. Deploy to production
4. Monitor logs
5. Verify with Browser Ninja

---

## Success Metrics

### SDK
- ✅ Published to PyPI
- ✅ Installable via `pip install inter-service-sdk`
- ✅ Zero dependencies on AutoLogin specifics
- ✅ >90% test coverage

### Backend
- ✅ All endpoints use helpers
- ✅ Code reduction >70%
- ✅ Consistent error/response format
- ✅ >85% test coverage

### User Endpoints
- ✅ Get user by ID working
- ✅ Search by email/name/account working
- ✅ <200ms response time
- ✅ Proper pagination

### Integration
- ✅ SDK successfully calls all endpoints
- ✅ Encryption working end-to-end
- ✅ Browser Ninja integration complete
- ✅ Zero production errors

---

## Timeline

**Total Estimated Time:** 11.5 hours

| Phase | Task | Time | Status |
|-------|------|------|--------|
| 1 | SDK Repo Setup | 30min | Pending |
| 2 | SDK Core Implementation | 2hr | Pending |
| 3 | SDK Packaging | 1hr | Pending |
| 4 | SDK Testing | 1.5hr | Pending |
| 5 | SDK Examples | 30min | Pending |
| 6 | Backend Helpers | 1hr | Pending |
| 7 | New User Endpoints | 2hr | Pending |
| 8 | Backend Tests | 1hr | Pending |
| 9 | Integration & Docs | 1hr | Pending |
| 10 | Deployment | 1hr | Pending |

---

## Appendix

### A. URL Building Examples

```python
# Example 1: Simple path params
endpoint = "users/{user_id}"
path_params = {"user_id": 123}
# Result: /api/v1/inter-service/users/123

# Example 2: Multiple path params
endpoint = "credentials/{platform}/{account_id}"
path_params = {"platform": "linkedin", "account_id": 456}
# Result: /api/v1/inter-service/credentials/linkedin/456

# Example 3: With query params
endpoint = "users/search"
query_params = {"q": "john", "type": "email", "limit": 10}
# Result: /api/v1/inter-service/users/search?q=john&type=email&limit=10
```

### B. Error Response Formats

```json
{
  "status": "error",
  "error": "User not found",
  "timestamp": "2025-10-06T12:00:00Z"
}
```

### C. Success Response Format

```json
{
  "status": "success",
  "data": {
    "user_id": 123,
    "name": "John Doe"
  },
  "timestamp": "2025-10-06T12:00:00Z"
}
```

---

## Version History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2025-10-06 | Claude | Initial plan |

---

## Contact & Support

**Questions?** Open an issue in the SDK repository.

**Contributing:** See CONTRIBUTING.md in SDK repo.
