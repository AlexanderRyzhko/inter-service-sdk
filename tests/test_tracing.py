"""
Tests for inter_service_sdk.tracing module (BLA-1504).
"""
import asyncio
import inspect
import logging
import uuid

import httpx
import pytest
import requests_mock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from inter_service_sdk import InterServiceClient
from inter_service_sdk.tracing import (
    TRACE_HEADER,
    REQUEST_ID_HEADER,
    trace_id_var,
    get_trace_id,
    set_trace_id,
    BlazelTracingMiddleware,
    BlazelTraceFilter,
)


@pytest.fixture(autouse=True)
def _reset_trace_id():
    """Ensure trace_id_var never leaks between tests in this module."""
    token = trace_id_var.set(None)
    yield
    trace_id_var.reset(token)


def _make_app():
    app = FastAPI()
    app.add_middleware(BlazelTracingMiddleware)

    @app.get("/echo")
    async def echo():
        return {"trace_id": get_trace_id()}

    return app


class TestTraceIdPrimitives:

    def test_get_trace_id_default_none(self):
        """AC-1: no trace id set -> get_trace_id() returns None, no raise."""
        assert get_trace_id() is None

    def test_set_then_get_trace_id(self):
        """AC-2: set_trace_id('abc') -> get_trace_id() == 'abc' in same context."""
        set_trace_id("abc")
        assert get_trace_id() == "abc"

    def test_trace_header_constant_value(self):
        """AC-3: TRACE_HEADER == 'X-Blazel-Trace-Id' exactly."""
        assert TRACE_HEADER == "X-Blazel-Trace-Id"


