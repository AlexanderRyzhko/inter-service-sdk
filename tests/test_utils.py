"""
Tests for inter_service_sdk.utils module.
"""

import pytest
from inter_service_sdk.utils import build_url
from inter_service_sdk.exceptions import URLBuildError


class TestBuildURL:
    """Test URL building functionality."""

    def test_basic_url(self):
        """Test basic URL without parameters."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="/api/v1/inter-service",
            endpoint="users"
        )
        assert url == "https://api.example.com/api/v1/inter-service/users"

    def test_with_path_params(self):
        """Test URL with path parameter substitution."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="/api/v1/inter-service",
            endpoint="users/{user_id}",
            path_params={"user_id": 123}
        )
        assert url == "https://api.example.com/api/v1/inter-service/users/123"

    def test_with_multiple_path_params(self):
        """Test URL with multiple path parameters."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="/api/v1/inter-service",
            endpoint="credentials/{platform}/{account_id}",
            path_params={"platform": "linkedin", "account_id": 456}
        )
        assert url == "https://api.example.com/api/v1/inter-service/credentials/linkedin/456"

    def test_with_query_params(self):
        """Test URL with query parameters."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="/api/v1/inter-service",
            endpoint="users",
            query_params={"correlation_id": "track-001", "limit": 10}
        )
        assert "https://api.example.com/api/v1/inter-service/users?" in url
        assert "correlation_id=track-001" in url
        assert "limit=10" in url

    def test_with_path_and_query_params(self):
        """Test URL with both path and query parameters."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="/api/v1/inter-service",
            endpoint="users/{user_id}",
            path_params={"user_id": 123},
            query_params={"correlation_id": "track-001"}
        )
        assert url == "https://api.example.com/api/v1/inter-service/users/123?correlation_id=track-001"

    def test_filters_none_query_params(self):
        """Test that None values are filtered from query parameters."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="/api/v1/inter-service",
            endpoint="users",
            query_params={"correlation_id": "track-001", "optional": None, "limit": 10}
        )
        assert "optional" not in url
        assert "correlation_id=track-001" in url
        assert "limit=10" in url

    def test_all_none_query_params(self):
        """Test URL when all query params are None."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="/api/v1/inter-service",
            endpoint="users",
            query_params={"optional1": None, "optional2": None}
        )
        assert "?" not in url
        assert url == "https://api.example.com/api/v1/inter-service/users"

    def test_empty_api_prefix(self):
        """Test URL with empty API prefix."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="",
            endpoint="users"
        )
        assert url == "https://api.example.com/users"

    def test_custom_api_prefix(self):
        """Test URL with custom API prefix."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="/v2/services",
            endpoint="users"
        )
        assert url == "https://api.example.com/v2/services/users"

    def test_missing_path_param(self):
        """Test error when required path parameter is missing."""
        with pytest.raises(URLBuildError) as exc_info:
            build_url(
                base_url="https://api.example.com",
                api_prefix="/api/v1/inter-service",
                endpoint="users/{user_id}",
                path_params={}
            )
        assert "Missing path parameter" in str(exc_info.value)

    def test_extra_path_params(self):
        """Test that extra path parameters are ignored."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="/api/v1/inter-service",
            endpoint="users/{user_id}",
            path_params={"user_id": 123, "extra_param": 999}
        )
        assert url == "https://api.example.com/api/v1/inter-service/users/123"

    def test_special_characters_in_query_params(self):
        """Test URL encoding of special characters in query parameters."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="/api/v1/inter-service",
            endpoint="users",
            query_params={"name": "John Doe", "email": "test@example.com"}
        )
        assert "name=John+Doe" in url or "name=John%20Doe" in url
        assert "email=test%40example.com" in url

    def test_numeric_path_params(self):
        """Test URL with numeric path parameters."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="/api/v1/inter-service",
            endpoint="users/{user_id}/posts/{post_id}",
            path_params={"user_id": 123, "post_id": 456}
        )
        assert url == "https://api.example.com/api/v1/inter-service/users/123/posts/456"

    def test_string_path_params(self):
        """Test URL with string path parameters."""
        url = build_url(
            base_url="https://api.example.com",
            api_prefix="/api/v1/inter-service",
            endpoint="credentials/{platform}",
            path_params={"platform": "linkedin"}
        )
        assert url == "https://api.example.com/api/v1/inter-service/credentials/linkedin"