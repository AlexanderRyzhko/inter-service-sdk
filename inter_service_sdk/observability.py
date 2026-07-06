"""Shared observability write-client (BLA-1342).

Single source of truth for the observability write-contract (Family 2 of
``ContentGeneratorAPI/docs/contracts/user-data-and-observability-write-contract.md``).
Extracted from the per-service hand-rolled writers (BLA-1330 / BLA-1339 /
BLA-1349) so in-VPC services stop re-deriving identity stamping, the
tenant-scoped ``agent_runs`` ``_id``, the null-``user_id`` drop, fire-and-forget,
and batch caps by hand (each re-derivation was a review-round bug source).

Three sibling collections in the BLA-1330 DocumentDB (database ``post_scaffolds``):

  - ``llm_traces``   — one doc per LLM call (input/output/tokens/latency/status)
  - ``tool_calls``   — one doc per tool invocation (args/result/latency/status)
  - ``agent_runs``   — one doc per agent turn, ties its LLM + tool calls by run_id

Two surfaces, one contract:

  * **Typed record builders** (:func:`llm_trace` / :func:`tool_call` /
    :func:`agent_run`) + :func:`validate_batch` — pure-dict, no DB dependency.
    Usable by any producer (also mirrored by the CGApp TypeScript client, which
    POSTs the same records to the ingestion endpoint).
  * :class:`ObservabilityWriter` — the in-VPC direct DocumentDB writer. It takes
    an **injected** async database handle (Motor ``AsyncIOMotorDatabase`` or a
    test double) — it does NOT reach into any service's ``get_db()``/``settings``.

``pymongo`` is required only by :class:`ObservabilityWriter` (bulk upsert ops).
It is imported lazily so ``import inter_service_sdk`` works without it; install
the extra: ``pip install inter-service-sdk[observability]``. The builders and
:func:`validate_batch` have no third-party dependency.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional

logger = logging.getLogger(__name__)

# --- Record kinds ---------------------------------------------------------
LLM_TRACE = "llm_trace"
TOOL_CALL = "tool_call"
AGENT_RUN = "agent_run"

LLM_TRACES = "llm_traces"
TOOL_CALLS = "tool_calls"
AGENT_RUNS = "agent_runs"

KIND_TO_COLLECTION = {
    LLM_TRACE: LLM_TRACES,
    TOOL_CALL: TOOL_CALLS,
    AGENT_RUN: AGENT_RUNS,
}

# One agent turn produces at most a handful of LLM + tool records; anything
# beyond this is abuse or a bug. Over-cap is a client error (the ingestion
# endpoint maps :class:`BatchTooLargeError` to HTTP 422).
DEFAULT_MAX_RECORDS_PER_BATCH = 1000

# Hard wall-clock bound on a single persist attempt so a DocumentDB outage /
# slow server-selection can't leave background write tasks hanging for the
# driver's default (~30s) and piling up under a sustained outage.
DEFAULT_WRITE_TIMEOUT_S = 5

# Traces are ephemeral triage/debug data.
DEFAULT_TTL_DAYS = 30


class ObservabilityError(Exception):
    """Base class for observability write-client errors."""


class BatchTooLargeError(ObservabilityError, ValueError):
    """A batch exceeds ``max_records_per_batch`` (endpoint maps this to 422)."""


class InvalidRecordError(ObservabilityError, ValueError):
    """A record is missing a required field (``kind`` or ``run_id``)."""


# --- Typed record builders (pure dict, no DB dependency) ------------------

def _record(kind: str, run_id: str, fields: Mapping[str, Any], extra: Mapping[str, Any]) -> Dict[str, Any]:
    """Assemble a trace record: ``kind`` + ``run_id`` (both required) plus the
    non-``None`` typed fields and any forward-compat ``extra``.

    Identity (``user_id`` / ``client_email``) is deliberately NOT set here — it
    is server-authoritative and stamped at write time (in-VPC by
    :class:`ObservabilityWriter`, out-of-VPC by the ingestion endpoint). Any
    caller-supplied ``user_id`` / ``client_email`` / ``_id`` is dropped.
    """
    if not run_id:
        raise InvalidRecordError(f"{kind} record requires a non-empty run_id")
    rec: Dict[str, Any] = {"kind": kind, "run_id": run_id}
    for key, value in fields.items():
        if value is not None:
            rec[key] = value
    for key, value in extra.items():
        if key not in ("kind", "run_id", "user_id", "client_email", "_id"):
            rec[key] = value
    return rec


def llm_trace(
    run_id: str,
    *,
    model: Optional[str] = None,
    input: Any = None,
    output: Any = None,
    tokens: Any = None,
    latency_ms: Optional[float] = None,
    status: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build an ``llm_trace`` record (one per LLM call)."""
    return _record(
        LLM_TRACE,
        run_id,
        {
            "model": model,
            "input": input,
            "output": output,
            "tokens": tokens,
            "latency_ms": latency_ms,
            "status": status,
        },
        extra,
    )


