# Inter-Service SDK

Generic HTTP client for secure service-to-service communication with bearer token authentication and optional ECC encryption.

## Features

- 🔐 **Bearer Token Auth** - Automatic authentication headers
- 🔒 **Optional ECC Encryption** - End-to-end encryption for sensitive data
- 🎯 **Path & Query Parameters** - Clean parameter substitution
- 🔄 **Automatic Retries** - Exponential backoff for failed requests
- 📝 **Structured Logging** - Request/response tracking
- 🚀 **Zero Dependencies** - Only requests and cryptography (optional)

## Installation

```bash
pip install inter-service-sdk
```

## Quick Start

```python
from inter_service_sdk import InterServiceClient

# Initialize client
client = InterServiceClient(
    base_url="https://api.example.com",
    api_key="your-secret-key"
)

# Make a request (correlation_id auto-generated)
response = client.request(
    endpoint="users/{user_id}",
    path_params={"user_id": 123}
)

if response["status"] == "success":
    print(response["data"])
else:
    print(f"Error: {response['error']}")
```

## Usage

### Basic GET Request

```python
client = InterServiceClient(
    base_url="https://api.example.com",
    api_key="your-api-key"
)

# GET /api/v1/inter-service/users/123
# correlation_id auto-generated
response = client.request(
    endpoint="users/{user_id}",
    path_params={"user_id": 123}
)
```

### With Query Parameters

```python
# GET /api/v1/inter-service/users/search?q=john&type=email&limit=10
# correlation_id auto-generated and added to query params
response = client.request(
    endpoint="users/search",
    query_params={
        "q": "john",
        "type": "email",
        "limit": 10
    }
)

# Custom correlation_id (optional)
response = client.request(
    endpoint="users/search",
    query_params={
        "q": "john",
        "correlation_id": "my-custom-id-123"
    }
)
```

### POST Request

```python
# POST /api/v1/inter-service/users
new_user = client.request(
    endpoint="users",
    method="POST",
    data={
        "name": "John Doe",
        "email": "john@example.com"
    }
)
```

### With ECC Encryption

```python
client = InterServiceClient(
    base_url="https://api.example.com",
    api_key="your-api-key",
    ecc_private_key=os.getenv("PRIVATE_KEY"),
    ecc_public_key=os.getenv("PUBLIC_KEY")
)

# Auto-decrypt response
credentials = client.request(
    endpoint="credentials/{id}",
    path_params={"id": 456},
    decrypt=True
)

# Auto-encrypt request
client.request(
    endpoint="secrets",
    method="POST",
    data={"secret": "sensitive data"},
    encrypt=True
)
```

### Custom API Prefix

```python
# Default prefix: /api/v1/inter-service
client = InterServiceClient(
    base_url="https://api.example.com",
    api_key="key",
    api_prefix="/v2/api"  # Custom prefix
)

# Override per request
response = client.request(
    endpoint="custom",
    api_prefix="/internal"
)
```

## Server-Side Utilities

The SDK also provides FastAPI utilities for creating REST-compliant inter-service endpoints.

### Creating a Router

```python
from fastapi import FastAPI, Depends
from inter_service_sdk.server import create_inter_service_router, inter_service_endpoint

# Create router with authentication
router = create_inter_service_router(
    auth_dependency=Depends(your_auth_function)
)

app = FastAPI()
app.include_router(router)
```

### Creating Endpoints

```python
from fastapi import Request, HTTPException
from sqlalchemy.orm import Session

@router.get("/users/{user_id}")
@inter_service_endpoint("get_user")
async def get_user(
    user_id: int,
    correlation_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    # Business logic only - SDK handles logging and errors
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {"id": user.id, "name": user.name}  # Direct return
```

### Features

- **Automatic Logging**: Request/response logging with correlation IDs
- **Error Handling**: Converts exceptions to proper HTTP status codes
- **REST Standard**: Returns data directly (200) or raises HTTPException (404, 500)
- **Authentication**: Configurable auth dependency for entire router

