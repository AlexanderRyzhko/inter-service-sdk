"""
Basic usage examples for inter-service-sdk.

This example demonstrates:
- Client initialization
- GET requests with path and query parameters
- POST, PUT, DELETE requests
- Error handling
- Custom API prefix and timeouts
"""

from inter_service_sdk import InterServiceClient


def example_basic_requests():
    """Example of basic HTTP requests."""
    print("=" * 60)
    print("EXAMPLE 1: Basic Requests")
    print("=" * 60)

    # Initialize client
    client = InterServiceClient(
        base_url="https://autologin.example.com",
        api_key="your-secret-api-key-here"
    )

    # GET request - fetch user by ID
    print("\n1. GET user by ID:")
    response = client.request(
        endpoint="users/{user_id}",
        path_params={"user_id": 123}
    )

    if response["status"] == "success":
        print(f"   User data: {response['data']}")
    else:
        print(f"   Error: {response['error']}")

    # GET request with query parameters - search users
    print("\n2. Search users:")
    response = client.request(
        endpoint="users/search",
        query_params={
            "email": "john@example.com",
            "correlation_id": "search-001"
        }
    )

    if response["status"] == "success":
        print(f"   Search results: {response['data']}")
    else:
        print(f"   Error: {response['error']}")

    # POST request - create new user
    print("\n3. Create new user:")
    response = client.request(
        endpoint="users",
        method="POST",
        data={
            "name": "Jane Doe",
            "email": "jane@example.com"
        },
        query_params={"correlation_id": "create-user-001"}
    )

    if response["status"] == "success":
        print(f"   Created user: {response['data']}")
    else:
        print(f"   Error: {response['error']}")

    # PUT request - update user
    print("\n4. Update user:")
    response = client.request(
        endpoint="users/{user_id}",
        path_params={"user_id": 123},
        method="PUT",
        data={
            "name": "John Updated",
            "email": "john.new@example.com"
        }
    )

    if response["status"] == "success":
        print(f"   Updated user: {response['data']}")
    else:
        print(f"   Error: {response['error']}")

    # DELETE request
    print("\n5. Delete user:")
    response = client.request(
        endpoint="users/{user_id}",
        path_params={"user_id": 456},
        method="DELETE"
    )

    if response["status"] == "success":
        print(f"   Deleted successfully")
    else:
        print(f"   Error: {response['error']}")


def example_custom_configuration():
    """Example of custom client configuration."""
    print("\n" + "=" * 60)
    print("EXAMPLE 2: Custom Configuration")
    print("=" * 60)

    # Client with custom configuration
    client = InterServiceClient(
        base_url="https://api.example.com",
        api_key="your-api-key",
        api_prefix="/v2/services",  # Custom API prefix
        timeout=60,  # Custom timeout
        retry_attempts=5  # Custom retry attempts
    )

    print("\nClient configured with:")
    print(f"  - Base URL: {client.base_url}")
    print(f"  - API Prefix: {client.default_api_prefix}")
    print(f"  - Timeout: {client.timeout}s")
    print(f"  - Retry Attempts: {client.retry_attempts}")

    # Make request with custom API prefix
    response = client.request(
        endpoint="status",
        query_params={"correlation_id": "health-check"}
    )

    print(f"\nHealth check: {response['status']}")


def example_multiple_path_params():
    """Example with multiple path parameters."""
    print("\n" + "=" * 60)
    print("EXAMPLE 3: Multiple Path Parameters")
    print("=" * 60)

    client = InterServiceClient(
        base_url="https://autologin.example.com",
        api_key="your-api-key"
    )

    # Endpoint with multiple path parameters
    print("\nFetch LinkedIn credentials for account:")
    response = client.request(
        endpoint="credentials/{platform}/{account_id}",
        path_params={
            "platform": "linkedin",
            "account_id": 789
        },
        query_params={"correlation_id": "fetch-creds-001"}
    )

    if response["status"] == "success":
        print(f"   Credentials: {response['data']}")
    else:
        print(f"   Error: {response['error']}")


def example_error_handling():
    """Example of error handling."""
    print("\n" + "=" * 60)
    print("EXAMPLE 4: Error Handling")
    print("=" * 60)

    client = InterServiceClient(
        base_url="https://api.example.com",
        api_key="invalid-key",
        retry_attempts=1  # Reduce retries for faster failure
    )

    # This will fail with 401 Unauthorized
    print("\n1. Authentication error (401):")
    response = client.request(endpoint="users")

    print(f"   Status: {response['status']}")
    print(f"   Status Code: {response['status_code']}")
    print(f"   Error: {response['error']}")

    # This will fail with 404 Not Found
    print("\n2. Not found error (404):")
    valid_client = InterServiceClient(
        base_url="https://api.example.com",
        api_key="valid-key"
    )

    response = valid_client.request(
        endpoint="users/{user_id}",
        path_params={"user_id": 999999}
    )

    print(f"   Status: {response['status']}")
    print(f"   Status Code: {response['status_code']}")


def example_custom_headers():
    """Example with custom headers."""
    print("\n" + "=" * 60)
    print("EXAMPLE 5: Custom Headers")
    print("=" * 60)

    client = InterServiceClient(
        base_url="https://api.example.com",
        api_key="your-api-key"
    )

    # Add custom headers
    response = client.request(
        endpoint="users",
        headers={
            "X-Request-ID": "custom-request-123",
            "X-Client-Version": "1.0.0"
        }
    )

    print(f"\nRequest with custom headers: {response['status']}")


def example_override_api_prefix():
    """Example of overriding API prefix per request."""
    print("\n" + "=" * 60)
    print("EXAMPLE 6: Override API Prefix")
    print("=" * 60)

    client = InterServiceClient(
        base_url="https://api.example.com",
        api_key="your-api-key",
        api_prefix="/api/v1/inter-service"  # Default prefix
    )

    # Use default prefix
    print("\n1. Using default prefix (/api/v1/inter-service):")
    response = client.request(endpoint="users")
    print(f"   Status: {response['status']}")

    # Override prefix for specific request
    print("\n2. Using custom prefix (/api/v2/custom):")
    response = client.request(
        endpoint="users",
        api_prefix="/api/v2/custom"
    )
    print(f"   Status: {response['status']}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("INTER-SERVICE SDK - BASIC USAGE EXAMPLES")
    print("=" * 60)
    print("\nNote: These examples use placeholder URLs and API keys.")
    print("Replace them with actual values from your environment.")
    print("=" * 60)

    # Run examples
    try:
        example_basic_requests()
        example_custom_configuration()
        example_multiple_path_params()
        example_error_handling()
        example_custom_headers()
        example_override_api_prefix()
    except Exception as e:
        print(f"\n\nExample execution error: {e}")
        print("This is expected when using placeholder URLs/keys.")

    print("\n" + "=" * 60)
    print("EXAMPLES COMPLETE")
    print("=" * 60)