def tool_call(
    run_id: str,
    *,
    tool_name: Optional[str] = None,
    tool_use_id: Optional[str] = None,
    args: Any = None,
    result: Any = None,
    latency_ms: Optional[float] = None,
    status: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a ``tool_call`` record (one per tool invocation).

    ``status`` is ``ok`` | ``error`` per the contract; not hard-enforced
    (records are schema-flexible), but the typed surface documents the shape.
    """
    return _record(
        TOOL_CALL,
        run_id,
        {
            "tool_name": tool_name,
            "tool_use_id": tool_use_id,
            "args": args,
            "result": result,
            "latency_ms": latency_ms,
            "status": status,
        },
        extra,
    )


def agent_run(
    run_id: str,
    *,
    session_id: Optional[str] = None,
    success: Optional[bool] = None,
    total_latency_ms: Optional[float] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build an ``agent_run`` record (one per agent turn; upserted by
    tenant-scoped ``_id`` at write time)."""
    return _record(
        AGENT_RUN,
        run_id,
        {
            "session_id": session_id,
            "success": success,
            "total_latency_ms": total_latency_ms,
        },
        extra,
    )


def validate_batch(
    records: Iterable[Mapping[str, Any]],
    *,
    max_records: int = DEFAULT_MAX_RECORDS_PER_BATCH,
) -> List[Mapping[str, Any]]:
    """Validate an ingest batch at the boundary, RAISING on violation.

    This is the caller-side gate (mirrors the ingestion endpoint's 422):
      * over ``max_records`` → :class:`BatchTooLargeError`
      * a record missing ``kind`` or ``run_id`` → :class:`InvalidRecordError`

    Distinct from :meth:`ObservabilityWriter.write_records`, which is
    fire-and-forget and never raises. Call ``validate_batch`` synchronously at
    the request boundary, then schedule the write off the request path.

    Returns the records as a list (so a one-shot iterable isn't consumed twice).
    """
    batch = list(records)
    if len(batch) > max_records:
        raise BatchTooLargeError(
            f"batch of {len(batch)} records exceeds max_records={max_records}"
        )
    for rec in batch:
        if not rec.get("kind"):
            raise InvalidRecordError("record missing required field 'kind'")
        if not rec.get("run_id"):
            raise InvalidRecordError("record missing required field 'run_id'")
    return batch


# --- In-VPC direct DocumentDB writer --------------------------------------

def _agent_run_id(user_id: str, run_id: str) -> str:
    """Tenant-scoped document id for an ``agent_run``.

    The upsert key MUST include the authenticated ``user_id`` — ``run_id`` is a
    client-supplied field (e.g. CGApp requestId), so keying on it alone would
    let one authenticated user overwrite another's agent_run doc (and re-brand
    it with the attacker's identity). Scoping by ``user_id`` closes that
    cross-tenant collision while preserving per-turn upsert semantics.
    """
    return f"{user_id}:{run_id}"


class ObservabilityWriter:
    """Fire-and-forget writer for the three trace collections.

    Construct once per service with an injected async database handle::

        from inter_service_sdk.observability import ObservabilityWriter
        writer = ObservabilityWriter(get_db())          # Motor AsyncIOMotorDatabase
        await writer.write_records(records, user_id=ctx.s3_user_id,
                                   client_email=ctx.email)

    All contract invariants live here, once:
      * **Server-authoritative identity** — ``user_id`` / ``client_email`` are
        stamped from the caller's authenticated context and overwrite anything
        in the record; a client-supplied ``_id`` is dropped.
      * **Null-``user_id`` drop** — a write with no authenticated ``user_id``
        (service-principal / API-key callers) is dropped whole, so traces never
        collapse into a shared ``None:<run_id>`` namespace or lose attribution.
      * **``agent_runs`` merge upsert** — keyed by tenant-scoped
        ``_id = "<user_id>:<run_id>"`` via ``$set`` (not replace) so a later
        finalize can't clobber earlier fields and unordered same-batch
        open+finalize ops converge.
      * **Fire-and-forget** — :meth:`write_records` never raises and never runs
        longer than ``write_timeout_s``; safe to ``asyncio.create_task`` off a
        request path.
    """

    def __init__(
        self,
        db: Any,
        *,
        ttl_days: int = DEFAULT_TTL_DAYS,
        max_records_per_batch: int = DEFAULT_MAX_RECORDS_PER_BATCH,
        write_timeout_s: float = DEFAULT_WRITE_TIMEOUT_S,
    ) -> None:
        self._db = db
        self._ttl_seconds = int(ttl_days) * 24 * 60 * 60
        self.max_records_per_batch = max_records_per_batch
        self.write_timeout_s = write_timeout_s
        self._indexes_ensured = False

    @staticmethod
    def _require_pymongo():
        """Lazy-import the pymongo symbols the writer needs.

        Kept out of module import so ``import inter_service_sdk`` (and the pure
        builders) work without pymongo. Consumers of the writer already ship
        motor/pymongo; install the extra otherwise.
        """
        try:
            from pymongo import UpdateOne
            from pymongo.errors import BulkWriteError, OperationFailure
        except ImportError as e:  # pragma: no cover - environment guard
            raise ObservabilityError(
                "ObservabilityWriter requires pymongo. Install it with: "
                "pip install inter-service-sdk[observability]"
            ) from e
        return UpdateOne, BulkWriteError, OperationFailure

    def _stamp(self, record: Mapping[str, Any], *, user_id: str, client_email: Optional[str]) -> Dict[str, Any]:
        """Return a copy of ``record`` with server-authoritative identity + timestamp.

        ``user_id`` / ``client_email`` ALWAYS come from the caller's
        authenticated context and overwrite anything the record carried — a
        trace's identity cannot be forged from the payload. Any supplied ``_id``
        is dropped so the caller cannot squat/collide on document ids.
        """
        doc = dict(record)
        doc.pop("_id", None)
        doc["user_id"] = user_id
        doc["client_email"] = client_email
        doc["received_at"] = datetime.now(timezone.utc)
        return doc

    async def ensure_trace_indexes(self) -> None:
        """Create TTL indexes on the three trace collections (idempotent, best-effort).

        Runs lazily once per process on first write. Never raises — an
        index-creation failure must not break the write path (docs simply won't
        auto-expire until the index lands).
        """
        if self._indexes_ensured:
            return
        _, _, OperationFailure = self._require_pymongo()

        all_handled = True
        for coll in (LLM_TRACES, TOOL_CALLS, AGENT_RUNS):
            try:
                await self._db[coll].create_index("received_at", expireAfterSeconds=self._ttl_seconds)
            except OperationFailure as e:  # noqa: BLE001 — best-effort, never raise
                if getattr(e, "code", None) == 85:  # IndexOptionsConflict
                    # Mutating a TTL needs a manual collMod/drop, not
                    # create_index. Existing index stays authoritative — this
                    # collection is "handled"; keep going.
                    logger.warning(
                        "%s TTL index already exists with a different TTL; changing the "
                        "TTL requires a manual index drop or collMod. Keeping the "
                        "existing index. (%s)", coll, e,
                    )
                else:
                    all_handled = False
                    logger.warning("Failed to ensure TTL index on %s: %s", coll, e)
            except Exception as e:  # noqa: BLE001 — best-effort, never raise
                all_handled = False
                logger.warning("Failed to ensure TTL index on %s: %s", coll, e)

        # Only latch once every collection has an index or a permanent conflict;
        # a transient failure leaves it False to retry on the next write.
        if all_handled:
            self._indexes_ensured = True
            logger.info("Observability TTL indexes ensured (ttl=%ss)", self._ttl_seconds)

    async def write_records(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        user_id: Optional[str],
        client_email: Optional[str],
    ) -> int:
        """Persist a batch of trace records, fire-and-forget.

        Never raises and never runs longer than ``write_timeout_s`` — safe to
        ``asyncio.create_task`` off a request path. Each record is a dict
        carrying a ``kind`` (``llm_trace`` | ``tool_call`` | ``agent_run``) and a
        ``run_id``. Returns the count of records successfully written.
        """
        batch = list(records)
        # Identity is REQUIRED. ``user_id`` is nullable for some authenticated
        # callers (service-principal / API-key tokens). Writing with a null
        # user_id would (a) collapse all such callers into a shared
        # ``None:<run_id>`` upsert namespace — re-opening the cross-tenant
        # clobber the composite key exists to prevent — and (b) drop attribution
        # / break the cross-store corpus join keyed on client_email. Drop the
        # batch instead.
        if not user_id:
            logger.warning(
                "Observability write dropped: no authenticated user_id "
                "(identity required for tenant-scoped traces); %d record(s)",
                len(batch),
            )
            return 0

        try:
            return await asyncio.wait_for(
                self._persist(batch, user_id=user_id, client_email=client_email),
                timeout=self.write_timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Observability write timed out after %ss; dropping %d record(s)",
                self.write_timeout_s, len(batch),
            )
            return 0
        except Exception as e:  # noqa: BLE001 — never surface a trace-write failure
            logger.warning("Observability write failed, dropping %d record(s): %s",
                           len(batch), e)
            return 0

    async def _persist(self, records: List[Mapping[str, Any]], *, user_id: str, client_email: Optional[str]) -> int:
        """Group records by kind and write them in bulk (one round-trip per
        collection). Wrapped by :meth:`write_records` for timeout + never-raise."""
        UpdateOne, _, _ = self._require_pymongo()
        await self.ensure_trace_indexes()

        llm_docs: List[dict] = []
        tool_docs: List[dict] = []
        run_ops: list = []
        for record in records:
            kind = record.get("kind")
            doc = self._stamp(record, user_id=user_id, client_email=client_email)
            if kind == LLM_TRACE:
                llm_docs.append(doc)
            elif kind == TOOL_CALL:
                tool_docs.append(doc)
            elif kind == AGENT_RUN:
                # One agent_run per turn, keyed by tenant-scoped id, merge-style
                # `$set` upsert (NOT a full replace): the run is opened at chat()
                # entry and finalized at the result message, so a later finalize
                # that omits early fields (e.g. session_id) must NOT clobber
                # them, and unordered same-batch open+finalize ops converge.
                run_id = doc.get("run_id")
                if not run_id:
                    logger.warning("agent_run record missing run_id, skipping")
                    continue
                _id = _agent_run_id(user_id, run_id)
                set_doc = {k: v for k, v in doc.items() if k != "_id"}
                run_ops.append(UpdateOne({"_id": _id}, {"$set": set_doc}, upsert=True))
            else:
                logger.warning("Unknown observability record kind=%r, skipping", kind)

        dispatched = 0
        dispatched += await self._write_batch(self._db[LLM_TRACES], "insert_many", llm_docs)
        dispatched += await self._write_batch(self._db[TOOL_CALLS], "insert_many", tool_docs)
        dispatched += await self._write_batch(self._db[AGENT_RUNS], "bulk_write", run_ops)
        return dispatched

    async def _write_batch(self, coll: Any, op: str, payload: list) -> int:
        """Run one grouped write against ``coll``, fire-and-forget.

        ``op`` is ``insert_many`` or ``bulk_write``. Returns the number of
        records written, or the partial count on ``BulkWriteError`` (logged,
        never raised). ``ordered=False`` so one bad doc doesn't abort the group.
        """
        if not payload:
            return 0
        _, BulkWriteError, _ = self._require_pymongo()
        try:
            if op == "insert_many":
                await coll.insert_many(payload, ordered=False)
            else:
                await coll.bulk_write(payload, ordered=False)
            return len(payload)
        except BulkWriteError as e:  # noqa: BLE001 — partial success, count what landed
            details = getattr(e, "details", None) or {}
            written = (
                details.get("nInserted", 0)
                + details.get("nUpserted", 0)
                + details.get("nModified", 0)
            )
            logger.warning("Partial %s write: %d/%d record(s) landed; %s",
                           op, written, len(payload), e)
            return written
        except Exception as e:  # noqa: BLE001 — per-group best-effort
            logger.warning("Failed to write %d %s record(s): %s", len(payload), op, e)
            return 0