class TestBlazelTracingMiddleware:

    def test_middleware_uses_incoming_trace_header(self):
        """AC-4: X-Blazel-Trace-Id: t1 inbound -> trace id t1, echoed on response."""
        client = TestClient(_make_app())
        resp = client.get("/echo", headers={TRACE_HEADER: "t1"})
        assert resp.json()["trace_id"] == "t1"
        assert resp.headers[TRACE_HEADER] == "t1"

    def test_middleware_falls_back_to_request_id(self):
        """AC-5: no X-Blazel-Trace-Id but X-Request-ID: r1 -> trace id r1, both headers echoed."""
        client = TestClient(_make_app())
        resp = client.get("/echo", headers={REQUEST_ID_HEADER: "r1"})
        assert resp.json()["trace_id"] == "r1"
        assert resp.headers[TRACE_HEADER] == "r1"
        assert resp.headers[REQUEST_ID_HEADER] == "r1"

    def test_middleware_mints_uuid4_when_absent(self):
        """AC-6: neither header present -> uuid4 minted, echoed as X-Blazel-Trace-Id."""
        client = TestClient(_make_app())
        resp = client.get("/echo")
        trace_id = resp.json()["trace_id"]
        assert trace_id is not None
        uuid.UUID(trace_id)  # raises ValueError if not a valid uuid4-shaped string
        assert resp.headers[TRACE_HEADER] == trace_id

    def test_middleware_mismatched_dual_inbound_headers_no_conflicting_response_ids(self):
        """Regression (PR #6 review round 3 finding): if the caller sends BOTH
        X-Blazel-Trace-Id and X-Request-ID with DIFFERENT values, X-Blazel-Trace-Id
        wins precedence (AC-4) — the now-stale, non-matching X-Request-ID must not
        be echoed back, or the response would carry two conflicting correlation ids."""
        client = TestClient(_make_app())
        resp = client.get("/echo", headers={TRACE_HEADER: "trace-1", REQUEST_ID_HEADER: "rid-2"})
        assert resp.json()["trace_id"] == "trace-1"
        assert resp.headers[TRACE_HEADER] == "trace-1"
        assert REQUEST_ID_HEADER not in resp.headers

    def test_middleware_matching_dual_inbound_headers_echoes_request_id(self):
        """Same-value case: both headers present with the SAME value -> both echoed
        (no mismatch to guard against)."""
        client = TestClient(_make_app())
        resp = client.get("/echo", headers={TRACE_HEADER: "same-id", REQUEST_ID_HEADER: "same-id"})
        assert resp.headers[TRACE_HEADER] == "same-id"
        assert resp.headers[REQUEST_ID_HEADER] == "same-id"

    def test_middleware_no_duplicate_response_headers_when_downstream_presets_them(self):
        """Regression (PR #6 review finding): if the wrapped app already set
        X-Blazel-Trace-Id / X-Request-ID on the response, the middleware must
        replace them, not append a duplicate (which HTTP clients would see as
        a comma-joined value)."""
        from starlette.responses import Response

        app = FastAPI()
        app.add_middleware(BlazelTracingMiddleware)

        @app.get("/preset")
        async def preset():
            return Response(
                content="{}",
                media_type="application/json",
                headers={TRACE_HEADER: "downstream-value", REQUEST_ID_HEADER: "downstream-rid"},
            )

        client = TestClient(app)
        resp = client.get("/preset", headers={REQUEST_ID_HEADER: "r1"})
        assert resp.headers[TRACE_HEADER] == "r1"
        assert resp.headers[REQUEST_ID_HEADER] == "r1"
        # raw_headers exposes duplicates that .headers (a dict-like) would hide
        raw_trace = [v for k, v in resp.headers.raw if k.decode().lower() == TRACE_HEADER.lower()]
        raw_rid = [v for k, v in resp.headers.raw if k.decode().lower() == REQUEST_ID_HEADER.lower()]
        assert raw_trace == [b"r1"]
        assert raw_rid == [b"r1"]

    def test_middleware_strips_downstream_request_id_even_when_not_echoing_one(self):
        """Regression (PR #6 review round 2 finding): if inbound had ONLY
        X-Blazel-Trace-Id (no X-Request-ID) but the downstream app set its own
        X-Request-ID, the response must not carry two conflicting correlation
        ids — the downstream X-Request-ID must be stripped."""
        from starlette.responses import Response

        app = FastAPI()
        app.add_middleware(BlazelTracingMiddleware)

        @app.get("/preset")
        async def preset():
            return Response(
                content="{}",
                media_type="application/json",
                headers={REQUEST_ID_HEADER: "downstream-rid"},
            )

        client = TestClient(app)
        resp = client.get("/preset", headers={TRACE_HEADER: "trace-123"})
        assert resp.headers[TRACE_HEADER] == "trace-123"
        assert REQUEST_ID_HEADER not in resp.headers

    def test_middleware_add_middleware_pattern_misses_unhandled_500(self):
        """Documents a known limitation (PR #6 review round 2 finding): Starlette's
        ServerErrorMiddleware is always outermost regardless of app.add_middleware()
        order, so a truly unhandled exception never reaches send_wrapper — the 500
        response has no trace header with this integration pattern."""
        app = FastAPI()
        app.add_middleware(BlazelTracingMiddleware)

        @app.get("/boom")
        async def boom():
            raise ValueError("kaboom")

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/boom", headers={TRACE_HEADER: "t1"})
        assert resp.status_code == 500
        assert TRACE_HEADER not in resp.headers  # documents the gap, not the desired end state

    def test_middleware_outer_wrap_pattern_covers_unhandled_500(self):
        """Counterpart to the above: wrapping the whole app from OUTSIDE (not via
        app.add_middleware) puts BlazelTracingMiddleware outside Starlette's own
        ServerErrorMiddleware, so the trace header IS present even on an unhandled
        exception's 500 response. This is the recommended pattern for full coverage."""
        app = FastAPI()

        @app.get("/boom")
        async def boom():
            raise ValueError("kaboom")

        wrapped = BlazelTracingMiddleware(app)
        client = TestClient(wrapped, raise_server_exceptions=False)
        resp = client.get("/boom", headers={TRACE_HEADER: "t1"})
        assert resp.status_code == 500
        assert resp.headers[TRACE_HEADER] == "t1"

    def test_middleware_is_pure_asgi_call(self):
        """AC-7: middleware implements async def __call__(scope, receive, send) directly,
        does NOT subclass starlette.middleware.base.BaseHTTPMiddleware."""
        assert not issubclass(BlazelTracingMiddleware, BaseHTTPMiddleware)
        assert inspect.iscoroutinefunction(BlazelTracingMiddleware.__call__)
        params = list(inspect.signature(BlazelTracingMiddleware.__call__).parameters)
        assert params == ["self", "scope", "receive", "send"]

    async def test_middleware_no_cross_request_bleed(self):
        """AC-8: two genuinely concurrent in-flight requests, different trace ids ->
        no cross-request contextvar bleed. Uses httpx.AsyncClient + ASGITransport with
        an event handshake to force real overlap (TestClient is serialized and would
        pass this vacuously — see design review should-fix 2)."""
        app = FastAPI()
        app.add_middleware(BlazelTracingMiddleware)

        first_arrived = asyncio.Event()
        release_first = asyncio.Event()

        @app.get("/slow")
        async def slow(which: str):
            if which == "first":
                first_arrived.set()
                await release_first.wait()
            else:
                await first_arrived.wait()
                release_first.set()
            return {"trace_id": get_trace_id()}

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            t1 = asyncio.create_task(
                ac.get("/slow", params={"which": "first"}, headers={TRACE_HEADER: "trace-1"})
            )
            t2 = asyncio.create_task(
                ac.get("/slow", params={"which": "second"}, headers={TRACE_HEADER: "trace-2"})
            )
            r1, r2 = await asyncio.wait_for(asyncio.gather(t1, t2), timeout=5)

        assert r1.json()["trace_id"] == "trace-1"
        assert r2.json()["trace_id"] == "trace-2"

    def test_exclude_paths_preserves_app_request_id_and_skips_trace_header(self):
        """BLA-1497: on an excluded path, the middleware must NOT strip the app's
        own X-Request-Id response header and must NOT add X-Blazel-Trace-Id — the
        endpoint keeps its own correlation-header contract intact."""
        from starlette.responses import Response

        app = FastAPI()
        app.add_middleware(BlazelTracingMiddleware, exclude_paths=["/learn"])

        @app.get("/api/v1/clients/x/learn")
        async def learn():
            # Endpoint mints and echoes its own X-Request-Id (its pre-existing contract).
            return Response(
                content="{}",
                media_type="application/json",
                headers={REQUEST_ID_HEADER: "app-minted-rid"},
            )

        client = TestClient(app)
        resp = client.get("/api/v1/clients/x/learn")
        # App's own X-Request-Id survives (not stripped).
        assert resp.headers[REQUEST_ID_HEADER] == "app-minted-rid"
        # Middleware did not add its own trace header on the excluded path.
        assert TRACE_HEADER not in resp.headers

    def test_exclude_paths_still_sets_trace_id_var_for_logging(self):
        """BLA-1497: excluded paths still get trace_id_var set (so their log
        records carry blazel_trace_id) — only the response-header rewrite is
        skipped, not the context propagation."""
        app = FastAPI()
        app.add_middleware(BlazelTracingMiddleware, exclude_paths=["/learn"])

        @app.get("/api/v1/clients/x/learn")
        async def learn():
            return {"trace_id": get_trace_id()}

        client = TestClient(app)
        resp = client.get("/api/v1/clients/x/learn", headers={TRACE_HEADER: "t-excl-1"})
        assert resp.json()["trace_id"] == "t-excl-1"

    def test_exclude_paths_does_not_affect_non_excluded_routes(self):
        """BLA-1497: a route not in exclude_paths keeps full rewrite behavior."""
        app = FastAPI()
        app.add_middleware(BlazelTracingMiddleware, exclude_paths=["/learn"])

        @app.get("/echo")
        async def echo():
            return {"trace_id": get_trace_id()}

        client = TestClient(app)
        resp = client.get("/echo", headers={TRACE_HEADER: "t-echo-1"})
        assert resp.json()["trace_id"] == "t-echo-1"
        assert resp.headers[TRACE_HEADER] == "t-echo-1"

    def test_exclude_paths_default_empty_is_backward_compatible(self):
        """BLA-1497: omitting exclude_paths keeps 1.3.0 behavior exactly — every
        path gets the trace header rewrite."""
        app = FastAPI()
        app.add_middleware(BlazelTracingMiddleware)

        @app.get("/anything")
        async def anything():
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/anything", headers={TRACE_HEADER: "t-bc-1"})
        assert resp.headers[TRACE_HEADER] == "t-bc-1"


