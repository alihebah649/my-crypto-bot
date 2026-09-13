"""Runtime defaults and process-wide Binance REST protection."""

import logging
import os
import threading
import time
from collections import deque
from urllib.parse import parse_qs, urlparse

# sitecustomize can be loaded by Python during the build, before application
# dependencies have been installed. Do not make the build depend on requests.
try:
    import requests
except ImportError:  # pragma: no cover - only relevant during dependency install
    requests = None

os.environ.setdefault("BINANCE_REST_URL", "https://data-api.binance.vision")

_BINANCE_BLOCK_LOCK = threading.RLock()
_BINANCE_BLOCK_UNTIL = 0.0
_BINANCE_DEFAULT_RETRY = 300.0

# Process-wide observability for every real/synthetic Binance HTTP request.
# The weight header is an IP-level cumulative counter, not a per-request cost;
# we therefore retain both the raw header and the best-effort delta between
# consecutive real Binance responses.
_BINANCE_METRICS_LOCK = threading.RLock()
_BINANCE_METRICS_STARTED_AT = time.time()
_BINANCE_METRICS_TOTAL = 0
_BINANCE_METRICS_REAL = 0
_BINANCE_METRICS_SYNTHETIC = 0
_BINANCE_METRICS_STATUS_COUNTS: dict[str, int] = {}
_BINANCE_METRICS_PATH_COUNTS: dict[str, int] = {}
_BINANCE_METRICS_PATH_WEIGHT_DELTA: dict[str, int] = {}
_BINANCE_METRICS_LAST_WEIGHT_1M: int | None = None
_BINANCE_METRICS_LAST_WEIGHT_AT: float | None = None
_BINANCE_METRICS_WEIGHT_DELTA_SUM = 0
_BINANCE_METRICS_EVENTS = deque(maxlen=200)
_BINANCE_METRICS_LAST_SUMMARY_AT = 0.0


