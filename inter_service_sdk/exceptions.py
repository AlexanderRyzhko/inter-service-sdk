"""
Custom exceptions for inter-service SDK.
"""


class InterServiceError(Exception):
    """Base exception for inter-service SDK."""
    pass


class AuthenticationError(InterServiceError):
    """Authentication failed."""
    pass


class RequestError(InterServiceError):
    """Request failed."""

    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code


class EncryptionError(InterServiceError):
    """Encryption/decryption failed."""
    pass


class URLBuildError(InterServiceError):
    """URL building failed."""
    pass
