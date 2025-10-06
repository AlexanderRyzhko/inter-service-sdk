"""
Server-side utilities for creating inter-service API endpoints with FastAPI.

Provides decorators and utilities to reduce boilerplate in inter-service endpoints:
- Router factory with configurable auth
- Automatic error handling and logging
- Consistent response formatting
- Correlation ID management
"""

import logging
from typing import Callable, Any, Dict, Optional
from functools import wraps
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, status

logger = logging.getLogger(__name__)


def create_inter_service_router(
    prefix: str = "/api/v1/inter-service",
    tags: Optional[list] = None,
    auth_dependency: Optional[Any] = None
) -> APIRouter:
    """
    Create FastAPI router for inter-service endpoints.

    Returns router with:
    - Configurable prefix (default: /api/v1/inter-service)
    - Optional authentication dependency
    - Custom or default tags

    Example:
        from fastapi import Depends
        from your_auth import require_inter_service_auth

        router = create_inter_service_router(
            auth_dependency=Depends(require_inter_service_auth)
        )

        @router.get("/users/{user_id}")
        async def get_user(user_id: int):
            return {"user_id": user_id}

    Args:
        prefix: API prefix path
        tags: List of tags for OpenAPI docs
        auth_dependency: FastAPI dependency for authentication

    Returns:
        Configured APIRouter instance
    """
    dependencies = []
    if auth_dependency is not None:
        dependencies.append(auth_dependency)

    return APIRouter(
        prefix=prefix,
        tags=tags or ["Inter-Service API"],
        dependencies=dependencies
    )


def inter_service_endpoint(
    endpoint_name: str,
    require_correlation_id: bool = True
):
    """
    Decorator for inter-service endpoints with automatic logging and error handling.

    Provides:
    - Request/response logging with correlation IDs
    - Client host logging
    - Automatic error handling and formatting
    - Consistent timestamp formatting

    Example:
        @router.get("/users/{user_id}")
        @inter_service_endpoint("get_user")
        async def get_user(user_id: int, correlation_id: str, request: Request):
            # Your endpoint logic here
            return {"user_id": user_id, "name": "John Doe"}

        # Automatically wrapped response:
        # {
        #     "status": "success",
        #     "data": {"user_id": 123, "name": "John Doe"},
        #     "correlation_id": "req-001",
        #     "timestamp": "2025-01-01T00:00:00Z"
        # }

    Args:
        endpoint_name: Name for logging (e.g., "get_credentials")
        require_correlation_id: Whether correlation_id parameter is required

    Returns:
        Decorated function with automatic logging and error handling
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract common parameters
            request: Optional[Request] = kwargs.get("request")
            correlation_id = kwargs.get("correlation_id", "unknown")

            # Validation
            if require_correlation_id and correlation_id == "unknown":
                logger.error(f"❌ [{endpoint_name}] Missing required correlation_id parameter")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="correlation_id query parameter is required"
                )

            # Log request
            client_host = request.client.host if request and request.client else "unknown"
            user_agent = request.headers.get("user-agent", "unknown") if request else "unknown"

            logger.info(f"🔗 [{endpoint_name}] Request started - Correlation: {correlation_id}")
            logger.info(f"   Client: {client_host}, User-Agent: {user_agent}")

            try:
                # Execute endpoint function
                result = await func(*args, **kwargs)

                # If result is already a dict with status field, return as-is
                if isinstance(result, dict) and "status" in result:
                    logger.info(f"✅ [{endpoint_name}] Request completed - Status: {result.get('status')}")
                    return result

                # Otherwise, wrap in standard response format
                response = {
                    "status": "success",
                    "data": result,
                    "correlation_id": correlation_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

                logger.info(f"✅ [{endpoint_name}] Request completed successfully")
                return response

            except HTTPException:
                # Re-raise HTTP exceptions (already have proper status codes)
                raise

            except Exception as e:
                logger.error(f"❌ [{endpoint_name}] Error: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Internal server error in {endpoint_name}"
                )

        return wrapper
    return decorator


def format_error_response(
    message: str,
    correlation_id: str,
    status_code: int = 500,
    **extra_fields
) -> Dict[str, Any]:
    """
    Format standard error response.

    Args:
        message: Error message
        correlation_id: Request correlation ID
        status_code: HTTP status code (not included in response, for reference)
        **extra_fields: Additional fields to include in response

    Returns:
        Formatted error response dict

    Example:
        return format_error_response(
            message="User not found",
            correlation_id="req-001",
            status_code=404,
            user_id=123
        )
        # Returns:
        # {
        #     "status": "error",
        #     "error": "User not found",
        #     "correlation_id": "req-001",
        #     "timestamp": "2025-01-01T00:00:00Z",
        #     "user_id": 123
        # }
    """
    response = {
        "status": "error",
        "error": message,
        "correlation_id": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    response.update(extra_fields)
    return response


def format_success_response(
    data: Any,
    correlation_id: str,
    **extra_fields
) -> Dict[str, Any]:
    """
    Format standard success response.

    Args:
        data: Response data
        correlation_id: Request correlation ID
        **extra_fields: Additional fields to include in response

    Returns:
        Formatted success response dict

    Example:
        return format_success_response(
            data={"user_id": 123, "name": "John"},
            correlation_id="req-001",
            cache_hit=True
        )
        # Returns:
        # {
        #     "status": "success",
        #     "data": {"user_id": 123, "name": "John"},
        #     "correlation_id": "req-001",
        #     "timestamp": "2025-01-01T00:00:00Z",
        #     "cache_hit": True
        # }
    """
    response = {
        "status": "success",
        "data": data,
        "correlation_id": correlation_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    response.update(extra_fields)
    return response
