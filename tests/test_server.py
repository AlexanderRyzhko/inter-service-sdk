"""
Tests for inter_service_sdk.server module.
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.testclient import TestClient
from fastapi import FastAPI

from inter_service_sdk.server import (
    create_inter_service_router,
    inter_service_endpoint,
    format_error_response,
    format_success_response
)


class TestCreateInterServiceRouter:
    """Test create_inter_service_router function."""

    def test_default_router(self):
        """Test router creation with defaults."""
        router = create_inter_service_router()

        assert isinstance(router, APIRouter)
        assert router.prefix == "/api/v1/inter-service"
        assert router.tags == ["Inter-Service API"]
        assert len(router.dependencies) == 0

    def test_custom_prefix(self):
        """Test router with custom prefix."""
        router = create_inter_service_router(prefix="/v2/custom")

        assert router.prefix == "/v2/custom"

    def test_custom_tags(self):
        """Test router with custom tags."""
        custom_tags = ["Custom API", "V2"]
        router = create_inter_service_router(tags=custom_tags)

        assert router.tags == custom_tags

    def test_with_auth_dependency(self):
        """Test router with auth dependency."""
        def mock_auth():
            return {"authenticated": True}

        router = create_inter_service_router(
            auth_dependency=Depends(mock_auth)
        )

        assert len(router.dependencies) == 1

    def test_without_auth_dependency(self):
        """Test router without auth dependency."""
        router = create_inter_service_router(auth_dependency=None)

        assert len(router.dependencies) == 0


class TestInterServiceEndpoint:
    """Test inter_service_endpoint decorator."""

    def test_successful_request(self):
        """Test decorator with successful request."""
        app = FastAPI()
        router = create_inter_service_router()

        @router.get("/test")
        @inter_service_endpoint("test_endpoint")
        async def test_func(correlation_id: str, request: Request):
            return {"result": "success"}

        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/v1/inter-service/test?correlation_id=test-123")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"] == {"result": "success"}
        assert data["correlation_id"] == "test-123"
        assert "timestamp" in data

    def test_missing_correlation_id(self):
        """Test decorator when correlation_id is missing."""
        app = FastAPI()
        router = create_inter_service_router()

        @router.get("/test")
        @inter_service_endpoint("test_endpoint")
        async def test_func(correlation_id: str, request: Request):
            return {"result": "success"}

        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/v1/inter-service/test")

        # FastAPI returns 422 for missing required query parameters
        assert response.status_code == 422

    def test_optional_correlation_id(self):
        """Test decorator with optional correlation_id."""
        app = FastAPI()
        router = create_inter_service_router()

        @router.get("/test")
        @inter_service_endpoint("test_endpoint", require_correlation_id=False)
        async def test_func(correlation_id: str = "unknown", request: Request = None):
            return {"result": "success"}

        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/v1/inter-service/test")

        assert response.status_code == 200
        data = response.json()
        assert data["correlation_id"] == "unknown"

    def test_response_with_status_field(self):
        """Test decorator when endpoint returns dict with status."""
        app = FastAPI()
        router = create_inter_service_router()

        @router.get("/test")
        @inter_service_endpoint("test_endpoint")
        async def test_func(correlation_id: str, request: Request):
            return {
                "status": "custom",
                "data": {"custom": "response"},
                "correlation_id": correlation_id
            }

        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/v1/inter-service/test?correlation_id=test-123")

        assert response.status_code == 200
        data = response.json()
        # Should return as-is without wrapping
        assert data["status"] == "custom"
        assert data["data"] == {"custom": "response"}

    def test_http_exception_passthrough(self):
        """Test that HTTP exceptions are re-raised."""
        app = FastAPI()
        router = create_inter_service_router()

        @router.get("/test")
        @inter_service_endpoint("test_endpoint")
        async def test_func(correlation_id: str, request: Request):
            raise HTTPException(status_code=404, detail="Not found")

        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/v1/inter-service/test?correlation_id=test-123")

        assert response.status_code == 404
        assert response.json()["detail"] == "Not found"

    def test_general_exception_handling(self):
        """Test handling of unexpected exceptions."""
        app = FastAPI()
        router = create_inter_service_router()

        @router.get("/test")
        @inter_service_endpoint("test_endpoint")
        async def test_func(correlation_id: str, request: Request):
            raise ValueError("Unexpected error")

        app.include_router(router)
        client = TestClient(app)

        response = client.get("/api/v1/inter-service/test?correlation_id=test-123")

        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]


class TestFormatErrorResponse:
    """Test format_error_response function."""

    def test_basic_error_response(self):
        """Test basic error response formatting."""
        response = format_error_response(
            message="Something went wrong",
            correlation_id="req-001"
        )

        assert response["status"] == "error"
        assert response["error"] == "Something went wrong"
        assert response["correlation_id"] == "req-001"
        assert "timestamp" in response

    def test_error_response_with_status_code(self):
        """Test error response with status code."""
        response = format_error_response(
            message="Not found",
            correlation_id="req-002",
            status_code=404
        )

        # Note: status_code is for reference, not included in response
        assert response["status"] == "error"
        assert response["error"] == "Not found"

    def test_error_response_with_extra_fields(self):
        """Test error response with additional fields."""
        response = format_error_response(
            message="Validation failed",
            correlation_id="req-003",
            user_id=123,
            field_errors=["email", "password"]
        )

        assert response["status"] == "error"
        assert response["error"] == "Validation failed"
        assert response["user_id"] == 123
        assert response["field_errors"] == ["email", "password"]

    def test_timestamp_format(self):
        """Test that timestamp is in ISO format."""
        response = format_error_response(
            message="Error",
            correlation_id="req-004"
        )

        # Verify timestamp is parseable ISO format
        timestamp = response["timestamp"]
        parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        assert isinstance(parsed, datetime)


class TestFormatSuccessResponse:
    """Test format_success_response function."""

    def test_basic_success_response(self):
        """Test basic success response formatting."""
        response = format_success_response(
            data={"user_id": 123, "name": "John"},
            correlation_id="req-001"
        )

        assert response["status"] == "success"
        assert response["data"] == {"user_id": 123, "name": "John"}
        assert response["correlation_id"] == "req-001"
        assert "timestamp" in response

    def test_success_response_with_extra_fields(self):
        """Test success response with additional fields."""
        response = format_success_response(
            data={"result": "ok"},
            correlation_id="req-002",
            cache_hit=True,
            execution_time_ms=42
        )

        assert response["status"] == "success"
        assert response["data"] == {"result": "ok"}
        assert response["cache_hit"] is True
        assert response["execution_time_ms"] == 42

    def test_success_response_with_list_data(self):
        """Test success response with list as data."""
        response = format_success_response(
            data=[1, 2, 3, 4, 5],
            correlation_id="req-003"
        )

        assert response["status"] == "success"
        assert response["data"] == [1, 2, 3, 4, 5]

    def test_success_response_with_none_data(self):
        """Test success response with None as data."""
        response = format_success_response(
            data=None,
            correlation_id="req-004"
        )

        assert response["status"] == "success"
        assert response["data"] is None

    def test_timestamp_format(self):
        """Test that timestamp is in ISO format."""
        response = format_success_response(
            data={"test": "data"},
            correlation_id="req-005"
        )

        # Verify timestamp is parseable ISO format
        timestamp = response["timestamp"]
        parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        assert isinstance(parsed, datetime)


class TestIntegration:
    """Integration tests for server utilities."""

    def test_complete_endpoint_flow(self):
        """Test complete flow with router, decorator, and formatters."""
        app = FastAPI()

        def mock_auth():
            return {"user": "test"}

        router = create_inter_service_router(
            auth_dependency=Depends(mock_auth)
        )

        @router.get("/users/{user_id}")
        @inter_service_endpoint("get_user")
        async def get_user(
            user_id: int,
            correlation_id: str,
            request: Request
        ):
            if user_id == 999:
                return format_error_response(
                    message="User not found",
                    correlation_id=correlation_id,
                    user_id=user_id
                )

            return format_success_response(
                data={"user_id": user_id, "name": f"User {user_id}"},
                correlation_id=correlation_id
            )

        app.include_router(router)
        client = TestClient(app)

        # Test success case
        response = client.get("/api/v1/inter-service/users/123?correlation_id=req-001")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["data"]["user_id"] == 123

        # Test error case
        response = client.get("/api/v1/inter-service/users/999?correlation_id=req-002")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "error"
        assert "not found" in data["error"]