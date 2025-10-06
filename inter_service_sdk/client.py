"""
Inter-service HTTP client with bearer auth and optional encryption.
"""

import time
import logging
from typing import Optional, Dict, Any
import requests
from requests.exceptions import RequestException, Timeout

from .utils import build_url
from .exceptions import AuthenticationError, RequestError
from . import crypto

logger = logging.getLogger(__name__)


class InterServiceClient:
    """
    Generic HTTP client for inter-service communication.

    Features:
    - Bearer token authentication
    - Optional ECC encryption/decryption
    - Path and query parameter handling
    - Automatic retry with exponential backoff
    - Consistent response format

    Example:
        >>> client = InterServiceClient(
        ...     base_url="https://api.example.com",
        ...     api_key="your-secret-key"
        ... )
        >>> response = client.request(
        ...     endpoint="users/{user_id}",
        ...     path_params={"user_id": 123}
        ... )
        >>> print(response["data"])
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_prefix: str = "/api/v1/inter-service",
        timeout: int = 30,
        retry_attempts: int = 3,
        ecc_private_key: Optional[str] = None,
        ecc_public_key: Optional[str] = None
    ):
        """
        Initialize inter-service client.

        Args:
            base_url: Base URL (e.g., "https://api.example.com")
            api_key: Bearer token for authentication
            api_prefix: API prefix (default: "/api/v1/inter-service")
            timeout: Request timeout in seconds (default: 30)
            retry_attempts: Number of retry attempts (default: 3)
            ecc_private_key: ECC private key for decryption (PEM format)
            ecc_public_key: ECC public key for encryption (PEM format)
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.default_api_prefix = api_prefix
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.ecc_private_key = ecc_private_key
        self.ecc_public_key = ecc_public_key

        # Setup session with auth headers
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'InterServiceSDK/1.0.0',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })

        logger.info(f"InterServiceClient initialized: {base_url}{api_prefix}")

    def request(
        self,
        endpoint: str,
        path_params: Optional[Dict[str, Any]] = None,
        query_params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        encrypt: bool = False,
        decrypt: bool = False,
        timeout: Optional[int] = None,
        api_prefix: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Make HTTP request to inter-service API.

        Args:
            endpoint: Endpoint template (e.g., "users/{user_id}")
            path_params: Path parameters for substitution
            query_params: Query string parameters
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            data: Request body (JSON)
            headers: Additional headers
            encrypt: Auto-encrypt request data with ECC
            decrypt: Auto-decrypt response with ECC
            timeout: Override default timeout
            api_prefix: Override default API prefix

        Returns:
            {
                "status": "success" | "error",
                "data": {...} | None,
                "status_code": int,
                "error": None | str
            }

        Example:
            >>> response = client.request(
            ...     endpoint="users/{user_id}",
            ...     path_params={"user_id": 123},
            ...     query_params={"correlation_id": "track-001"}
            ... )
        """
        # Build URL
        url = build_url(
            self.base_url,
            api_prefix if api_prefix is not None else self.default_api_prefix,
            endpoint,
            path_params,
            query_params
        )

        # Prepare request data
        json_data = None
        if data:
            if encrypt and self.ecc_public_key:
                try:
                    correlation_id = query_params.get("correlation_id", "default") if query_params else "default"
                    encrypted = crypto.encrypt_data(data, self.ecc_public_key, correlation_id)
                    json_data = encrypted
                except Exception as e:
                    logger.error(f"Encryption failed: {e}")
                    return {
                        "status": "error",
                        "data": None,
                        "status_code": None,
                        "error": f"Encryption failed: {str(e)}"
                    }
            else:
                json_data = data

        # Merge headers
        request_headers = self.session.headers.copy()
        if headers:
            request_headers.update(headers)

        # Make request with retry logic
        for attempt in range(self.retry_attempts):
            try:
                logger.debug(f"{method} {url}")

                response = self.session.request(
                    method=method.upper(),
                    url=url,
                    json=json_data,
                    headers=request_headers,
                    timeout=timeout or self.timeout
                )

                # Handle HTTP errors
                if response.status_code >= 400:
                    logger.error(f"HTTP {response.status_code}: {response.text}")
                    return {
                        "status": "error",
                        "data": None,
                        "status_code": response.status_code,
                        "error": response.text
                    }

                # Parse response
                response_data = response.json()

                # Decrypt if needed
                if decrypt and self.ecc_private_key:
                    try:
                        # Extract encrypted data from response
                        if "encrypted_data" in response_data:
                            correlation_id = query_params.get("correlation_id", "default") if query_params else "default"
                            decrypted = crypto.decrypt_data(
                                response_data["encrypted_data"],
                                response_data["ephemeral_public_key"],
                                response_data["nonce"],
                                self.ecc_private_key,
                                correlation_id
                            )
                            response_data["data"] = decrypted
                    except Exception as e:
                        logger.error(f"Decryption failed: {e}")
                        return {
                            "status": "error",
                            "data": None,
                            "status_code": response.status_code,
                            "error": f"Decryption failed: {str(e)}"
                        }

                return {
                    "status": "success",
                    "data": response_data.get("data", response_data),
                    "status_code": response.status_code,
                    "error": None
                }

            except Timeout:
                logger.warning(f"Request timeout (attempt {attempt + 1}/{self.retry_attempts})")
                if attempt == self.retry_attempts - 1:
                    return {
                        "status": "error",
                        "data": None,
                        "status_code": None,
                        "error": f"Request timed out after {timeout or self.timeout} seconds"
                    }
                time.sleep(2 ** attempt)  # Exponential backoff

            except RequestException as e:
                logger.warning(f"Request failed (attempt {attempt + 1}/{self.retry_attempts}): {e}")
                if attempt == self.retry_attempts - 1:
                    return {
                        "status": "error",
                        "data": None,
                        "status_code": None,
                        "error": str(e)
                    }
                time.sleep(2 ** attempt)  # Exponential backoff

            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                return {
                    "status": "error",
                    "data": None,
                    "status_code": None,
                    "error": f"Unexpected error: {str(e)}"
                }

        # Should not reach here
        return {
            "status": "error",
            "data": None,
            "status_code": None,
            "error": "Max retries exceeded"
        }
