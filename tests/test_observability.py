"""Tests for the shared observability write-client (BLA-1342).

Covers the two surfaces:
  * pure-dict builders + ``validate_batch`` (no DB)
  * ``ObservabilityWriter`` against a fake async db double — identity stamping,
    null-``user_id`` drop, tenant-scoped ``agent_runs`` upsert, exactly-one-write,
    fire-and-forget (never raises), and the time bound.
"""
import asyncio

import pytest

from inter_service_sdk.observability import (
    ObservabilityWriter,
    ObservabilitySubmitter,
    _documentdb_client_kwargs,
    BatchTooLargeError,
    InvalidRecordError,
    validate_batch,
    llm_trace,
    tool_call,
    agent_run,
    LLM_TRACES,
    TOOL_CALLS,
    AGENT_RUNS,
)


# --- Fake async DB double --------------------------------------------------

class FakeCollection:
    def __init__(self, name, recorder, *, raises=False, sleep=0.0):
        self.name = name
        self.recorder = recorder
        self.raises = raises
        self.sleep = sleep

    async def insert_many(self, docs, ordered=True):
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.raises:
            raise RuntimeError("simulated store outage")
        self.recorder.append(("insert_many", self.name, list(docs)))

    async def bulk_write(self, ops, ordered=True):
        if self.sleep:
            await asyncio.sleep(self.sleep)
        if self.raises:
            raise RuntimeError("simulated store outage")
        self.recorder.append(("bulk_write", self.name, list(ops)))

    async def create_index(self, *args, **kwargs):
        return "idx"


class FakeDB:
    def __init__(self, *, raises=False, sleep=0.0):
        self.calls = []
        self._colls = {}
        self._raises = raises
        self._sleep = sleep

    def __getitem__(self, name):
        if name not in self._colls:
            self._colls[name] = FakeCollection(
                name, self.calls, raises=self._raises, sleep=self._sleep
            )
        return self._colls[name]


def _writes(db):
    """Ops that actually hit a collection (excludes create_index)."""
    return db.calls


# --- Builders --------------------------------------------------------------

def test_llm_trace_builds_kind_run_id_and_drops_none():
    rec = llm_trace("run-1", model="claude", input="hi", output=None, latency_ms=12.0)
    assert rec["kind"] == "llm_trace"
    assert rec["run_id"] == "run-1"
    assert rec["model"] == "claude"
    assert rec["input"] == "hi"
    assert rec["latency_ms"] == 12.0
    assert "output" not in rec  # None dropped


def test_tool_call_and_agent_run_kinds():
    tc = tool_call("run-1", tool_name="search", tool_use_id="tu-1", status="ok")
    assert tc["kind"] == "tool_call" and tc["tool_name"] == "search"
    ar = agent_run("run-1", session_id="s-1", success=True, total_latency_ms=99)
    assert ar["kind"] == "agent_run" and ar["session_id"] == "s-1" and ar["success"] is True


def test_builders_reject_empty_run_id():
    with pytest.raises(InvalidRecordError):
        llm_trace("")
    with pytest.raises(InvalidRecordError):
        agent_run(None)


def test_builders_strip_client_supplied_identity_and_id():
    # A caller must not be able to smuggle identity or _id through the builder.
    rec = llm_trace("run-1", user_id="attacker", client_email="a@b.com", _id="squat")
    assert "user_id" not in rec
    assert "client_email" not in rec
    assert "_id" not in rec


def test_builder_keeps_forward_compat_extra():
    rec = tool_call("run-1", tool_name="x", custom_field="keep")
    assert rec["custom_field"] == "keep"


# --- validate_batch --------------------------------------------------------

def test_validate_batch_over_cap_raises():
    records = [llm_trace(f"r-{i}") for i in range(11)]
    with pytest.raises(BatchTooLargeError):
        validate_batch(records, max_records=10)


def test_validate_batch_missing_fields_raise():
    with pytest.raises(InvalidRecordError):
        validate_batch([{"run_id": "r-1"}])  # missing kind
    with pytest.raises(InvalidRecordError):
        validate_batch([{"kind": "llm_trace"}])  # missing run_id


def test_validate_batch_returns_list():
    gen = (llm_trace(f"r-{i}") for i in range(3))
    out = validate_batch(gen)
    assert isinstance(out, list) and len(out) == 3


# --- Writer: identity + routing + exactly-one-write ------------------------

