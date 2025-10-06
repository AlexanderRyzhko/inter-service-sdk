"""
Tests for inter_service_sdk.client module.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import requests
from requests.exceptions import Timeout, RequestException

from inter_service_sdk.client import InterServiceClient
from inter_service_sdk.exceptions import AuthenticationError, RequestError


class TestInterServiceClient:
    """Test InterServiceClient initialization and configuration."""

    def test_client_initialization(self):
        """Test client initialization with basic parameters."""
        client = InterServiceClient(
            base_url="https://api.example.com",
            api_key="test-api-key"
        )

        assert client.base_url == "https://api.example.com"
        assert client.api_key == "test-api-key"
        assert client.default_api_prefix == "/api/v1/inter-service"
        assert client.timeout == 30
        assert client.retry_attempts == 3

    def test_client_strips_trailing_slash(self):
        """Test that trailing slash is removed from base URL."""
        client = InterServiceClient(
            base_url="https://api.example.com/",
            api_key="test-api-key"
        )

        assert client.base_url == "https://api.example.com"

    def test_client_custom_api_prefix(self):
        """Test client initialization with custom API prefix."""
        client = InterServiceClient(
            base_url="https://api.example.com",
            api_key="test-api-key",
            api_prefix="/v2/services"
        )

        assert client.default_api_prefix == "/v2/services"

    def test_client_custom_timeout(self):
        """Test client initialization with custom timeout."""
        client = InterServiceClient(
            base_url="https://api.example.com",
            api_key="test-api-key",
            timeout=60
        )

        assert client.timeout == 60

    def test_client_custom_retry(self):
        """Test client initialization with custom retry attempts."""
        client = InterServiceClient(
            base_url="https://api.example.com",
            api_key="test-api-key",
            retry_attempts=5
        )

        assert client.retry_attempts == 5

    def test_client_session_headers(self):
        """Test that session is configured with correct headers."""
        client = InterServiceClient(
            base_url="https://api.example.com",
            api_key="test-api-key-123"
        )

        assert client.session.headers["Authorization"] == "Bearer test-api-key-123"
        assert client.session.headers["User-Agent"] == "InterServiceSDK/1.0.0"
        assert client.session.headers["Content-Type"] == "application/json"
        assert client.session.headers["Accept"] == "application/json"

    def test_client_with_ecc_keys(self):
        """Test client initialization with ECC keys."""
        client = InterServiceClient(
            base_url="https://api.example.com",
            api_key="test-api-key",
            ecc_private_key="private-key-pem",
            ecc_public_key="public-key-pem"
        )

        assert client.ecc_private_key == "private-key-pem"
        assert client.ecc_public_key == "public-key-pem"


class TestClientRequests:
    """Test HTTP request functionality."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return InterServiceClient(
            base_url="https://api.example.com",
            api_key="test-api-key",
            retry_attempts=1  # Reduce retries for faster tests
        )

    @pytest.fixture
    def mock_response(self):
        """Create mock response."""
        mock = Mock()
        mock.status_code = 200
        mock.json.return_value = {"data": {"user_id": 123, "name": "John Doe"}}
        return mock

    def test_get_request(self, client, mock_response):
        """Test basic GET request."""
        with patch.object(client.session, 'request', return_value=mock_response):
            response = client.request(endpoint="users")

            assert response["status"] == "success"
            assert response["data"]["user_id"] == 123
            assert response["status_code"] == 200
            assert response["error"] is None

    def test_get_request_with_path_params(self, client, mock_response):
        """Test GET request with path parameters."""
        with patch.object(client.session, 'request', return_value=mock_response) as mock_request:
            response = client.request(
                endpoint="users/{user_id}",
                path_params={"user_id": 123}
            )

            # Verify URL was built correctly
            call_args = mock_request.call_args
            assert "users/123" in call_args.kwargs["url"]
            assert response["status"] == "success"

    def test_get_request_with_query_params(self, client, mock_response):
        """Test GET request with query parameters."""
        with patch.object(client.session, 'request', return_value=mock_response) as mock_request:
            response = client.request(
                endpoint="users",
                query_params={"correlation_id": "track-001", "limit": 10}
            )

            # Verify URL includes query params
            call_args = mock_request.call_args
            assert "correlation_id=track-001" in call_args.kwargs["url"]
            assert "limit=10" in call_args.kwargs["url"]
            assert response["status"] == "success"

    def test_post_request_with_data(self, client, mock_response):
        """Test POST request with JSON data."""
        with patch.object(client.session, 'request', return_value=mock_response) as mock_request:
            data = {"name": "New User", "email": "test@example.com"}
            response = client.request(
                endpoint="users",
                method="POST",
                data=data
            )

            # Verify request method and data
            call_args = mock_request.call_args
            assert call_args.kwargs["method"] == "POST"
            assert call_args.kwargs["json"] == data
            assert response["status"] == "success"

    def test_put_request(self, client, mock_response):
        """Test PUT request."""
        with patch.object(client.session, 'request', return_value=mock_response) as mock_request:
            data = {"name": "Updated User"}
            response = client.request(
                endpoint="users/{user_id}",
                path_params={"user_id": 123},
                method="PUT",
                data=data
            )

            call_args = mock_request.call_args
            assert call_args.kwargs["method"] == "PUT"
            assert response["status"] == "success"

    def test_delete_request(self, client, mock_response):
        """Test DELETE request."""
        with patch.object(client.session, 'request', return_value=mock_response) as mock_request:
            response = client.request(
                endpoint="users/{user_id}",
                path_params={"user_id": 123},
                method="DELETE"
            )

            call_args = mock_request.call_args
            assert call_args.kwargs["method"] == "DELETE"
            assert response["status"] == "success"

    def test_custom_headers(self, client, mock_response):
        """Test request with custom headers."""
        with patch.object(client.session, 'request', return_value=mock_response) as mock_request:
            custom_headers = {"X-Custom-Header": "custom-value"}
            response = client.request(
                endpoint="users",
                headers=custom_headers
            )

            # Verify custom header was added
            call_args = mock_request.call_args
            assert call_args.kwargs["headers"]["X-Custom-Header"] == "custom-value"
            # Original headers should still be present
            assert "Authorization" in call_args.kwargs["headers"]

    def test_custom_timeout(self, client, mock_response):
        """Test request with custom timeout."""
        with patch.object(client.session, 'request', return_value=mock_response) as mock_request:
            response = client.request(
                endpoint="users",
                timeout=60
            )

            call_args = mock_request.call_args
            assert call_args.kwargs["timeout"] == 60

    def test_override_api_prefix(self, client, mock_response):
        """Test request with overridden API prefix."""
        with patch.object(client.session, 'request', return_value=mock_response) as mock_request:
            response = client.request(
                endpoint="users",
                api_prefix="/v2/custom"
            )

            call_args = mock_request.call_args
            assert "/v2/custom/users" in call_args.kwargs["url"]