class TestBlazelTraceFilter:

    def test_trace_filter_injects_field_when_set(self):
        """AC-9: trace id set in context -> record.blazel_trace_id equals it."""
        set_trace_id("abc123")
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", None, None)
        f = BlazelTraceFilter()
        assert f.filter(record) is True
        assert record.blazel_trace_id == "abc123"

    def test_trace_filter_safe_default_when_unset(self):
        """AC-10: no trace id set -> record.blazel_trace_id present with safe default,
        formatter referencing %(blazel_trace_id)s never raises KeyError."""
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", None, None)
        f = BlazelTraceFilter()
        f.filter(record)
        assert record.blazel_trace_id == BlazelTraceFilter.default_value
        formatter = logging.Formatter("%(blazel_trace_id)s %(message)s")
        formatter.format(record)  # must not raise KeyError


class TestClientInjectionFromSyncRouteHandler:

    def test_client_injection_from_sync_route_handler(self):
        """AC-14 (Delivery Unknown): sync (def, not async def) FastAPI route handler
        calls client.request() after middleware set the context var -> trace id still
        propagates into outbound header. Starlette runs sync routes via
        anyio.to_thread.run_sync, which copies context — this proves it holds here."""
        app = FastAPI()
        app.add_middleware(BlazelTracingMiddleware)

        captured = {}

        @app.get("/proxy")
        def proxy():  # sync def, intentionally not async
            client = InterServiceClient(base_url="http://downstream.example.com", api_key="k")
            with requests_mock.Mocker() as m:
                m.get(requests_mock.ANY, json={"data": {}})
                client.request(endpoint="ping")
                captured["headers"] = m.request_history[0].headers
            return {"ok": True}

        test_client = TestClient(app)
        resp = test_client.get("/proxy", headers={TRACE_HEADER: "sync-trace"})
        assert resp.status_code == 200
        assert captured["headers"].get(TRACE_HEADER) == "sync-trace"


class TestVersionAndExports:

    def test_version_is_1_3_0(self):
        """AC-15: inter_service_sdk.__version__ == '1.3.0'."""
        import inter_service_sdk
        assert inter_service_sdk.__version__ == "1.3.0"

    def test_tracing_symbols_exported_from_top_level(self):
        """AC-15: TRACE_HEADER, get_trace_id, set_trace_id, BlazelTracingMiddleware,
        BlazelTraceFilter all importable from inter_service_sdk top-level."""
        import inter_service_sdk
        assert inter_service_sdk.TRACE_HEADER == "X-Blazel-Trace-Id"
        assert inter_service_sdk.get_trace_id is get_trace_id
        assert inter_service_sdk.set_trace_id is set_trace_id
        assert inter_service_sdk.BlazelTracingMiddleware is BlazelTracingMiddleware
        assert inter_service_sdk.BlazelTraceFilter is BlazelTraceFilter