async def test_write_routes_by_kind_and_counts_exactly_once():
    db = FakeDB()
    writer = ObservabilityWriter(db)
    records = [
        llm_trace("run-1", model="m"),
        tool_call("run-1", tool_name="t"),
        agent_run("run-1", session_id="s"),
    ]
    n = await writer.write_records(records, user_id="geoff", client_email="g@b.com")
    assert n == 3  # exactly one write per record

    ops = {(op, coll) for (op, coll, _payload) in _writes(db)}
    assert ("insert_many", LLM_TRACES) in ops
    assert ("insert_many", TOOL_CALLS) in ops
    assert ("bulk_write", AGENT_RUNS) in ops
    # each collection touched exactly once (no double-write)
    assert len(_writes(db)) == 3


async def test_write_stamps_server_identity_and_drops_client_identity():
    db = FakeDB()
    writer = ObservabilityWriter(db)
    # payload tries to forge identity + _id; server must overwrite/drop.
    rec = {"kind": "llm_trace", "run_id": "run-1", "user_id": "attacker",
           "client_email": "evil@x.com", "_id": "squat"}
    await writer.write_records([rec], user_id="geoff", client_email="g@b.com")
    (_op, _coll, docs) = _writes(db)[0]
    doc = docs[0]
    assert doc["user_id"] == "geoff"
    assert doc["client_email"] == "g@b.com"
    assert "_id" not in doc
    assert "received_at" in doc


async def test_agent_run_upsert_is_tenant_scoped_and_set_merge():
    db = FakeDB()
    writer = ObservabilityWriter(db)
    await writer.write_records(
        [agent_run("run-1", session_id="s-1")], user_id="geoff", client_email="g@b.com"
    )
    (_op, coll, ops) = _writes(db)[0]
    assert coll == AGENT_RUNS
    op = ops[0]
    # tenant-scoped _id + $set merge + upsert
    assert op._filter == {"_id": "geoff:run-1"}
    assert "$set" in op._doc
    assert op._doc["$set"]["session_id"] == "s-1"
    assert "_id" not in op._doc["$set"]
    assert op._upsert is True


async def test_null_user_id_drops_whole_batch_no_write():
    db = FakeDB()
    writer = ObservabilityWriter(db)
    n = await writer.write_records(
        [llm_trace("run-1")], user_id=None, client_email="g@b.com"
    )
    assert n == 0
    assert _writes(db) == []  # nothing written — no None:<run_id> namespace


async def test_unknown_kind_skipped():
    db = FakeDB()
    writer = ObservabilityWriter(db)
    n = await writer.write_records(
        [{"kind": "mystery", "run_id": "run-1"}], user_id="geoff", client_email="g@b.com"
    )
    assert n == 0
    assert _writes(db) == []


# --- Writer: fire-and-forget (never raises) + time bound -------------------

async def test_write_never_raises_on_store_error():
    db = FakeDB(raises=True)
    writer = ObservabilityWriter(db)
    # must return 0, never propagate
    n = await writer.write_records(
        [llm_trace("run-1")], user_id="geoff", client_email="g@b.com"
    )
    assert n == 0


async def test_write_times_out_and_drops():
    db = FakeDB(sleep=0.2)
    writer = ObservabilityWriter(db, write_timeout_s=0.05)
    n = await writer.write_records(
        [llm_trace("run-1")], user_id="geoff", client_email="g@b.com"
    )
    assert n == 0  # slow sink bounded, batch dropped, no raise


# --- Writer: cap backstop, colon guard, generator-raises -------------------

async def test_writer_enforces_batch_cap_backstop():
    # Writer cap is a real backstop for callers that skip validate_batch:
    # over-cap → drop + warn (fire-and-forget), not raise, not a no-op.
    db = FakeDB()
    writer = ObservabilityWriter(db, max_records_per_batch=2)
    records = [llm_trace(f"r-{i}") for i in range(3)]
    n = await writer.write_records(records, user_id="geoff", client_email="g@b.com")
    assert n == 0
    assert _writes(db) == []


async def test_writer_drops_user_id_with_colon():
    # A ':' in user_id would make the tenant-scoped agent_run _id non-injective.
    db = FakeDB()
    writer = ObservabilityWriter(db)
    n = await writer.write_records(
        [agent_run("run-1")], user_id="acme:corp", client_email="g@b.com"
    )
    assert n == 0
    assert _writes(db) == []


