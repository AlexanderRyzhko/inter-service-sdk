"""
Utility functions for inter-service SDK.
"""

from typing import Dict, Any, Optional
from urllib.parse import urlencode
from .exceptions import URLBuildError


def build_url(
    base_url: str,
    api_prefix: str,
    endpoint: str,
    path_params: Optional[Dict[str, Any]] = None,
    query_params: Optional[Dict[str, Any]] = None
) -> str:
    """
    Build complete URL with path parameter substitution.

    Args:
        base_url: Base URL (e.g., "https://api.example.com")
        api_prefix: API prefix (e.g., "/api/v1/inter-service")
        endpoint: Endpoint template (e.g., "users/{user_id}")
        path_params: Path parameters for substitution
        query_params: Query string parameters

    Returns:
        Complete URL string

    Example:
        >>> build_url(
        ...     "https://api.example.com",
        ...     "/api/v1/inter-service",
        ...     "users/{user_id}",
        ...     {"user_id": 123},
        ...     {"correlation_id": "track-001"}
        ... )
        'https://api.example.com/api/v1/inter-service/users/123?correlation_id=track-001'
    """
    try:
        # Substitute path parameters
        if path_params:
            endpoint = endpoint.format(**path_params)

        # Build full URL
        url = f"{base_url}{api_prefix}/{endpoint}"

        # Add query parameters
        if query_params:
            # Filter out None values
            clean_params = {k: v for k, v in query_params.items() if v is not None}
            if clean_params:
                query_string = urlencode(clean_params)
                url = f"{url}?{query_string}"

        return url

    except KeyError as e:
        raise URLBuildError(f"Missing path parameter: {e}")
    except Exception as e:
        raise URLBuildError(f"Failed to build URL: {e}")