def _is_binance_market_host(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host == "data-api.binance.vision" or host.endswith(".binance.com") or host == "binance.com"


def _request_descriptor(url: str) -> tuple[str, dict[str, str]]:
    """Return path and a small safe subset of query metadata without secrets."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    descriptor: dict[str, str] = {}
    if "symbol" in query and query["symbol"]:
        descriptor["symbol"] = query["symbol"][0]
    if "interval" in query and query["interval"]:
        descriptor["interval"] = query["interval"][0]
    if "limit" in query and query["limit"]:
        descriptor["limit"] = query["limit"][0]
    if "symbols" in query and query["symbols"]:
        raw_symbols = query["symbols"][0]
        try:
            import json
            parsed_symbols = json.loads(raw_symbols)
            if isinstance(parsed_symbols, list):
                descriptor["symbols_count"] = str(len(parsed_symbols))
        except Exception:
            descriptor["symbols_count"] = "?"
    return parsed.path or "/", descriptor


def _record_binance_request(*, method: str, url: str, response, synthetic: bool, elapsed_ms: float) -> None:
    global _BINANCE_METRICS_TOTAL, _BINANCE_METRICS_REAL, _BINANCE_METRICS_SYNTHETIC
    global _BINANCE_METRICS_LAST_WEIGHT_1M, _BINANCE_METRICS_LAST_WEIGHT_AT
    global _BINANCE_METRICS_WEIGHT_DELTA_SUM, _BINANCE_METRICS_LAST_SUMMARY_AT

    path, descriptor = _request_descriptor(url)
    status = int(getattr(response, "status_code", 0) or 0)
    weight_raw = response.headers.get("X-MBX-USED-WEIGHT-1M")
    try:
        weight_1m = int(weight_raw) if weight_raw is not None else None
    except (TypeError, ValueError):
        weight_1m = None

    with _BINANCE_METRICS_LOCK:
        _BINANCE_METRICS_TOTAL += 1
        if synthetic:
            _BINANCE_METRICS_SYNTHETIC += 1
        else:
            _BINANCE_METRICS_REAL += 1
        status_key = str(status)
        _BINANCE_METRICS_STATUS_COUNTS[status_key] = _BINANCE_METRICS_STATUS_COUNTS.get(status_key, 0) + 1
        _BINANCE_METRICS_PATH_COUNTS[path] = _BINANCE_METRICS_PATH_COUNTS.get(path, 0) + 1

        delta = None
        if not synthetic and weight_1m is not None:
            previous = _BINANCE_METRICS_LAST_WEIGHT_1M
            if previous is None or weight_1m >= previous:
                delta = weight_1m if previous is None else weight_1m - previous
            else:
                # The one-minute counter rolled/reset, so treat the new raw
                # value as the observed delta for this response.
                delta = weight_1m
            delta = max(0, int(delta))
            _BINANCE_METRICS_WEIGHT_DELTA_SUM += delta
            _BINANCE_METRICS_PATH_WEIGHT_DELTA[path] = _BINANCE_METRICS_PATH_WEIGHT_DELTA.get(path, 0) + delta
            _BINANCE_METRICS_LAST_WEIGHT_1M = weight_1m
            _BINANCE_METRICS_LAST_WEIGHT_AT = time.time()

        event = {
            "at": time.time(),
            "method": str(method).upper(),
            "path": path,
            "params": descriptor,
            "status": status,
            "synthetic": bool(synthetic),
            "elapsed_ms": round(float(elapsed_ms), 1),
            "weight_1m": weight_1m,
            "weight_delta_from_previous_response": delta,
        }
        _BINANCE_METRICS_EVENTS.append(event)

        now = time.time()
        if now - _BINANCE_METRICS_LAST_SUMMARY_AT >= 60.0:
            _BINANCE_METRICS_LAST_SUMMARY_AT = now
            summary = {
                "uptime_s": round(now - _BINANCE_METRICS_STARTED_AT, 1),
                "total": _BINANCE_METRICS_TOTAL,
                "real": _BINANCE_METRICS_REAL,
                "synthetic": _BINANCE_METRICS_SYNTHETIC,
                "status": dict(_BINANCE_METRICS_STATUS_COUNTS),
                "paths": dict(_BINANCE_METRICS_PATH_COUNTS),
                "observed_weight_delta_sum": _BINANCE_METRICS_WEIGHT_DELTA_SUM,
                "last_weight_1m": _BINANCE_METRICS_LAST_WEIGHT_1M,
                "last_weight_at": _BINANCE_METRICS_LAST_WEIGHT_AT,
            }
        else:
            summary = None

    # Render receives stdout; keep the log line compact and avoid dumping full
    # query strings or headers. Endpoint-level counts remain enough to identify
    # whether ticker, klines, or another Binance path is driving traffic.
    print(
        "[BINANCE-METRICS] request "
        f"method={str(method).upper()} path={path} status={status} "
        f"synthetic={int(synthetic)} elapsed_ms={float(elapsed_ms):.1f} "
        f"weight_1m={weight_1m if weight_1m is not None else 'NA'} "
        f"weight_delta={delta if delta is not None else 'NA'} params={descriptor}",
        flush=True,
    )
    if summary is not None:
        print(f"[BINANCE-METRICS] summary {summary}", flush=True)


def binance_metrics_snapshot() -> dict:
    """Return a JSON-safe in-process snapshot for diagnostics."""
    with _BINANCE_METRICS_LOCK:
        return {
            "started_at": _BINANCE_METRICS_STARTED_AT,
            "uptime_seconds": round(max(0.0, time.time() - _BINANCE_METRICS_STARTED_AT), 1),
            "total_requests_seen": _BINANCE_METRICS_TOTAL,
            "real_outbound_requests": _BINANCE_METRICS_REAL,
            "synthetic_circuit_responses": _BINANCE_METRICS_SYNTHETIC,
            "status_counts": dict(_BINANCE_METRICS_STATUS_COUNTS),
            "path_counts": dict(_BINANCE_METRICS_PATH_COUNTS),
            "path_observed_weight_delta": dict(_BINANCE_METRICS_PATH_WEIGHT_DELTA),
            "observed_weight_delta_sum": _BINANCE_METRICS_WEIGHT_DELTA_SUM,
            "last_weight_1m": _BINANCE_METRICS_LAST_WEIGHT_1M,
            "last_weight_timestamp": _BINANCE_METRICS_LAST_WEIGHT_AT,
            "recent_events": list(_BINANCE_METRICS_EVENTS),
        }


if requests is not None:
    def _retry_after(response) -> float:
        value = response.headers.get("Retry-After") if response is not None else None
        try:
            return max(1.0, float(value))
        except (TypeError, ValueError):
            return _BINANCE_DEFAULT_RETRY

    def _synthetic_block_response(url: str, remaining: float) -> requests.Response:
        response = requests.Response()
        response.status_code = 200
        response.headers["Retry-After"] = str(max(1, int(remaining)))
        response.headers["X-Shadow-Binance-Circuit"] = "open"
        response.url = str(url)
        # Both protected market-data consumers already interpret an empty JSON
        # list as no available market data. Returning a successful empty payload
        # keeps the circuit state local to this layer and prevents upper guards
        # from mistaking our own synthetic block for a new Binance 418/429.
        response._content = b"[]"
        response.encoding = "utf-8"
        return response

    _original_session_request = requests.sessions.Session.request

    def _protected_session_request(self, method, url, **kwargs):
        global _BINANCE_BLOCK_UNTIL
        url_string = str(url)
        is_binance = _is_binance_market_host(url_string)
        started = time.monotonic()
        synthetic = False
        if is_binance:
            with _BINANCE_BLOCK_LOCK:
                remaining = _BINANCE_BLOCK_UNTIL - time.time()
            if remaining > 0:
                synthetic = True
                response = _synthetic_block_response(url_string, remaining)
                _record_binance_request(
                    method=method,
                    url=url_string,
                    response=response,
                    synthetic=True,
                    elapsed_ms=(time.monotonic() - started) * 1000.0,
                )
                return response

        response = _original_session_request(self, method, url, **kwargs)

        if is_binance:
            _record_binance_request(
                method=method,
                url=str(getattr(response, "url", url_string) or url_string),
                response=response,
                synthetic=False,
                elapsed_ms=(time.monotonic() - started) * 1000.0,
            )
            if response.status_code in {418, 429}:
                retry_after = _retry_after(response)
                with _BINANCE_BLOCK_LOCK:
                    _BINANCE_BLOCK_UNTIL = max(_BINANCE_BLOCK_UNTIL, time.time() + retry_after)
        return response

    requests.sessions.Session.request = _protected_session_request


# Keep a conventional logger import available to code that introspects
# sitecustomize during diagnostics; request metrics are emitted with print so
# they remain visible even before application logging is configured.
logging.getLogger("BinanceRequestMetrics")