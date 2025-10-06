"""
Inter-Service SDK - Complete framework for service-to-service communication.

Provides both client-side and server-side utilities:
- Client: InterServiceClient for making inter-service HTTP requests
- Server: FastAPI utilities for creating inter-service endpoints
- Crypto: Optional ECC encryption/decryption
- Exceptions: Custom exception hierarchy
"""

from .client import InterServiceClient
from .exceptions import (
    InterServiceError,
    AuthenticationError,
    RequestError,
    EncryptionError,
    URLBuildError
)
from .server import (
    create_inter_service_router,
    inter_service_endpoint
)

__version__ = "1.0.2"

__all__ = [
    # Client
    "InterServiceClient",
    # Exceptions
    "InterServiceError",
    "AuthenticationError",
    "RequestError",
    "EncryptionError",
    "URLBuildError",
    # Server utilities
    "create_inter_service_router",
    "inter_service_endpoint",
]