class TestClientErrorHandling:
    """Test error handling."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return InterServiceClient(
            base_url="https://api.example.com",
            api_key="test-api-key",
            retry_attempts=1
        )

    def test_http_404_error(self, client):
        """Test handling of 404 error."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"

        with patch.object(client.session, 'request', return_value=mock_response):
            response = client.request(endpoint="users/999")

            assert response["status"] == "error"
            assert response["status_code"] == 404
            assert "Not Found" in response["error"]
            assert response["data"] is None

    def test_http_401_error(self, client):
        """Test handling of authentication error."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch.object(client.session, 'request', return_value=mock_response):
            response = client.request(endpoint="users")

            assert response["status"] == "error"
            assert response["status_code"] == 401
            assert "Unauthorized" in response["error"]

    def test_http_500_error(self, client):
        """Test handling of server error."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(client.session, 'request', return_value=mock_response):
            response = client.request(endpoint="users")

            assert response["status"] == "error"
            assert response["status_code"] == 500

    def test_timeout_error(self, client):
        """Test handling of request timeout."""
        with patch.object(client.session, 'request', side_effect=Timeout("Connection timeout")):
            response = client.request(endpoint="users")

            assert response["status"] == "error"
            assert response["data"] is None
            assert "timed out" in response["error"]

    def test_request_exception(self, client):
        """Test handling of general request exception."""
        with patch.object(client.session, 'request', side_effect=RequestException("Network error")):
            response = client.request(endpoint="users")

            assert response["status"] == "error"
            assert "Network error" in response["error"]

    def test_unexpected_exception(self, client):
        """Test handling of unexpected exception."""
        with patch.object(client.session, 'request', side_effect=ValueError("Unexpected error")):
            response = client.request(endpoint="users")

            assert response["status"] == "error"
            assert "Unexpected error" in response["error"]

    def test_retry_on_timeout(self, client):
        """Test retry mechanism on timeout."""
        client.retry_attempts = 3

        with patch.object(client.session, 'request', side_effect=Timeout("Connection timeout")):
            with patch('time.sleep'):  # Skip actual sleep
                response = client.request(endpoint="users")

                # Should have retried 3 times
                assert client.session.request.call_count == 3
                assert response["status"] == "error"

    def test_retry_with_eventual_success(self, client):
        """Test that retry succeeds after failures."""
        client.retry_attempts = 3

        # First two calls fail, third succeeds
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"success": True}}

        with patch.object(
            client.session,
            'request',
            side_effect=[Timeout("timeout"), Timeout("timeout"), mock_response]
        ):
            with patch('time.sleep'):  # Skip actual sleep
                response = client.request(endpoint="users")

                assert response["status"] == "success"
                assert response["data"]["success"] is True


