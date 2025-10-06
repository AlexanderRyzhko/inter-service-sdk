"""
Server-side utilities for creating REST-compliant inter-service API endpoints with FastAPI.

Provides decorators and utilities to reduce boilerplate in inter-service endpoints:
- Router factory with configurable auth
- Automatic error handling with proper HTTP status codes
- Request/response logging with correlation IDs
- Standard REST response format (data returned directly, errors via HTTPException)

REST Standard:
- Success: Return data directly → FastAPI returns HTTP 200 with data
- Errors: Raise HTTPException(status_code=404, detail="...") → FastAPI returns HTTP 404 with error
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
    Decorator for REST-compliant inter-service endpoints with automatic logging and error handling.

    Provides:
    - Request/response logging with correlation IDs
    - Client host and user-agent logging
    - Automatic error handling with proper HTTP status codes
    - Exception to HTTPException conversion

    Example:
        @router.get("/users/{user_id}")
        @inter_service_endpoint("get_user")
        async def get_user(
            user_id: int,
            correlation_id: str,
            request: Request,
            db: Session = Depends(get_db)
        ):
            user = db.query(User).filter(User.id == user_id).first()

            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            return {"user_id": user.id, "name": user.name}

        # Success returns HTTP 200:
        # {"user_id": 123, "name": "John Doe"}

        # Error returns HTTP 404:
        # {"detail": "User not found"}

    Args:
        endpoint_name: Name for logging (e.g., "get_user")
        require_correlation_id: Whether correlation_id parameter is required (default: True)

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

                logger.info(f"✅ [{endpoint_name}] Request completed successfully")
                return result  # Return data directly (FastAPI handles HTTP 200)

            except HTTPException as e:
                # Re-raise HTTP exceptions (they have proper status codes and details)
                logger.warning(f"❌ [{endpoint_name}] HTTP {e.status_code}: {e.detail}")
                raise

            except Exception as e:
                # Unexpected errors become HTTP 500
                logger.error(f"❌ [{endpoint_name}] Error: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Internal server error in {endpoint_name}"
                )

        return wrapper
    return decorator
