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
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

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

# Traces are long-lived audit/analysis data (BLA-1753): 5 years. Services
# override per-env from the shared ``OBSERVABILITY_TRACE_TTL_DAYS`` secret key;
# this constant is only the fallback when nothing is configured.
DEFAULT_TTL_DAYS = 1825

# Minimum wall-clock gap between re-probes of an index whose live TTL could not
# be read. Bounds the round-trip cost against a degraded store; the retry budget
# then measures elapsed recovery time rather than caller volume.
DEFAULT_PROBE_COOLDOWN_S = 30.0


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
        probe_cooldown_s: float = DEFAULT_PROBE_COOLDOWN_S,
    ) -> None:
        self._db = db
        self._ttl_seconds = int(ttl_days) * 24 * 60 * 60
        self.max_records_per_batch = max_records_per_batch
        self.write_timeout_s = write_timeout_s
        self._indexes_ensured = False
        # An index conflict whose live TTL cannot be read is retried on later
        # writes (the store may recover), but bounded — an unbounded re-probe
        # costs 2 extra round trips per collection on every write batch.
        self._conflict_probe_attempts = 0
        self._max_conflict_probes = 3
        # Per-collection classification cache. A code-85 conflict is terminal for
        # that collection, so it must never be re-probed or re-reported just
        # because a SIBLING collection failed for an unrelated reason (e.g. a
        # code-13 Unauthorized) and kept the latch open.
        self._conflict_outcomes: Dict[str, str] = {}
        # Signature of the last rollup emitted, NOT a bool. A process-global
        # "already logged" flag meant an initial "unreadable" summary suppressed
        # the real by-remedy rollup forever once the store recovered and the same
        # collections reclassified as genuinely stale.
        self._conflict_summary_signature: Optional[tuple] = None
        # Single-flight guard. The attempt counter below assumes passes are
        # spread over SUCCESSIVE write batches; without this, a burst of
        # concurrent first writes (the advertised ``asyncio.create_task``
        # pattern) all clear the latch check before their first await, so they
        # probe in parallel and blow past the bound in one go. Set and checked
        # synchronously, so no asyncio.Lock and no loop-binding concern.
        self._ensure_in_flight = False
        # Single-flight alone is NOT enough: inside one asyncio.gather each write
        # still runs a full pass once the previous one finished, so a burst of N
        # first writes spent the whole retry budget immediately and latched on
        # "unknown". Re-probing is therefore also rate-limited in wall clock, so
        # the budget measures elapsed recovery time rather than caller volume.
        self._probe_cooldown_s = probe_cooldown_s
        self._last_probe_monotonic: Optional[float] = None

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

    async def _live_ttl_seconds(self, coll: str) -> Tuple[str, Optional[int]]:
        """Inspect the live ``received_at`` index.

        Returns ``(status, expire_after_seconds)`` where status is:
          * ``"ok"``         — a TTL index was found; the value is its TTL
          * ``"no_ttl"``     — a ``received_at`` index exists but carries no
            ``expireAfterSeconds`` (i.e. never expires), or none was found
          * ``"unreadable"`` — the metadata query failed

        ``no_ttl`` and ``unreadable`` are distinguished so the operator-facing
        message doesn't assert an index exists when we could not look.
        """
        # The spec walk stays INSIDE the try. This runs from inside
        # ensure_trace_indexes' ``except OperationFailure`` handler, and Python
        # does not re-dispatch to a sibling ``except`` of the same try — so
        # anything raised here would escape a method documented as never raising.
        try:
            info = await self._db[coll].index_information()
            for spec in (info or {}).values():
                keys = spec.get("key") if isinstance(spec, dict) else None
                if keys and list(keys)[0][0] == "received_at" and "expireAfterSeconds" in spec:
                    return "ok", int(spec["expireAfterSeconds"])
        except Exception as e:  # noqa: BLE001 — best-effort, never raise
            logger.warning("Could not read index info for %s: %s", coll, e)
            return "unreadable", None
        return "no_ttl", None

    async def _report_index_conflict(self, coll: str, exc: Exception) -> str:
        """Log an ACTIONABLE error for an ``IndexOptionsConflict`` (code 85).

        Returns the classification so the caller can summarize by REMEDY —
        ``"stale_ttl"`` (collMod), ``"no_ttl"`` (drop + recreate),
        ``"unreadable"`` (state unknown, nothing to prescribe) or ``"other"``
        (TTL is fine, the conflict is on another option). Lumping these together
        produced a summary promising a collMod for an index that needs
        drop+recreate instead.

        Code 85 is a GENERIC index-options conflict, not a TTL-specific one — it
        also fires for a mismatch on name, ``partialFilterExpression``,
        ``unique``, and so on. Classifying every code 85 as a stale TTL emitted a
        ``collMod expireAfterSeconds`` remedy that would not fix the actual
        conflict, and claimed a mismatch even when the live TTL already equalled
        the configured one. Read the live value and branch on it.
        """
        status, live = await self._live_ttl_seconds(coll)

        if status == "ok" and live == self._ttl_seconds:
            # TTL matches; the conflict is on some OTHER index option. A collMod
            # of expireAfterSeconds would be a no-op, so don't suggest it.
            logger.error(
                "%s received_at index conflicts on an option other than the TTL "
                "(live TTL is %ss, matching the configured ttl_days=%s): %s. The "
                "existing index stays authoritative — inspect it with "
                "db.%s.getIndexes().",
                coll, live, self._ttl_seconds // 86400, exc, coll,
            )
            return "other"

        if status == "no_ttl":
            # A received_at index with no expireAfterSeconds never expires.
            # collMod cannot add a TTL to a non-TTL index — that needs
            # drop + recreate.
            logger.error(
                "%s has a received_at index with NO expireAfterSeconds (it never "
                "expires), so configured ttl_days=%s is not in effect: %s. It must be "
                "dropped and recreated with the TTL — collMod cannot add one. Inspect "
                "with db.%s.getIndexes().",
                coll, self._ttl_seconds // 86400, exc, coll,
            )
            return "no_ttl"

        if status == "unreadable":
            logger.error(
                "%s index options conflict and the live TTL could NOT be read, so "
                "configured ttl_days=%s is not known to be in effect: %s. Inspect "
                "with db.%s.getIndexes().",
                coll, self._ttl_seconds // 86400, exc, coll,
            )
            return "unreadable"

        await self._report_stale_ttl(coll, live)
        return "stale_ttl"

    async def _report_stale_ttl(self, coll: str, live: int) -> bool:
        """Log an ACTIONABLE error for a TTL index that doesn't match config.

        Deliberately read-only. ``create_index`` cannot mutate
        ``expireAfterSeconds`` (it raises ``IndexOptionsConflict``, code 85) and
        only ``collMod`` can — but this library does NOT issue it. These three
        collections are a SHARED, multi-writer store: a ``collMod`` from any one
        consumer, including one whose config simply hasn't been updated yet,
        irreversibly deletes every document older than its own TTL, on data the
        other writers own. That is not a decision a background write path should
        make. Applying a TTL change is an operator action, run once per
        environment with an admin role.

        What this fixes relative to the pre-BLA-1753 behaviour is the *signal*.
        The old log named the remedy generically ("changing the TTL requires a
        manual index drop or collMod") but at WARNING, and it named neither the
        live value, the configured value, nor the command to run — and prod
        consequently sat at 30d for the whole life of
        ``OBSERVABILITY_TRACE_TTL_DAYS=365``. This logs at ERROR with both
        numbers and the exact command, so it is greppable and alertable.
        """
        # Raw seconds, not floor-divided days: the live value comes from the
        # server and need not be day-aligned. `live // 86400` printed a 3600s TTL
        # as "0d" (indistinguishable from a real expireAfterSeconds: 0) and a
        # 1825d+1h TTL as "1825d" — asserting a mismatch while showing two
        # identical numbers, which reads as an SDK bug and gets dismissed.
        logger.error(
            "%s TTL index is STALE: live=%ss (~%sd), configured ttl_days=%s "
            "(%ss). Retention will NOT change until an operator applies it (this "
            "library never mutates a shared TTL index). Run: db.runCommand("
            "{collMod: \"%s\", index: {keyPattern: {received_at: 1}, "
            "expireAfterSeconds: %s}})",
            coll, live, live // 86400, self._ttl_seconds // 86400,
            self._ttl_seconds, coll, self._ttl_seconds,
        )
        return True

    async def ensure_trace_indexes(self) -> None:
        """Create TTL indexes on the three trace collections (idempotent, best-effort).

        Runs lazily once per process on first write. Never raises — an
        index-creation failure must not break the write path (docs simply won't
        auto-expire until the index lands).

        An index that already conflicts is reported, not rewritten: see
        :meth:`_report_index_conflict` for the classification, and
        :meth:`_report_stale_ttl` for why mutating a shared TTL index is an
        operator action rather than a library one.
        """
        # Both the check and the set are synchronous — no await between them —
        # so this is atomic within an event loop. A concurrent write that finds
        # a pass already in flight simply proceeds; index bookkeeping is
        # best-effort and the in-flight pass will finish it.
        if self._indexes_ensured or self._ensure_in_flight:
            return
        # Every conflicting collection already has a verdict, and re-running
        # create_index only re-raises code 85; nothing can change before the next
        # probe is due. Rate-limit the WHOLE pass, not just the probe, so a
        # degraded store (the only state that leaves us unlatched) is not charged
        # 3 create_index round trips per write batch inside write_timeout_s.
        if self._conflict_outcomes and not self._cooldown_elapsed():
            return
        self._ensure_in_flight = True
        try:
            await self._ensure_trace_indexes_once()
        finally:
            self._ensure_in_flight = False

    def _cooldown_elapsed(self) -> bool:
        """True if enough wall clock has passed to justify another probe."""
        if self._last_probe_monotonic is None:
            return True
        return (time.monotonic() - self._last_probe_monotonic) >= self._probe_cooldown_s

    async def _ensure_trace_indexes_once(self) -> None:
        """One pass of :meth:`ensure_trace_indexes`, serialized by its caller."""
        _, _, OperationFailure = self._require_pymongo()
        probed = False

        all_handled = True
        by_remedy: Dict[str, List[str]] = {"stale_ttl": [], "no_ttl": [], "unreadable": []}
        for coll in (LLM_TRACES, TOOL_CALLS, AGENT_RUNS):
            try:
                await self._db[coll].create_index("received_at", expireAfterSeconds=self._ttl_seconds)
            except OperationFailure as e:  # noqa: BLE001 — best-effort, never raise
                if getattr(e, "code", None) == 85:  # IndexOptionsConflict
                    # Classify once per collection. Only an "unreadable" verdict
                    # is worth re-probing (the store may recover), and only
                    # while attempts remain.
                    # Classify once per collection. Only an "unreadable" verdict
                    # is worth re-probing (the store may recover), while attempts
                    # remain. The pass-level cooldown gate in the public entry
                    # point already guarantees the window has elapsed, so no
                    # second cooldown check is needed here.
                    cached = self._conflict_outcomes.get(coll)
                    retry_unknown = (
                        cached == "unreadable"
                        and self._conflict_probe_attempts < self._max_conflict_probes
                    )
                    if cached is not None and not retry_unknown:
                        outcome = cached
                    else:
                        outcome = await self._report_index_conflict(coll, e)
                        self._conflict_outcomes[coll] = outcome
                        probed = True
                        # Stamp the window on the probe itself — the event this
                        # timestamp names — rather than behind a separate guard.
                        self._last_probe_monotonic = time.monotonic()
                    if outcome in by_remedy:
                        by_remedy[outcome].append(coll)
                else:
                    all_handled = False
                    logger.warning("Failed to ensure TTL index on %s: %s", coll, e)
            except Exception as e:  # noqa: BLE001 — best-effort, never raise
                all_handled = False
                logger.warning("Failed to ensure TTL index on %s: %s", coll, e)

        # A conflict whose live state we COULD read is terminal — the existing
        # index stays authoritative and no retry changes that, so latch and let
        # the logged command be the escalation. An UNREADABLE live state is not
        # terminal: the store may recover and we would then owe an accurate
        # report. Retry it, but bounded, and rate-limited by the caller's gate.
        unreadable = by_remedy["unreadable"]
        if unreadable:
            # Count an ATTEMPT only when this pass actually probed. A pass that
            # short-circuited on the cached verdict cost nothing and must not
            # consume budget, or a burst of writes would exhaust it without a
            # single extra round trip.
            if probed:
                self._conflict_probe_attempts += 1
            if self._conflict_probe_attempts < self._max_conflict_probes:
                all_handled = False
            elif probed:
                # Budget exhausted on the pass that spent the last attempt: we
                # are about to latch and go silent, so announce the transition
                # from "still retrying" to "permanently unknown" explicitly.
                logger.error(
                    "Observability: retry budget exhausted after %d attempts; the "
                    "live TTL for %s is now permanently UNKNOWN for this process — "
                    "inspect with getIndexes().",
                    self._conflict_probe_attempts, ", ".join(unreadable),
                )

        if all_handled:
            self._indexes_ensured = True
            if not any(by_remedy.values()):
                logger.info("Observability TTL indexes ensured (ttl=%ss)", self._ttl_seconds)

        # The rollup is emitted whenever the CONFLICT STATE changes, whether or
        # not the latch was set. Two reasons it is not a one-shot flag:
        #   * a sibling failure (e.g. code 13) keeps all_handled False, and that
        #     is precisely where an operator most needs the summary;
        #   * an "unreadable" state can later reclassify to a real stale TTL, and
        #     that new remedy must be reported rather than suppressed by the
        #     earlier unknown-state rollup.
        # Keying on the signature also stops an unchanged state from re-logging.
        # Fold the attempt count into the "unreadable" bucket only, so the rollup
        # re-emits as the count climbs (2, 3) instead of freezing at 1 — a
        # readable-state remedy never changes across passes, but an unreadable
        # one's whole story is "we are still trying, now on attempt N".
        signature = tuple(
            (
                remedy,
                tuple(colls),
                self._conflict_probe_attempts if remedy == "unreadable" else None,
            )
            for remedy, colls in sorted(by_remedy.items()) if colls
        )
        if signature and signature != self._conflict_summary_signature:
            self._conflict_summary_signature = signature
            # Never claim "ensured (ttl=X)" while X is the value NOT in effect —
            # a false all-clear is the same misleading signal this change exists
            # to remove (BLA-1753). Summarize BY REMEDY: collMod fixes a stale
            # TTL, but a non-TTL index needs drop+recreate and an unknown state
            # needs inspection, so one blanket "run collMod" line would be wrong
            # for two of the three.
            if by_remedy["stale_ttl"]:
                logger.warning(
                    "Observability: %d collection(s) have a STALE TTL awaiting a manual "
                    "collMod (%s); configured ttl_days=%s is NOT in effect for them.",
                    len(by_remedy["stale_ttl"]), ", ".join(by_remedy["stale_ttl"]),
                    self._ttl_seconds // 86400,
                )
            if by_remedy["no_ttl"]:
                logger.warning(
                    "Observability: %d collection(s) have a received_at index with NO "
                    "TTL (%s); they need a DROP + RECREATE, not a collMod.",
                    len(by_remedy["no_ttl"]), ", ".join(by_remedy["no_ttl"]),
                )
            if unreadable:
                logger.warning(
                    "Observability: %d collection(s) conflict with an unreadable live "
                    "TTL (%s) after %d attempt(s); state unknown — inspect with "
                    "getIndexes() before assuming any remedy.",
                    len(unreadable), ", ".join(unreadable),
                    self._conflict_probe_attempts,
                )

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
        # Materialize inside the guard: an input generator that raises mid
        # iteration must not escape the never-raise contract either.
        try:
            batch = list(records)
        except Exception as e:  # noqa: BLE001 — never surface a producer failure
            logger.warning("Observability write dropped: record iterable raised: %s", e)
            return 0

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

        # Fail-safe: the tenant-scoped agent_runs id is the contract string
        # ``"<user_id>:<run_id>"``. A ``:`` inside user_id would make that key
        # non-injective (two distinct (user_id, run_id) pairs could collide),
        # re-opening a cross-tenant clobber. Real identities (s3_user_id slug /
        # UUID) never contain ``:`` — drop defensively if one ever does rather
        # than write a colliding key.
        if ":" in user_id:
            logger.warning(
                "Observability write dropped: user_id contains ':' separator "
                "(would break tenant-scoped agent_run id); %d record(s)",
                len(batch),
            )
            return 0

        # Batch cap backstop. The boundary gate ``validate_batch`` RAISES (→ 422)
        # for well-behaved callers; the writer is fire-and-forget, so an
        # over-cap batch that reached it (a caller that skipped the gate) is
        # dropped with a warning rather than raised. Not a silent no-op — the
        # configured cap is enforced here too.
        if len(batch) > self.max_records_per_batch:
            logger.warning(
                "Observability write dropped: batch of %d exceeds "
                "max_records_per_batch=%d",
                len(batch), self.max_records_per_batch,
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


# --- Sync-safe transport (daemon-thread submitter) ------------------------

# Default depth of the in-memory hand-off queue between the (sync) request
# thread and the writer loop. Bounded so a trace-store outage can't grow memory
# without limit; on overflow ``put_nowait`` raises QueueFull and the incoming
# (newest) submit is dropped with a countable log — the backlog is preserved.
DEFAULT_QUEUE_MAX = 1000

# Sentinel so ``submit(user_id=None)`` (an explicit, meaningful null) is
# distinguishable from "identity not supplied, fall back to the constructor
# default".
_UNSET = object()


def _documentdb_client_kwargs(mongo_uri: str, tls_ca_file: Optional[str]) -> Dict[str, Any]:
    """Motor client kwargs honoring the AWS DocumentDB contract.

    DocumentDB requires TLS and does NOT support retryable writes — motor's
    default ``retryWrites=True`` makes every insert raise. When a TLS CA is
    configured (the DocumentDB path) default ``retryWrites=False`` unless the URI
    already pins it. Mirrors the pattern the per-service writers used before the
    transport was folded into the SDK.
    """
    kwargs: Dict[str, Any] = {"serverSelectionTimeoutMS": 5000}
    if tls_ca_file:
        kwargs["tls"] = True
        kwargs["tlsCAFile"] = tls_ca_file
        if "retrywrites" not in mongo_uri.lower():
            kwargs["retryWrites"] = False
    return kwargs


class ObservabilitySubmitter:
    """Fire-and-forget-from-sync transport wrapping :class:`ObservabilityWriter`.

    ``ObservabilityWriter.write_records`` is a coroutine: it assumes a **live**
    event loop it can be awaited on (async callers ``asyncio.create_task`` it off
    a request path). Sync callers can't — e.g. radaric's concept extraction runs
    ``Runner.run_sync`` → ``loop.run_until_complete``; that loop stops the instant
    the wrapped call returns, so a task scheduled on it would never run and the
    trace would be lost.

    This transport owns a dedicated daemon thread running its own event loop,
    created lazily on first :meth:`submit`. ``submit`` hands the batch to that
    loop via ``call_soon_threadsafe`` and returns immediately — safe to call from
    any thread, with or without a running loop.

    Persistence is delegated to a single :class:`ObservabilityWriter` built on the
    worker loop, so every contract invariant (server-authoritative identity stamp,
    tenant-scoped ``agent_runs._id``, null-``user_id`` drop, TTL indexes, batch
    cap, per-write timeout, never-raise) is reused — NOT re-derived here.

    The db handle is built lazily on the worker loop via ``db_factory`` because
    Motor clients bind to the loop that is running when they are created; building
    it eagerly on the caller's thread would bind it to the wrong loop and writes
    would hang. Use :meth:`from_motor_uri` for the common URI case.
    """

    def __init__(
        self,
        db_factory: Callable[[], Any],
        *,
        user_id: Optional[str] = None,
        client_email: Optional[str] = None,
        ttl_days: int = DEFAULT_TTL_DAYS,
        max_records_per_batch: int = DEFAULT_MAX_RECORDS_PER_BATCH,
        write_timeout_s: float = DEFAULT_WRITE_TIMEOUT_S,
        queue_max: int = DEFAULT_QUEUE_MAX,
    ) -> None:
        self._db_factory = db_factory
        self._default_user_id = user_id
        self._default_client_email = client_email
        self._writer_kwargs = dict(
            ttl_days=ttl_days,
            max_records_per_batch=max_records_per_batch,
            write_timeout_s=write_timeout_s,
        )
        self._queue_max = queue_max
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: Optional[asyncio.Queue] = None
        self._writer: Optional[ObservabilityWriter] = None
        self._consumer_task: Optional[asyncio.Task] = None
        self._ready = threading.Event()
        self.dropped = 0
        self.submitted = 0

    @classmethod
    def from_motor_uri(
        cls,
        mongo_uri: str,
        db_name: str,
        *,
        tls_ca_file: Optional[str] = None,
        **kwargs: Any,
    ) -> "ObservabilitySubmitter":
        """Build a submitter whose db handle is a Motor database at ``mongo_uri``.

        The Motor client is created lazily on the worker loop (see class docs).
        ``motor`` is imported inside the factory so importing the SDK doesn't
        require it — install the ``observability`` extra (motor→pymongo).
        """

        def factory() -> Any:
            from motor.motor_asyncio import AsyncIOMotorClient

            client = AsyncIOMotorClient(
                mongo_uri, **_documentdb_client_kwargs(mongo_uri, tls_ca_file)
            )
            return client[db_name]

        return cls(factory, **kwargs)

    # --- public: safe to call from any thread (the request path) ------------

    def submit(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        user_id: Any = _UNSET,
        client_email: Any = _UNSET,
    ) -> bool:
        """Enqueue a batch for fire-and-forget writing. Never raises.

        Identity precedence: an explicit ``user_id`` / ``client_email`` argument
        (including an explicit ``None``) wins over the constructor default. The
        actual write applies all writer invariants (null-drop, cap, stamp, etc.);
        this method only hands work to the writer loop and returns immediately.

        Returns ``True`` if the batch was handed off, ``False`` if it was dropped
        (bad iterable or the worker could not be reached).
        """
        uid = self._default_user_id if user_id is _UNSET else user_id
        email = self._default_client_email if client_email is _UNSET else client_email
        try:
            batch = list(records)
        except Exception:  # noqa: BLE001 — a producer failure must not escape
            logger.warning("observability submit dropped: record iterable raised", exc_info=True)
            return False
        try:
            loop = self._ensure_worker()
            loop.call_soon_threadsafe(self._put_nowait, (batch, uid, email))
            # submit() is documented safe from any thread, and `+=` is a
            # non-atomic read-modify-write, so guard the counter (uncontended
            # after worker warmup except vs. other concurrent submits).
            with self._lock:
                self.submitted += 1
            return True
        except Exception:  # noqa: BLE001 — fire-and-forget, never surface
            logger.debug("observability submit failed", exc_info=True)
            return False

    # --- worker thread internals --------------------------------------------

    def _ensure_worker(self) -> asyncio.AbstractEventLoop:
        if self._loop is not None:
            return self._loop
        with self._lock:
            if self._loop is not None:
                return self._loop
            loop = asyncio.new_event_loop()
            thread = threading.Thread(
                target=self._run_loop, args=(loop,),
                name="observability_submitter", daemon=True,
            )
            thread.start()
            self._loop = loop
            self._thread = thread
            # Do NOT wait for readiness here — this runs on the request path and
            # must stay fire-and-forget. ``call_soon_threadsafe`` tolerates a loop
            # that hasn't reached run_forever yet; the callback fires once it does
            # (after the queue is created). Readiness is only awaited in drain().
            return loop

    def _run_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_max)
        self._queue = queue
        self._consumer_task = loop.create_task(self._consume(queue))
        self._ready.set()
        loop.run_forever()

    def _put_nowait(self, item) -> None:
        # Runs on the worker loop.
        queue = self._queue
        if queue is None:
            return
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            self.dropped += 1
            logger.warning(
                "observability_submit event=drop reason=queue_full dropped_total=%d",
                self.dropped,
            )

    async def _consume(self, queue: asyncio.Queue) -> None:
        while True:
            item = await queue.get()
            try:
                writer = self._get_writer()
                if writer is not None:
                    batch, uid, email = item
                    # write_records is itself never-raising + time-bounded.
                    await writer.write_records(batch, user_id=uid, client_email=email)
                else:
                    # db_factory failed (bad URI / missing motor): count the
                    # discarded batch so `dropped` reflects DB-misconfig loss, not
                    # just queue overflow. Safe unlocked — worker thread only.
                    self.dropped += 1
            except Exception as exc:  # noqa: BLE001 — never propagate off the loop
                logger.warning("observability_submit event=error err=%s", exc)
            finally:
                queue.task_done()

    def _get_writer(self) -> Optional[ObservabilityWriter]:
        """Build the writer once, lazily, on the worker loop.

        A db_factory failure (bad URI, missing motor) is swallowed + logged so it
        never breaks the loop; the next submit retries construction.
        """
        if self._writer is not None:
            return self._writer
        try:
            db = self._db_factory()
        except Exception:  # noqa: BLE001 — best-effort; retry on next item
            logger.warning("observability_submit: db_factory failed (will retry)", exc_info=True)
            return None
        self._writer = ObservabilityWriter(db, **self._writer_kwargs)
        return self._writer

    # --- test / shutdown helpers --------------------------------------------

    async def drain(self) -> None:
        """Wait until the queue is fully processed (cross-thread safe, test-only)."""
        if self._loop is None:
            return
        await asyncio.get_event_loop().run_in_executor(None, self._ready.wait, 2)
        if self._queue is None:
            return
        fut = asyncio.run_coroutine_threadsafe(self._queue.join(), self._loop)
        await asyncio.wrap_future(fut)

    async def aclose(self) -> None:
        """Cleanly stop the worker thread/loop (cancel consumer, stop, close)."""
        loop, thread, task = self._loop, self._thread, self._consumer_task
        self._loop = None
        self._thread = None
        self._consumer_task = None
        self._queue = None
        self._writer = None
        self._ready.clear()
        if loop is None:
            return

        async def _shutdown() -> None:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            loop.stop()

        try:
            asyncio.run_coroutine_threadsafe(_shutdown(), loop)
        except RuntimeError:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            await asyncio.get_event_loop().run_in_executor(None, thread.join, 2)
        if (thread is None or not thread.is_alive()) and not loop.is_closed():
            loop.close()
