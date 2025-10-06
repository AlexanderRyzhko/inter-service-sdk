"""
Inter-Service SDK - Generic HTTP client for service-to-service communication.
"""

from .client import InterServiceClient
from .exceptions import (
    InterServiceError,
    AuthenticationError,
    RequestError,
    EncryptionError,
    URLBuildError
)

__version__ = "1.0.0"

__all__ = [
    "InterServiceClient",
    "InterServiceError",
    "AuthenticationError",
    "RequestError",
    "EncryptionError",
    "URLBuildError",
]
