# Inter-Service SDK Examples

This directory contains comprehensive examples demonstrating how to use the inter-service-sdk.

## Prerequisites

Install the SDK with optional dependencies:

```bash
# Basic installation
pip install inter-service-sdk

# With encryption support
pip install inter-service-sdk[crypto]

# Development installation
pip install inter-service-sdk[dev]
```

## Examples

### 1. Basic Usage (`basic_usage.py`)

Demonstrates fundamental SDK functionality:
- Client initialization
- GET, POST, PUT, DELETE requests
- Path and query parameters
- Custom headers and timeouts
- Error handling
- API prefix customization

**Run:**
```bash
python examples/basic_usage.py
```

**Key Concepts:**
- Simple client setup with base URL and API key
- Making requests to different endpoints
- Handling responses and errors
- Customizing request behavior

### 2. With Encryption (`with_encryption.py`)

Shows how to use end-to-end encryption:
- ECC key pair generation (P-256)
- Encrypting request data
- Decrypting response data
- Security best practices
- Error handling with encryption
- Correlation IDs

**Run:**
```bash
# Requires crypto dependencies
pip install inter-service-sdk[crypto]
python examples/with_encryption.py
```

**Key Concepts:**
- Secure credential transmission
- ECC P-256 + ECDH-ES + AES-256-GCM encryption
- Public/private key management
- When to use encryption vs. plain requests

## Quick Start

### Basic Request Example

```python
from inter_service_sdk import InterServiceClient

# Initialize client
client = InterServiceClient(
    base_url="https://api.example.com",
    api_key="your-secret-key"
)

# Make a GET request
response = client.request(
    endpoint="users/{user_id}",
    path_params={"user_id": 123},
    query_params={"correlation_id": "req-001"}
)

if response["status"] == "success":
    print(response["data"])
else:
    print(f"Error: {response['error']}")
```

### Encrypted Request Example

```python
from inter_service_sdk import InterServiceClient

# Initialize client with encryption keys
client = InterServiceClient(
    base_url="https://api.example.com",
    api_key="your-secret-key",
    ecc_public_key=PUBLIC_KEY_PEM,  # Server's public key
    ecc_private_key=PRIVATE_KEY_PEM  # Your private key
)

# POST with encrypted data
response = client.request(
    endpoint="credentials/store",
    method="POST",
    data={
        "username": "user@example.com",
        "password": "secret"
    },
    encrypt=True,  # Encrypt the request
    query_params={"correlation_id": "store-001"}
)
```

## Response Format

All requests return a consistent response structure:

```python
{
    "status": "success" | "error",
    "data": {...} | None,
    "status_code": int | None,
    "error": str | None
}
```

## Configuration Options

### Client Initialization

```python
client = InterServiceClient(
    base_url="https://api.example.com",       # Required: Service base URL
    api_key="your-api-key",                   # Required: Bearer token
    api_prefix="/api/v1/inter-service",       # Optional: Default API prefix
    timeout=30,                                # Optional: Request timeout (seconds)
    retry_attempts=3,                          # Optional: Number of retries
    ecc_private_key=PRIVATE_KEY_PEM,          # Optional: For decryption
    ecc_public_key=PUBLIC_KEY_PEM             # Optional: For encryption
)
```

### Request Parameters

```python
response = client.request(
    endpoint="users/{user_id}",               # Endpoint with optional placeholders
    path_params={"user_id": 123},             # Path parameter substitution
    query_params={"limit": 10},               # Query string parameters
    method="GET",                             # HTTP method
    data={"key": "value"},                    # Request body (JSON)
    headers={"X-Custom": "value"},            # Additional headers
    encrypt=False,                            # Encrypt request data
    decrypt=False,                            # Decrypt response data
    timeout=60,                               # Override default timeout
    api_prefix="/v2/custom"                   # Override default prefix
)
```

## Security Notes

### ECC Key Management

1. **Generate Keys:**
```python
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

private_key = ec.generate_private_key(ec.SECP256R1())
public_key = private_key.public_key()

private_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()
).decode('utf-8')

public_pem = public_key.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
).decode('utf-8')
```

2. **Store Securely:**
   - Use environment variables or secrets management (AWS Secrets Manager, HashiCorp Vault, etc.)
   - Never commit keys to version control
   - Use different keys for different environments

3. **Share Keys:**
   - Share only public keys with other services
   - Keep private keys confidential
   - Rotate keys periodically

### When to Use Encryption

**✅ Use encryption for:**
- Passwords, API keys, tokens
- Personal Identifiable Information (PII)
- Financial data
- Any confidential business data

**⚡ Skip encryption for:**
- Public data
- Non-sensitive metadata
- When TLS already provides sufficient security and performance is critical

## Error Handling

The SDK handles errors gracefully and returns structured error responses:

```python
response = client.request(endpoint="invalid")

if response["status"] == "error":
    print(f"Status Code: {response['status_code']}")  # HTTP status or None
    print(f"Error Message: {response['error']}")      # Error description
```

Common error scenarios:
- **401 Unauthorized**: Invalid API key
- **404 Not Found**: Endpoint or resource doesn't exist
- **500 Server Error**: Backend service error
- **Timeout**: Request exceeded timeout limit
- **Network Error**: Connection failed

## Testing

Run the examples (they use placeholder URLs and will show expected errors):

```bash
# Basic examples
python examples/basic_usage.py

# Encryption examples (requires crypto package)
pip install inter-service-sdk[crypto]
python examples/with_encryption.py
```

## Additional Resources

- **GitHub**: https://github.com/AlexanderRyzhko/inter-service-sdk
- **Documentation**: See main README.md
- **Tests**: See `tests/` directory for more usage examples

## Support

For issues or questions:
- Open an issue on GitHub
- Review test files for more examples
- Check main README.md for detailed documentation