### Response Format

- **Success**: Return data directly → FastAPI returns HTTP 200 with data
- **Errors**: Raise HTTPException → FastAPI returns HTTP 404/500 with error detail

```python
# ✅ Correct
return {"user_id": 123, "name": "John"}

# ✅ Correct
raise HTTPException(status_code=404, detail="Not found")

# ❌ Incorrect - Don't wrap in envelope
return {"status": "success", "data": {...}}
```

## API Reference

### InterServiceClient

```python
InterServiceClient(
    base_url: str,
    api_key: str,
    api_prefix: str = "/api/v1/inter-service",
    timeout: int = 30,
    retry_attempts: int = 3,
    ecc_private_key: str = None,
    ecc_public_key: str = None
)
```

#### Parameters

- `base_url` (str): Base URL of the API (e.g., "https://api.example.com")
- `api_key` (str): Bearer token for authentication
- `api_prefix` (str, optional): API prefix. Default: "/api/v1/inter-service"
- `timeout` (int, optional): Request timeout in seconds. Default: 30
- `retry_attempts` (int, optional): Number of retry attempts. Default: 3
- `ecc_private_key` (str, optional): ECC private key for decryption
- `ecc_public_key` (str, optional): ECC public key for encryption

### request()

```python
client.request(
    endpoint: str,
    path_params: dict = None,
    query_params: dict = None,
    method: str = "GET",
    data: dict = None,
    headers: dict = None,
    encrypt: bool = False,
    decrypt: bool = False,
    timeout: int = None,
    api_prefix: str = None
) -> dict
```

#### Parameters

- `endpoint` (str): Endpoint template (e.g., "users/{user_id}")
- `path_params` (dict, optional): Path parameters for substitution
- `query_params` (dict, optional): Query string parameters
- `method` (str, optional): HTTP method. Default: "GET"
- `data` (dict, optional): Request body (JSON)
- `headers` (dict, optional): Additional headers
- `encrypt` (bool, optional): Auto-encrypt request data. Default: False
- `decrypt` (bool, optional): Auto-decrypt response. Default: False
- `timeout` (int, optional): Override default timeout
- `api_prefix` (str, optional): Override default API prefix

#### Returns

```python
{
    "status": "success" | "error",
    "data": {...} | None,
    "status_code": int,
    "error": None | str
}
```

## Error Handling

```python
response = client.request(endpoint="users/123")

if response["status"] == "success":
    user = response["data"]
    print(user)
else:
    print(f"Error: {response['error']}")
    print(f"Status code: {response['status_code']}")
```

## Configuration

### Environment Variables

```bash
# Recommended approach
export API_BASE_URL="https://api.example.com"
export API_KEY="your-secret-key"
export ECC_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----..."
export ECC_PUBLIC_KEY="-----BEGIN PUBLIC KEY-----..."
```

```python
import os
from inter_service_sdk import InterServiceClient

client = InterServiceClient(
    base_url=os.getenv("API_BASE_URL"),
    api_key=os.getenv("API_KEY"),
    ecc_private_key=os.getenv("ECC_PRIVATE_KEY"),
    ecc_public_key=os.getenv("ECC_PUBLIC_KEY")
)
```

## Development

### Install Development Dependencies

```bash
pip install -r requirements-dev.txt
```

### Run Tests

```bash
pytest tests/ -v
```

### Run Tests with Coverage

```bash
pytest tests/ --cov=inter_service_sdk --cov-report=html
```

### Code Formatting

```bash
black inter_service_sdk tests
```

### Type Checking

```bash
mypy inter_service_sdk
```

## Examples

See the `examples/` directory for more usage examples:

- `basic_usage.py` - Simple GET request
- `with_encryption.py` - ECC encryption example
- `search_example.py` - Query parameters example
- `post_example.py` - POST request example

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## Support

For questions or issues, please open a GitHub issue.