class TestClientEncryption:
    """Test encryption/decryption functionality."""

    @pytest.fixture
    def client_with_crypto(self):
        """Create client with crypto keys."""
        return InterServiceClient(
            base_url="https://api.example.com",
            api_key="test-api-key",
            ecc_private_key="private-key-pem",
            ecc_public_key="public-key-pem",
            retry_attempts=1
        )

    def test_request_with_encryption(self, client_with_crypto):
        """Test request with data encryption."""
        mock_encrypted = {
            "encrypted_data": "base64-encrypted",
            "ephemeral_public_key": "ephemeral-key",
            "nonce": "nonce-value"
        }

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"success": True}}

        with patch('inter_service_sdk.crypto.encrypt_data', return_value=mock_encrypted):
            with patch.object(client_with_crypto.session, 'request', return_value=mock_response) as mock_request:
                data = {"user_id": 123}
                response = client_with_crypto.request(
                    endpoint="users",
                    method="POST",
                    data=data,
                    encrypt=True
                )

                # Verify encrypted data was sent
                call_args = mock_request.call_args
                assert call_args.kwargs["json"] == mock_encrypted
                assert response["status"] == "success"

    def test_request_with_decryption(self, client_with_crypto):
        """Test request with response decryption."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "encrypted_data": "encrypted",
            "ephemeral_public_key": "key",
            "nonce": "nonce"
        }

        decrypted_data = {"user_id": 123, "name": "John Doe"}

        with patch('inter_service_sdk.crypto.decrypt_data', return_value=decrypted_data):
            with patch.object(client_with_crypto.session, 'request', return_value=mock_response):
                response = client_with_crypto.request(
                    endpoint="users",
                    decrypt=True
                )

                assert response["status"] == "success"
                assert response["data"] == decrypted_data

    def test_encryption_error_handling(self, client_with_crypto):
        """Test handling of encryption errors."""
        with patch('inter_service_sdk.crypto.encrypt_data', side_effect=Exception("Encryption failed")):
            response = client_with_crypto.request(
                endpoint="users",
                method="POST",
                data={"test": "data"},
                encrypt=True
            )

            assert response["status"] == "error"
            assert "Encryption failed" in response["error"]

    def test_decryption_error_handling(self, client_with_crypto):
        """Test handling of decryption errors."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "encrypted_data": "encrypted",
            "ephemeral_public_key": "key",
            "nonce": "nonce"
        }

        with patch('inter_service_sdk.crypto.decrypt_data', side_effect=Exception("Decryption failed")):
            with patch.object(client_with_crypto.session, 'request', return_value=mock_response):
                response = client_with_crypto.request(
                    endpoint="users",
                    decrypt=True
                )

                assert response["status"] == "error"
                assert "Decryption failed" in response["error"]


class TestClientResponseFormats:
    """Test different response format handling."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return InterServiceClient(
            base_url="https://api.example.com",
            api_key="test-api-key",
            retry_attempts=1
        )

    def test_response_with_data_field(self, client):
        """Test response that has a 'data' field."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": {"user_id": 123}
        }

        with patch.object(client.session, 'request', return_value=mock_response):
            response = client.request(endpoint="users")

            assert response["data"] == {"user_id": 123}

    def test_response_without_data_field(self, client):
        """Test response without explicit 'data' field."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_id": 123, "name": "John"}

        with patch.object(client.session, 'request', return_value=mock_response):
            response = client.request(endpoint="users")

            # Should return entire response as data
            assert response["data"] == {"user_id": 123, "name": "John"}

    def test_response_structure(self, client):
        """Test that response always has consistent structure."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": {"test": "value"}}

        with patch.object(client.session, 'request', return_value=mock_response):
            response = client.request(endpoint="test")

            # Verify response structure
            assert "status" in response
            assert "data" in response
            assert "status_code" in response
            assert "error" in response
            assert response["status"] in ["success", "error"]