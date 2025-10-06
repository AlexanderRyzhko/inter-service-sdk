"""
Encryption usage examples for inter-service-sdk.

This example demonstrates:
- Client initialization with ECC keys
- Encrypting request data
- Decrypting response data
- Generating ECC key pairs
- Error handling with encryption
"""

from inter_service_sdk import InterServiceClient


# Example ECC key pair (P-256)
# In production, generate these securely and store them in environment variables or secrets manager
PRIVATE_KEY_PEM = """-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgkkNCYxSXNX66ZeZI
QVYGkGl02JgzgE722kz3f4Clg9yhRANCAATrxUsmhsMFnBIN5iANHfNsWQCbeHwy
TDM/buvqwsqdcMuwRPKX8EdRpSuY8ywNQ3zWQXlOhWjs19u0RNlYxsMF
-----END PRIVATE KEY-----"""

PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE68VLJobDBZwSDeYgDR3zbFkAm3h8
MkwzP27r6sLKnXDLsETyl/BHUaUrmPMsDUN81kF5ToVo7NfbtETZWMbDBQ==
-----END PUBLIC KEY-----"""


def example_request_encryption():
    """Example of encrypting request data."""
    print("=" * 60)
    print("EXAMPLE 1: Request Encryption")
    print("=" * 60)

    # Initialize client with encryption keys
    # - ecc_public_key: Used to encrypt outgoing requests
    # - ecc_private_key: Used to decrypt incoming responses
    client = InterServiceClient(
        base_url="https://autologin.example.com",
        api_key="your-secret-api-key",
        ecc_public_key=PUBLIC_KEY_PEM,  # Server's public key
        ecc_private_key=PRIVATE_KEY_PEM  # Your private key
    )

    print("\nSending encrypted credentials:")

    # POST request with encrypted data
    response = client.request(
        endpoint="credentials/store",
        method="POST",
        data={
            "platform": "linkedin",
            "username": "john@example.com",
            "password": "super-secret-password",
            "cookies": {
                "session": "abc123xyz",
                "auth_token": "secret-token"
            }
        },
        encrypt=True,  # Enable encryption
        query_params={"correlation_id": "store-creds-001"}
    )

    if response["status"] == "success":
        print(f"   ✅ Credentials stored securely")
        print(f"   Response: {response['data']}")
    else:
        print(f"   ❌ Error: {response['error']}")


def example_response_decryption():
    """Example of decrypting response data."""
    print("\n" + "=" * 60)
    print("EXAMPLE 2: Response Decryption")
    print("=" * 60)

    client = InterServiceClient(
        base_url="https://autologin.example.com",
        api_key="your-secret-api-key",
        ecc_public_key=PUBLIC_KEY_PEM,
        ecc_private_key=PRIVATE_KEY_PEM
    )

    print("\nFetching encrypted credentials:")

    # GET request with encrypted response
    response = client.request(
        endpoint="credentials/{platform}/{account_id}",
        path_params={
            "platform": "linkedin",
            "account_id": 123
        },
        decrypt=True,  # Enable decryption
        query_params={"correlation_id": "fetch-creds-001"}
    )

    if response["status"] == "success":
        print(f"   ✅ Credentials decrypted successfully")
        print(f"   Username: {response['data'].get('username')}")
        print(f"   Cookies: {len(response['data'].get('cookies', {}))} items")
    else:
        print(f"   ❌ Error: {response['error']}")


def example_full_encryption_workflow():
    """Example of complete encryption workflow (encrypt request + decrypt response)."""
    print("\n" + "=" * 60)
    print("EXAMPLE 3: Full Encryption Workflow")
    print("=" * 60)

    client = InterServiceClient(
        base_url="https://autologin.example.com",
        api_key="your-secret-api-key",
        ecc_public_key=PUBLIC_KEY_PEM,
        ecc_private_key=PRIVATE_KEY_PEM
    )

    print("\nStep 1: Store encrypted credentials")

    # Store credentials with encryption
    store_response = client.request(
        endpoint="credentials/store",
        method="POST",
        data={
            "platform": "linkedin",
            "username": "john@example.com",
            "password": "my-secure-password",
            "account_id": 456
        },
        encrypt=True,
        query_params={"correlation_id": "workflow-001"}
    )

    if store_response["status"] == "success":
        print(f"   ✅ Stored successfully")
        account_id = store_response["data"].get("account_id")

        print(f"\nStep 2: Retrieve encrypted credentials (account_id: {account_id})")

        # Retrieve credentials with decryption
        fetch_response = client.request(
            endpoint="credentials/{platform}/{account_id}",
            path_params={
                "platform": "linkedin",
                "account_id": account_id
            },
            decrypt=True,
            query_params={"correlation_id": "workflow-002"}
        )

        if fetch_response["status"] == "success":
            print(f"   ✅ Retrieved and decrypted successfully")
            print(f"   Data matches: {fetch_response['data']['username'] == 'john@example.com'}")
        else:
            print(f"   ❌ Fetch error: {fetch_response['error']}")
    else:
        print(f"   ❌ Store error: {store_response['error']}")


def example_encryption_error_handling():
    """Example of error handling with encryption."""
    print("\n" + "=" * 60)
    print("EXAMPLE 4: Encryption Error Handling")
    print("=" * 60)

    # Client without encryption keys
    client_no_keys = InterServiceClient(
        base_url="https://autologin.example.com",
        api_key="your-secret-api-key"
    )

    print("\n1. Attempting encryption without public key:")
    response = client_no_keys.request(
        endpoint="test",
        method="POST",
        data={"test": "data"},
        encrypt=True
    )
    print(f"   Status: {response['status']}")
    if response["status"] == "error":
        print(f"   Expected error (no public key configured)")

    # Client with invalid key
    client_invalid_key = InterServiceClient(
        base_url="https://autologin.example.com",
        api_key="your-secret-api-key",
        ecc_public_key="invalid-key-format"
    )

    print("\n2. Attempting encryption with invalid key:")
    response = client_invalid_key.request(
        endpoint="test",
        method="POST",
        data={"test": "data"},
        encrypt=True
    )
    print(f"   Status: {response['status']}")
    if response["status"] == "error":
        print(f"   Error: {response['error']}")


def example_generate_keys():
    """Example of generating ECC key pairs."""
    print("\n" + "=" * 60)
    print("EXAMPLE 5: Generate ECC Key Pair")
    print("=" * 60)

    print("\nTo generate your own ECC P-256 key pair:")
    print("\n```python")
    print("from cryptography.hazmat.primitives.asymmetric import ec")
    print("from cryptography.hazmat.primitives import serialization")
    print("")
    print("# Generate private key")
    print("private_key = ec.generate_private_key(ec.SECP256R1())")
    print("")
    print("# Get public key")
    print("public_key = private_key.public_key()")
    print("")
    print("# Serialize private key to PEM")
    print("private_pem = private_key.private_bytes(")
    print("    encoding=serialization.Encoding.PEM,")
    print("    format=serialization.PrivateFormat.PKCS8,")
    print("    encryption_algorithm=serialization.NoEncryption()")
    print(").decode('utf-8')")
    print("")
    print("# Serialize public key to PEM")
    print("public_pem = public_key.public_bytes(")
    print("    encoding=serialization.Encoding.PEM,")
    print("    format=serialization.PublicFormat.SubjectPublicKeyInfo")
    print(").decode('utf-8')")
    print("")
    print("print('Private Key:', private_pem)")
    print("print('Public Key:', public_pem)")
    print("```")

    print("\n📝 Security Best Practices:")
    print("   - Store private keys in secure vaults (AWS Secrets Manager, etc.)")
    print("   - Never commit keys to version control")
    print("   - Use different key pairs for different environments")
    print("   - Rotate keys periodically")
    print("   - Share only public keys with other services")


def example_correlation_ids():
    """Example of using correlation IDs with encryption."""
    print("\n" + "=" * 60)
    print("EXAMPLE 6: Correlation IDs with Encryption")
    print("=" * 60)

    client = InterServiceClient(
        base_url="https://autologin.example.com",
        api_key="your-secret-api-key",
        ecc_public_key=PUBLIC_KEY_PEM,
        ecc_private_key=PRIVATE_KEY_PEM
    )

    print("\nCorrelation IDs are used in key derivation for added security.")
    print("The same correlation_id must be used for encryption and decryption.\n")

    # Request with specific correlation ID
    correlation_id = "user-login-session-abc123"

    response = client.request(
        endpoint="credentials/validate",
        method="POST",
        data={
            "username": "john@example.com",
            "password": "secret"
        },
        encrypt=True,
        query_params={"correlation_id": correlation_id}
    )

    print(f"Request sent with correlation_id: {correlation_id}")
    print(f"Status: {response['status']}")

    print("\n💡 Tip: Use meaningful correlation IDs for:")
    print("   - Request tracing across services")
    print("   - Log correlation and debugging")
    print("   - Additional cryptographic binding")


def example_without_encryption():
    """Example showing when NOT to use encryption."""
    print("\n" + "=" * 60)
    print("EXAMPLE 7: When to Use/Skip Encryption")
    print("=" * 60)

    client = InterServiceClient(
        base_url="https://autologin.example.com",
        api_key="your-secret-api-key",
        ecc_public_key=PUBLIC_KEY_PEM,
        ecc_private_key=PRIVATE_KEY_PEM
    )

    print("\n✅ USE encryption for:")
    print("   - Sensitive credentials (passwords, tokens, cookies)")
    print("   - Personal information (PII)")
    print("   - Financial data")
    print("   - Any confidential business data")

    print("\n⚡ SKIP encryption for:")
    print("   - Public data")
    print("   - Non-sensitive metadata")
    print("   - When performance is critical and data is already secured by TLS")

    print("\n1. Request WITHOUT encryption (public data):")
    response = client.request(
        endpoint="users/{user_id}/public-profile",
        path_params={"user_id": 123},
        # No encrypt=True flag
    )
    print(f"   Status: {response['status']}")

    print("\n2. Request WITH encryption (sensitive data):")
    response = client.request(
        endpoint="credentials/store",
        method="POST",
        data={"password": "secret"},
        encrypt=True  # Encrypt sensitive data
    )
    print(f"   Status: {response['status']}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("INTER-SERVICE SDK - ENCRYPTION EXAMPLES")
    print("=" * 60)
    print("\n⚠️  Prerequisites:")
    print("   - Install with crypto support: pip install inter-service-sdk[crypto]")
    print("   - Generate ECC key pairs for your services")
    print("   - Configure keys in environment variables")
    print("=" * 60)

    try:
        example_request_encryption()
        example_response_decryption()
        example_full_encryption_workflow()
        example_encryption_error_handling()
        example_generate_keys()
        example_correlation_ids()
        example_without_encryption()
    except Exception as e:
        print(f"\n\nExample execution error: {e}")
        print("This is expected when using placeholder URLs/keys.")
        print("\n💡 To run these examples:")
        print("   1. Install: pip install inter-service-sdk[crypto]")
        print("   2. Generate real ECC keys")
        print("   3. Update URLs and API keys")

    print("\n" + "=" * 60)
    print("ENCRYPTION EXAMPLES COMPLETE")
    print("=" * 60)
    print("\n📚 For more information:")
    print("   - GitHub: https://github.com/AlexanderRyzhko/inter-service-sdk")
    print("   - Encryption: ECC P-256 + ECDH-ES + AES-256-GCM")
    print("=" * 60)