async def test_write_never_raises_on_generator_error():
    def bad_records():
        yield llm_trace("run-1")
        raise RuntimeError("producer blew up")

    db = FakeDB()
    writer = ObservabilityWriter(db)
    n = await writer.write_records(
        bad_records(), user_id="geoff", client_email="g@b.com"
    )
    assert n == 0  # producer failure swallowed, never escapes


# --- Sync-safe transport: ObservabilitySubmitter (BLA-1382) ----------------
# These are SYNC tests: the transport owns its own daemon thread + loop, so the
# test drives it from a plain sync context (which is the whole point — the caller
# has no live loop of its own).


def _drain_sync(sub, timeout=2.0):
    """Block the calling thread until the submitter's queue is fully processed."""
    sub._ready.wait(timeout)
    if sub._queue is None:
        return
    fut = asyncio.run_coroutine_threadsafe(sub._queue.join(), sub._loop)
    fut.result(timeout)


def _close_sync(sub):
    # Drive the production aclose() from a throwaway loop: it cancels the consumer
    # task and awaits it (so no task is left pending at GC), stops + joins the
    # worker thread, and closes the worker loop.
    if sub._loop is None:
        return
    tmp = asyncio.new_event_loop()
    try:
        tmp.run_until_complete(sub.aclose())
    finally:
        tmp.close()


def test_sync_submit_survives_loop_stop():
    # AC1: a sync caller whose event loop stops the instant the wrapped call
    # returns must NOT lose the write. asyncio.create_task on that dying loop
    # would; the daemon-thread submitter must not.
    db = FakeDB()
    sub = ObservabilitySubmitter(lambda: db)
    caller_loop = asyncio.new_event_loop()

    async def _do():
        sub.submit([llm_trace("run-1", model="m")], user_id="geoff", client_email="g@b.com")

    caller_loop.run_until_complete(_do())
    caller_loop.close()  # caller's loop is GONE — a task on it would never run

    _drain_sync(sub)
    assert any(coll == LLM_TRACES for (_op, coll, _p) in _writes(db))
    _close_sync(sub)


def test_submit_returns_immediately_and_never_raises_on_dead_sink():
    # AC2: submit is fire-and-forget even when the store is down — no raise, and
    # the batch is handed off. The write itself is swallowed by the writer.
    db = FakeDB(raises=True)
    sub = ObservabilitySubmitter(lambda: db)
    ok = sub.submit([llm_trace("run-1")], user_id="geoff", client_email="g@b.com")
    assert ok is True
    assert sub.submitted == 1
    _drain_sync(sub)  # completes without raising
    _close_sync(sub)


def test_submit_bad_iterable_returns_false():
    # AC2: a producer that raises while being materialized is dropped, not raised.
    def bad():
        yield llm_trace("run-1")
        raise RuntimeError("producer blew up")

    sub = ObservabilitySubmitter(lambda: FakeDB())
    assert sub.submit(bad()) is False
    _close_sync(sub)


def test_overflow_drops_countable():
    # AC2: a bounded queue drops on overflow with a countable counter (not a
    # silent no-op, not unbounded growth). Drive _put_nowait directly against a
    # pre-filled queue for a deterministic (timing-free) overflow.
    sub = ObservabilitySubmitter(lambda: FakeDB(), queue_max=1)
    q = asyncio.Queue(maxsize=1)
    q.put_nowait(("filled", "u", "e"))
    sub._queue = q
    sub._put_nowait(("overflow", "u", "e"))
    assert sub.dropped == 1


def test_db_factory_failure_counts_as_drop():
    # A persistent db_factory failure (bad URI / missing motor) discards the
    # batch — count it in `dropped` so alerting sees DB-misconfig loss, not only
    # queue overflow.
    def bad_factory():
        raise RuntimeError("bad uri")

    sub = ObservabilitySubmitter(bad_factory)
    sub.submit([llm_trace("run-1")], user_id="geoff", client_email="g@b.com")
    _drain_sync(sub)
    assert sub.dropped == 1
    _close_sync(sub)


def test_sync_transport_null_user_id_dropped_by_writer():
    # AC3: the transport reuses ObservabilityWriter, so the null-user_id whole-
    # batch drop still applies — nothing is written for an unauthenticated batch.
    db = FakeDB()
    sub = ObservabilitySubmitter(lambda: db)
    sub.submit([llm_trace("run-1")], user_id=None, client_email="g@b.com")
    _drain_sync(sub)
    assert _writes(db) == []
    _close_sync(sub)


