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
from .observability import (
    ObservabilityWriter,
    ObservabilitySubmitter,
    ObservabilityError,
    BatchTooLargeError,
    InvalidRecordError,
    validate_batch,
    llm_trace,
    tool_call,
    agent_run,
    LLM_TRACE,
    TOOL_CALL,
    AGENT_RUN,
    DEFAULT_MAX_RECORDS_PER_BATCH,
    DEFAULT_WRITE_TIMEOUT_S,
    DEFAULT_TTL_DAYS,
    DEFAULT_QUEUE_MAX,
)
from .tracing import (
    TRACE_HEADER,
    get_trace_id,
    set_trace_id,
    BlazelTracingMiddleware,
    BlazelTraceFilter,
)

__version__ = "1.3.1"

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
    # Observability write-client (BLA-1342)
    "ObservabilityWriter",
    # Sync-safe transport (BLA-1382)
    "ObservabilitySubmitter",
    "DEFAULT_QUEUE_MAX",
    "ObservabilityError",
    "BatchTooLargeError",
    "InvalidRecordError",
    "validate_batch",
    "llm_trace",
    "tool_call",
    "agent_run",
    "LLM_TRACE",
    "TOOL_CALL",
    "AGENT_RUN",
    "DEFAULT_MAX_RECORDS_PER_BATCH",
    "DEFAULT_WRITE_TIMEOUT_S",
    "DEFAULT_TTL_DAYS",
    # Tracing (BLA-1504)
    "TRACE_HEADER",
    "get_trace_id",
    "set_trace_id",
    "BlazelTracingMiddleware",
    "BlazelTraceFilter",
]