def test_sync_transport_stamps_default_sentinel_identity():
    # AC3 + AC6: constructor identity (e.g. radaric-system sentinel) is applied
    # when submit passes no explicit identity, and the writer stamps it server-
    # authoritatively (received_at present).
    db = FakeDB()
    sub = ObservabilitySubmitter(lambda: db, user_id="radaric-system")
    sub.submit([llm_trace("run-1", model="m")])
    _drain_sync(sub)
    (_op, coll, docs) = _writes(db)[0]
    assert coll == LLM_TRACES
    assert docs[0]["user_id"] == "radaric-system"
    assert "received_at" in docs[0]
    _close_sync(sub)


def test_submit_explicit_identity_overrides_default():
    # Explicit submit identity wins over the constructor default.
    db = FakeDB()
    sub = ObservabilitySubmitter(lambda: db, user_id="radaric-system")
    sub.submit([llm_trace("run-1", model="m")], user_id="real-user", client_email="u@b.com")
    _drain_sync(sub)
    (_op, _coll, docs) = _writes(db)[0]
    assert docs[0]["user_id"] == "real-user"
    assert docs[0]["client_email"] == "u@b.com"
    _close_sync(sub)


# --- TTL index convergence (BLA-1753) --------------------------------------

class ConflictingCollection(FakeCollection):
    """create_index always reports the index exists with a different TTL."""

    async def create_index(self, *args, **kwargs):
        from pymongo.errors import OperationFailure

        raise OperationFailure("index already exists with different options", 85)


class ConflictingDB(FakeDB):
    """FakeDB whose collections conflict on create_index; records ``command``."""

    def __init__(self, *, collmod_raises=False):
        super().__init__()
        self.commands = []
        self._collmod_raises = collmod_raises

    def __getitem__(self, name):
        if name not in self._colls:
            self._colls[name] = ConflictingCollection(name, self.calls)
        return self._colls[name]

    async def command(self, spec):
        self.commands.append(spec)
        if self._collmod_raises:
            raise RuntimeError("not authorized on post_scaffolds to execute collMod")
        return {"ok": 1}


@pytest.mark.asyncio
async def test_ttl_conflict_converges_existing_index_via_collmod():
    # A pre-existing index with a different TTL must be MUTATED, not left stale —
    # create_index can never change expireAfterSeconds (BLA-1753 drift bug).
    db = ConflictingDB()
    writer = ObservabilityWriter(db, ttl_days=1825)
    await writer.ensure_trace_indexes()

    assert [c["collMod"] for c in db.commands] == [LLM_TRACES, TOOL_CALLS, AGENT_RUNS]
    for cmd in db.commands:
        assert cmd["index"]["keyPattern"] == {"received_at": 1}
        assert cmd["index"]["expireAfterSeconds"] == 1825 * 86400


@pytest.mark.asyncio
async def test_ttl_collmod_failure_never_raises_and_does_not_block_writes():
    # No collMod privilege (the per-service app users may lack it): the write
    # path must survive, and the failure is logged rather than raised.
    db = ConflictingDB(collmod_raises=True)
    writer = ObservabilityWriter(db, ttl_days=1825)
    await writer.ensure_trace_indexes()
    assert len(db.commands) == 3

    written = await writer.write_records(
        [llm_trace("run-1", model="m")], user_id="u1", client_email="u@b.com"
    )
    assert written == 1


def test_documentdb_kwargs_disables_retrywrites_with_tls():
    # DocumentDB: TLS CA present → retryWrites disabled (DocumentDB rejects it).
    kw = _documentdb_client_kwargs("mongodb://host:27017", "/etc/ca.pem")
    assert kw["tls"] is True
    assert kw["tlsCAFile"] == "/etc/ca.pem"
    assert kw["retryWrites"] is False
    # Plain mongo (no CA) → no TLS, driver default retryWrites kept.
    kw2 = _documentdb_client_kwargs("mongodb://host:27017", None)
    assert "tls" not in kw2 and "retryWrites" not in kw2
    # URI that already pins retrywrites → don't override it.
    kw3 = _documentdb_client_kwargs("mongodb://host:27017/?retryWrites=true", "/ca.pem")
    assert "retryWrites" not in kw3
