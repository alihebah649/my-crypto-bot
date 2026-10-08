"""Paper Trading entrypoint with dual Scalping + Swing strategy lanes.

This adapter keeps Strategy, Trade Manager, Paper Execution, persistence,
Smart Hold and Recovery owned by their existing modules. The only additions
here are the screened Spot universe, market-data guard/cache, diagnostics and
runtime orchestration.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import os
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import requests
from flask import jsonify

import shadow_main_legacy as _legacy
from shadow_main_legacy import *
from dual_mode_strategy import score_symbol, SCALP_SCORE_THRESHOLD, SWING_SCORE_THRESHOLD, BUY_SCORE_THRESHOLD
from core.brain_shadow_runtime import BrainShadowRuntime
from core.brain_shadow_capture_store import BrainShadowCaptureStore
from core.postgres_evidence_store import PostgresEvidenceStore, database_url_from_env
from core.brain_market_regime import derive_market_breadth
from core.brain_shadow_binding import attach_brain_shadow_entry
from core.mtf_context_cache import MTFContextCache
from core.market_data_manager import MarketDataManager, PersistentMarketDataCache
from core.binance_market_stream import BinanceMarketStream
from core.binance_snapshot_consumer import BinanceSnapshotError, hydrate_market_data_manager
from core.bybit_market_data import BybitMarketDataClient, BybitMarketDataError
from core.bybit_market_stream import BybitMarketStream
from trade_manager.core_risk_providers import KlineCorrelationProvider

# Additional assets are deliberately limited to established Spot assets that
# currently pass the external Shariah screen used for this project. This is a
# universe expansion only; it does not alter score thresholds or entry rules.
# Re-screen before live trading because crypto Shariah opinions and project
# mechanics can change. TON is intentionally excluded because Binance replaced
# the TON ticker with GRAM in July 2026.
_ADDITIONAL_HALAL_SPOT_SYMBOLS = [
    "XRPUSDT", "XLMUSDT", "HBARUSDT", "SUIUSDT", "BCHUSDT", "TRXUSDT",
]
for _symbol in _ADDITIONAL_HALAL_SPOT_SYMBOLS:
    if _symbol not in _legacy.TRADING_SYMBOLS:
        _legacy.TRADING_SYMBOLS.append(_symbol)

_mtf_candles: dict[str, dict[str, list[dict]]] = {}
_mtf_cache = MTFContextCache(ttl_by_timeframe={"1h": 3300.0, "4h": 14100.0})
_original_fetch_strategy_data = _legacy.fetch_strategy_data

# -----------------------------------------------------------------------------
# Binance REST rate-limit / shared-IP guard + candle polling cache
# -----------------------------------------------------------------------------
_binance_block_until = 0.0
_binance_backoff_seconds = 300.0

# Paper market-data sharding: keep each symbol's ticker and klines on one
# venue so a candle series is internally consistent. This affects public data
# acquisition only; fees, risk, execution, and order venues remain unchanged.
_BYBIT_MARKET_DATA_ENABLED = os.getenv("BYBIT_MARKET_DATA_ENABLED", "1").strip().lower() not in {"0", "false", "off", "no"}
PAPER_VENUE_MODE = os.getenv("PAPER_VENUE_MODE", "MIXED").strip().upper()
if PAPER_VENUE_MODE not in {"MIXED", "BINANCE_ONLY_LAB", "BYBIT_ONLY_LAB"}:
    raise ValueError(f"Unsupported PAPER_VENUE_MODE: {PAPER_VENUE_MODE}")
PAPER_VENUE_LAB = PAPER_VENUE_MODE != "MIXED"
_BYBIT_MARKET_DATA_REST = os.getenv("BYBIT_MARKET_DATA_REST_URL", "https://api.bybit.com").strip()
_BYBIT_BACKOFF_SECONDS = 300.0
_BYBIT_BLOCK_UNTIL = 0.0
_BYBIT_GUARD = {
    "state": "DISABLED" if not _BYBIT_MARKET_DATA_ENABLED else "READY",
    "status_code": None,
    "blocked_until": 0.0,
    "retry_after_seconds": 0.0,
    "last_error": None,
    "last_path": None,
}
_BYBIT_TICKER_CACHE_TTL = 30.0
_BYBIT_TICKER_CACHE: tuple[float, dict[str, dict]] | None = None
_bybit_client = BybitMarketDataClient(base_url=_BYBIT_MARKET_DATA_REST)

_market_data_split = len(TRADING_SYMBOLS) // 2
if PAPER_VENUE_MODE == "BINANCE_ONLY_LAB":
    _BINANCE_MARKET_DATA_SYMBOLS = tuple(TRADING_SYMBOLS)
    _BYBIT_MARKET_DATA_SYMBOLS = ()
elif PAPER_VENUE_MODE == "BYBIT_ONLY_LAB":
    _BINANCE_MARKET_DATA_SYMBOLS = ()
    _BYBIT_MARKET_DATA_SYMBOLS = tuple(TRADING_SYMBOLS)
else:
    _BINANCE_MARKET_DATA_SYMBOLS = tuple(TRADING_SYMBOLS[:_market_data_split])
    _BYBIT_MARKET_DATA_SYMBOLS = tuple(TRADING_SYMBOLS[_market_data_split:])
_BINANCE_MARKET_DATA_SYMBOL_SET = set(_BINANCE_MARKET_DATA_SYMBOLS)
_BYBIT_MARKET_DATA_SYMBOL_SET = set(_BYBIT_MARKET_DATA_SYMBOLS)
_binance_guard = {
    "state": "READY",
    "status_code": None,
    "blocked_until": 0.0,
    "retry_after_seconds": 0.0,
    "last_error": None,
    "last_path": None,
}
_original_fetch_24h_tickers = _legacy.fetch_24h_tickers
_original_fetch_klines = _legacy.fetch_klines
_KLINE_CACHE_TTL = {"5m": 310.0, "15m": 910.0, "1h": 3610.0, "4h": 14410.0}
_kline_cache: dict[tuple[str, str, int], tuple[float, list[dict]]] = {}
_kline_cache_lock = threading.RLock()
_LAB_TICKER_FALLBACK_CACHE: tuple[float, dict[str, dict]] | None = None
_LAB_TICKER_FALLBACK_TTL = 300.0
_BINANCE_LAB_WARMUP_LOGGED: set[tuple[str, str]] = set()

# Activate the staggered Kline scheduler in the live Paper runtime. The
# scheduler is intentionally independent of strategy/risk decisions; it only
# limits which symbols may make a network refresh during each 30s cycle.
_market_data_manager = MarketDataManager(
    PersistentMarketDataCache(Path(PAPER_STATE_DIR) / "market_data_manager_cache.json"),
    ticker_symbols=TRADING_SYMBOLS,
    ticker_batch_size=11,
    ticker_group_interval_seconds=30.0,
    kline_wave_count=3,
    kline_wave_interval_seconds=30.0,
)
_legacy.market_data_manager = _market_data_manager
_legacy._market_data_manager_installed = True

# Optional Binance Lab warm-start from the GitHub-published market snapshot.
# Main/MIXED remains unchanged unless the URL is explicitly configured.
_BINANCE_MARKET_DATA_SNAPSHOT_URL = os.getenv(
    "BINANCE_MARKET_DATA_SNAPSHOT_URL", ""
).strip()
try:
    _BINANCE_MARKET_DATA_SNAPSHOT_MAX_AGE = float(
        os.getenv("BINANCE_MARKET_DATA_SNAPSHOT_MAX_AGE", "900")
    )
except (TypeError, ValueError):
    _BINANCE_MARKET_DATA_SNAPSHOT_MAX_AGE = 900.0
try:
    _BINANCE_MARKET_DATA_SNAPSHOT_BOOTSTRAP_MAX_AGE = float(
        os.getenv("BINANCE_MARKET_DATA_SNAPSHOT_BOOTSTRAP_MAX_AGE", "21600")
    )
except (TypeError, ValueError):
    _BINANCE_MARKET_DATA_SNAPSHOT_BOOTSTRAP_MAX_AGE = 21600.0

if PAPER_VENUE_MODE == "BINANCE_ONLY_LAB" and _BINANCE_MARKET_DATA_SNAPSHOT_URL:
    try:
        _snapshot_result = hydrate_market_data_manager(
            _market_data_manager,
            _BINANCE_MARKET_DATA_SNAPSHOT_URL,
            TRADING_SYMBOLS,
            max_stale_seconds=max(60.0, _BINANCE_MARKET_DATA_SNAPSHOT_MAX_AGE),
            bootstrap_max_stale_seconds=max(
                max(60.0, _BINANCE_MARKET_DATA_SNAPSHOT_MAX_AGE),
                _BINANCE_MARKET_DATA_SNAPSHOT_BOOTSTRAP_MAX_AGE,
            ),
        )
        _legacy.logger.info(
            "[BINANCE-SNAPSHOT] loaded=%s bootstrap_stale=%s entry_fresh=%s symbols=%s entries=%s age=%.1fs",
            bool(_snapshot_result.get("loaded")),
            bool(_snapshot_result.get("bootstrap_stale")),
            bool(_snapshot_result.get("entry_fresh")),
            _snapshot_result.get("symbols", 0),
            _snapshot_result.get("cache_entries_written", 0),
            float(_snapshot_result.get("age_seconds", 0.0)),
        )
    except BinanceSnapshotError as exc:
        _legacy.logger.warning(
            "[BINANCE-SNAPSHOT] rejected: %s; continuing with existing WS-only fallback",
            exc,
        )
    except Exception as exc:
        _legacy.logger.warning(
            "[BINANCE-SNAPSHOT] load failed: %s; continuing with existing WS-only fallback",
            exc,
        )


def _correlation_candle_loader(symbol: str):
    """Read bounded-analysis 5m candles from the canonical MarketDataManager cache."""
    key = f"5m:{str(symbol).upper()}:60"
    snapshot = _market_data_manager.get_for_analysis("5m", key)
    return snapshot.payload if snapshot is not None else []
_legacy.logger.info(
    "[MARKET-DATA-CONFIG] owner=shadow_main_base venue_mode=%s ticker_groups=%d ticker_batch_size=%d ticker_interval=%.1fs kline_waves=%d kline_interval=%.1fs",
    PAPER_VENUE_MODE,
    len(_market_data_manager.ticker_groups()),
    _market_data_manager.ticker_batch_size,
    _market_data_manager.ticker_group_interval_seconds,
    _market_data_manager.kline_wave_count,
    _market_data_manager.kline_wave_interval_seconds,
)


def _retry_after_seconds(exc: Exception, default: float) -> float:
    response = getattr(exc, "response", None)
    header = response.headers.get("Retry-After") if response is not None else None
    if header:
        try:
            return max(1.0, float(header))
        except (TypeError, ValueError):
            pass
    return default


def _set_binance_block(exc: Exception, path: str) -> None:
    global _binance_block_until, _binance_backoff_seconds
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    retry_after = _retry_after_seconds(exc, _binance_backoff_seconds)
    _binance_block_until = time.time() + retry_after
    _binance_guard.update({
        "state": "BLOCKED", "status_code": status,
        "blocked_until": _binance_block_until,
        "retry_after_seconds": retry_after,
        "last_error": f"{type(exc).__name__}: {exc}", "last_path": path,
    })
    if status == 418:
        _binance_backoff_seconds = min(max(_binance_backoff_seconds * 2.0, retry_after), 3600.0)
    else:
        _binance_backoff_seconds = min(max(60.0, retry_after), 900.0)
    _legacy.logger.warning(
        "Binance market-data guard activated: HTTP %s path=%s retry_in=%.1fs",
        status, path, retry_after,
    )


def _binance_guard_active() -> bool:
    if time.time() < _binance_block_until:
        return True
    if _binance_guard.get("state") == "BLOCKED":
        _binance_guard["state"] = "READY"
        _binance_guard["blocked_until"] = 0.0
    return False


def _bybit_guard_active() -> bool:
    return (not _BYBIT_MARKET_DATA_ENABLED) or time.time() < _BYBIT_BLOCK_UNTIL


def _set_bybit_block(exc: Exception, path: str) -> None:
    global _BYBIT_BLOCK_UNTIL, _BYBIT_BACKOFF_SECONDS
    message = str(exc)
    is_rate_limit = "HTTP 403" in message or "HTTP 429" in message
    retry_after = 600.0 if is_rate_limit else max(60.0, _BYBIT_BACKOFF_SECONDS)
    _BYBIT_BLOCK_UNTIL = time.time() + retry_after
    _BYBIT_GUARD.update({
        "state": "BLOCKED",
        "status_code": 403 if "HTTP 403" in message else (429 if "HTTP 429" in message else None),
        "blocked_until": _BYBIT_BLOCK_UNTIL,
        "retry_after_seconds": retry_after,
        "last_error": f"{type(exc).__name__}: {exc}",
        "last_path": path,
    })
    _BYBIT_BACKOFF_SECONDS = min(max(_BYBIT_BACKOFF_SECONDS * 2.0, retry_after), 1800.0)
    _legacy.logger.warning(
        "Bybit market-data guard activated: path=%s retry_in=%.1fs",
        path,
        retry_after,
    )


def _lab_stream_for_mode():
    if PAPER_VENUE_MODE == "BINANCE_ONLY_LAB":
        return _binance_market_stream
    if PAPER_VENUE_MODE == "BYBIT_ONLY_LAB":
        return _bybit_market_stream
    return None


def _lab_ticker_fallback(symbols: list[str]) -> dict[str, dict]:
    global _LAB_TICKER_FALLBACK_CACHE
    now = time.time()
    cached = _LAB_TICKER_FALLBACK_CACHE
    if cached is not None and now - cached[0] < _LAB_TICKER_FALLBACK_TTL:
        return {s: dict(cached[1][s]) for s in symbols if s in cached[1]}

    fallback: dict[str, dict] = {}
    if PAPER_VENUE_MODE == "BINANCE_ONLY_LAB":
        # Binance Lab is intentionally REST-free. It waits for its own
        # WebSocket ticker stream instead of touching the shared Render egress.
        return {}
    elif PAPER_VENUE_MODE == "BYBIT_ONLY_LAB":
        if not _BYBIT_MARKET_DATA_ENABLED or _bybit_guard_active():
            return {}
        try:
            raw = _bybit_client.fetch_tickers(symbols)
            for symbol, ticker in raw.items():
                row = dict(ticker)
                row["market_data_source"] = "BYBIT"
                row["market_data_transport"] = "REST_COLD_START"
                fallback[symbol] = row
            _BYBIT_GUARD.update({
                "state": "READY",
                "status_code": None,
                "last_error": None,
                "last_path": None,
            })
        except BybitMarketDataError as exc:
            _set_bybit_block(exc, "/v5/market/tickers")
            return {}

    if fallback:
        _LAB_TICKER_FALLBACK_CACHE = (now, dict(fallback))
    return fallback


def _guarded_fetch_24h_tickers(symbols=None):
    global _binance_backoff_seconds, _BYBIT_TICKER_CACHE
    requested = [
        str(symbol).upper()
        for symbol in (symbols if symbols is not None else TRADING_SYMBOLS)
    ]
    result: dict[str, dict] = {}

    binance_symbols = [
        symbol for symbol in requested if symbol in _BINANCE_MARKET_DATA_SYMBOL_SET
    ]
    bybit_symbols = [
        symbol for symbol in requested if symbol in _BYBIT_MARKET_DATA_SYMBOL_SET
    ]

    # Isolated venue labs consume ticker snapshots from their own WebSocket.
    # REST is a bounded cold-start fallback, never a polling path.
    if PAPER_VENUE_MODE in {"BINANCE_ONLY_LAB", "BYBIT_ONLY_LAB"}:
        stream = _lab_stream_for_mode()
        missing: list[str] = []
        if stream is not None:
            for symbol in requested:
                try:
                    ticker = stream.get_latest_ticker(symbol)
                    received_at = float((ticker or {}).get("received_at", 0.0) or 0.0)
                    stale_after = float(
                        getattr(stream, "stale_after_seconds", 30.0)
                    )
                except Exception:
                    ticker = None
                    received_at = 0.0
                    stale_after = 30.0
                if (
                    isinstance(ticker, dict)
                    and received_at > 0.0
                    and time.time() - received_at <= stale_after
                ):
                    result[symbol] = dict(ticker)
                else:
                    missing.append(symbol)
        else:
            missing = list(requested)

        if missing:
            fallback = _lab_ticker_fallback(missing)
            result.update(fallback)

        return {symbol: result[symbol] for symbol in requested if symbol in result}

    # Existing mixed-lane Paper behavior remains unchanged below.
    if binance_symbols and not _binance_guard_active():
        try:
            data = _original_fetch_24h_tickers(binance_symbols)
            for symbol, ticker in data.items():
                row = dict(ticker)
                row["market_data_source"] = "BINANCE"
                result[symbol] = row
            _binance_guard.update({
                "state": "READY",
                "status_code": None,
                "last_error": None,
                "last_path": None,
            })
            _binance_backoff_seconds = 300.0
        except requests.HTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {418, 429}:
                _set_binance_block(exc, "/api/v3/ticker/24hr")
            else:
                raise

    if bybit_symbols and _BYBIT_MARKET_DATA_ENABLED:
        now = time.time()
        cached = _BYBIT_TICKER_CACHE
        if cached is not None and now - cached[0] < _BYBIT_TICKER_CACHE_TTL:
            bybit_data = cached[1]
        elif not _bybit_guard_active():
            try:
                bybit_data = _bybit_client.fetch_tickers(bybit_symbols)
                _BYBIT_TICKER_CACHE = (now, bybit_data)
                _BYBIT_GUARD.update({
                    "state": "READY",
                    "status_code": None,
                    "last_error": None,
                    "last_path": None,
                })
            except BybitMarketDataError as exc:
                _set_bybit_block(exc, "/v5/market/tickers")
                bybit_data = {}
        else:
            bybit_data = cached[1] if cached is not None else {}
        for symbol, ticker in bybit_data.items():
            if symbol in bybit_symbols:
                result[symbol] = dict(ticker)

    # No cross-venue price substitution is performed here.
    return {symbol: result[symbol] for symbol in requested if symbol in result}


def _sync_bybit_ws_kline_manager_cache(manager, cache_key: str, ws_rows: list[dict], stream) -> bool:
    """Keep Bybit manager freshness aligned with the latest symbol-level WS kline observation."""
    if PAPER_VENUE_MODE != "BYBIT_ONLY_LAB" or manager is None or not ws_rows:
        return False
    try:
        stream_snapshot = stream.snapshot()
    except Exception:
        return False
    if not bool(stream_snapshot.get("event_stream_healthy")):
        return False

    # REST warm-up rows do not carry ``is_closed``/WS timestamps. Select the
    # newest candle by open time, then require that the newest row is actually
    # attributable to the live WebSocket before advancing manager freshness.
    candidates = [
        row for row in ws_rows
        if isinstance(row, dict) and row.get("open_time") is not None
    ]
    if not candidates:
        return False
    latest_row = max(
        candidates,
        key=lambda row: int(row.get("open_time") or 0),
    )
    if str(latest_row.get("market_data_transport", "")).upper() != "WEBSOCKET":
        return False

    now = time.time()
    is_closed = bool(latest_row.get("is_closed"))
    if is_closed:
        close_time = latest_row.get("close_time")
        try:
            close_timestamp = float(close_time) / 1000.0
        except (TypeError, ValueError):
            return False
        # For a closed latest row, freshness follows the candle's completed
        # timestamp. This avoids the PR #159 failure mode where the receive
        # timestamp aged out after seconds even though the candle remained the
        # correct latest completed snapshot.
        fetched_at = min(now, close_timestamp)
    else:
        received_at = latest_row.get("received_at")
        try:
            live_age = max(0.0, now - float(received_at))
        except (TypeError, ValueError):
            return False
        if live_age > float(getattr(stream, "stale_after_seconds", 30.0)):
            return False
        # A live current-candle WS observation is the safe heartbeat clock.
        fetched_at = now

    manager.cache.put(
        cache_key,
        ws_rows,
        fetched_at=fetched_at,
        persist=False,
    )
    return True


def _lab_kline_cold_start(
    symbol: str,
    interval: str,
    limit: int,
    *,
    stream,
    key: tuple[str, str, int],
    cache_key: str,
    manager,
) -> list[dict]:
    started_at = time.time()
    if PAPER_VENUE_MODE == "BYBIT_ONLY_LAB" and str(interval) in {"1h", "4h"}:
        _legacy.logger.info(
            "[BYBIT-LAB-REST-FALLBACK] start symbol=%s interval=%s limit=%d",
            symbol,
            interval,
            limit,
        )
    data: list[dict] = []
    if PAPER_VENUE_MODE == "BINANCE_ONLY_LAB":
        # Binance Lab is fully WS-only. There is deliberately no REST
        # cold-start path here, because any REST call would reintroduce the
        # shared-IP problem we are trying to isolate. The runtime warms its
        # historical window from closed WebSocket candles.
        warmup_key = (symbol, str(interval))
        if warmup_key not in _BINANCE_LAB_WARMUP_LOGGED:
            _BINANCE_LAB_WARMUP_LOGGED.add(warmup_key)
            _legacy.logger.info(
                "BINANCE LAB WS WARMUP symbol=%s interval=%s waiting_for_closed_ws_history",
                symbol,
                interval,
            )
        return []
    elif PAPER_VENUE_MODE == "BYBIT_ONLY_LAB":
        if not _BYBIT_MARKET_DATA_ENABLED or _bybit_guard_active():
            return []
        try:
            data = _bybit_client.fetch_klines(symbol, interval, limit)
            if str(interval) in {"1h", "4h"}:
                _legacy.logger.info(
                    "[BYBIT-LAB-REST-FALLBACK] done symbol=%s interval=%s rows=%d elapsed=%.3fs",
                    symbol,
                    interval,
                    len(data),
                    time.time() - started_at,
                )
        except BybitMarketDataError as exc:
            _legacy.logger.warning(
                "[BYBIT-LAB-REST-FALLBACK] failed symbol=%s interval=%s elapsed=%.3fs error=%s",
                symbol,
                interval,
                time.time() - started_at,
                exc,
            )
            _set_bybit_block(exc, f"/v5/market/kline:{symbol}:{interval}")
            return []

    if not data:
        return []
    fetched_at = time.time()
    with _kline_cache_lock:
        _kline_cache[key] = (fetched_at, data)
    if manager is not None:
        try:
            manager.cache.put(cache_key, data, fetched_at=fetched_at)
        except Exception:
            _legacy.logger.exception(
                "MarketDataManager cache sync failed for lab %s %s",
                symbol,
                interval,
            )
    if stream is not None:
        try:
            stream.seed_kline_history(symbol, interval, data)
            return stream.get_kline_history(symbol, interval, limit)
        except Exception:
            pass
    return data


def _guarded_fetch_klines(symbol: str, interval: str, limit: int):
    symbol = str(symbol).upper()
    key = (symbol, str(interval), int(limit))
    now = time.time()
    ttl = _KLINE_CACHE_TTL.get(str(interval), 60.0)
    manager = getattr(_legacy, "market_data_manager", None)
    manager_cache = None
    cache_key = f"{str(interval)}:{str(symbol).upper()}:{int(limit)}"
    if manager is not None:
        try:
            manager_cache = manager.cache.get(cache_key)
        except Exception:
            manager_cache = None

    with _kline_cache_lock:
        cached = _kline_cache.get(key)
        cached_age = None if cached is None else max(0.0, now - cached[0])
        if cached is not None and cached_age < ttl:
            if PAPER_VENUE_LAB:
                stream = _lab_stream_for_mode()
                if stream is not None:
                    try:
                        stream.seed_kline_history(symbol, interval, cached[1])
                        ws_rows = stream.get_kline_history(symbol, interval, limit)
                        if len(ws_rows) >= int(limit):
                            _sync_bybit_ws_kline_manager_cache(manager, cache_key, ws_rows, stream)
                            return ws_rows
                    except Exception:
                        pass
            return cached[1]

    if manager_cache is not None:
        try:
            manager_age = max(0.0, now - float(manager_cache.fetched_at))
            payload = manager_cache.payload
            if manager_age < ttl:
                if PAPER_VENUE_LAB:
                    stream = _lab_stream_for_mode()
                    if stream is not None:
                        try:
                            stream.seed_kline_history(symbol, interval, payload)
                            ws_rows = stream.get_kline_history(symbol, interval, limit)
                            if len(ws_rows) >= int(limit):
                                _sync_bybit_ws_kline_manager_cache(manager, cache_key, ws_rows, stream)
                                return ws_rows
                        except Exception:
                            pass
                with _kline_cache_lock:
                    _kline_cache[key] = (float(manager_cache.fetched_at), payload)
                return payload
        except (TypeError, ValueError):
            pass

    if PAPER_VENUE_LAB:
        stream = _lab_stream_for_mode()
        if stream is not None:
            try:
                ws_rows = stream.get_kline_history(symbol, interval, limit)
            except Exception:
                ws_rows = []
            if len(ws_rows) >= int(limit):
                _sync_bybit_ws_kline_manager_cache(manager, cache_key, ws_rows, stream)
                return ws_rows

        # REST cold-start is also wave-gated. A symbol waits for its scheduler
        # slot so startup cannot create a 22x4 burst.
        allowed_symbols = getattr(_legacy, "_market_data_kline_refresh_symbols", None)
        if manager is not None and isinstance(allowed_symbols, set):
            if symbol not in allowed_symbols:
                return ws_rows if 'ws_rows' in locals() else []

        return _lab_kline_cold_start(
            symbol,
            interval,
            limit,
            stream=stream,
            key=key,
            cache_key=cache_key,
            manager=manager,
        )

    # Existing mixed-lane Paper behavior remains unchanged.
    allowed_symbols = getattr(_legacy, "_market_data_kline_refresh_symbols", None)
    if manager is not None and isinstance(allowed_symbols, set):
        if symbol not in allowed_symbols:
            if manager_cache is None:
                return cached[1] if cached is not None else []
            try:
                stale_age = max(0.0, now - float(manager_cache.fetched_at))
                stale_max = float(
                    manager.policies[str(interval)].stale_max_age_seconds
                )
                if stale_age <= stale_max:
                    return manager_cache.payload
            except (KeyError, TypeError, ValueError, AttributeError):
                pass
            return cached[1] if cached is not None else []

    if symbol in _BYBIT_MARKET_DATA_SYMBOL_SET:
        if not _BYBIT_MARKET_DATA_ENABLED or _bybit_guard_active():
            return cached[1] if cached is not None else []
        try:
            data = _bybit_client.fetch_klines(symbol, interval, limit)
            fetched_at = time.time()
            with _kline_cache_lock:
                _kline_cache[key] = (fetched_at, data)
            if manager is not None:
                try:
                    manager.cache.put(
                        cache_key,
                        data,
                        fetched_at=fetched_at,
                    )
                except Exception:
                    _legacy.logger.exception(
                        "MarketDataManager cache sync failed for Bybit %s %s",
                        symbol,
                        interval,
                    )
            return data
        except BybitMarketDataError as exc:
            _set_bybit_block(exc, f"/v5/market/kline:{symbol}:{interval}")
            return cached[1] if cached is not None else []

    if _binance_guard_active():
        return cached[1] if cached is not None else []

    try:
        data = _original_fetch_klines(symbol, interval, limit)
        fetched_at = time.time()
        with _kline_cache_lock:
            _kline_cache[key] = (fetched_at, data)
        if manager is not None:
            try:
                manager.cache.put(
                    f"{str(interval)}:{symbol}:{int(limit)}",
                    data,
                    fetched_at=fetched_at,
                )
            except Exception:
                _legacy.logger.exception(
                    "MarketDataManager cache sync failed for %s %s",
                    symbol,
                    interval,
                )
        return data
    except requests.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in {418, 429}:
            _set_binance_block(exc, f"/api/v3/klines:{symbol}:{interval}")
            return cached[1] if cached is not None else []
        raise

_legacy.fetch_24h_tickers = _guarded_fetch_24h_tickers
_legacy.fetch_klines = _guarded_fetch_klines


def _market_data_guard_snapshot() -> dict:
    now = time.time()
    remaining = max(0.0, _binance_block_until - now)
    bybit_remaining = max(0.0, _BYBIT_BLOCK_UNTIL - now)
    snapshot = dict(_binance_guard)
    snapshot["blocked_for_seconds"] = round(remaining, 1)
    snapshot["blocked"] = remaining > 0
    snapshot["bybit"] = {
        **dict(_BYBIT_GUARD),
        "enabled": _BYBIT_MARKET_DATA_ENABLED,
        "blocked": bybit_remaining > 0,
        "blocked_for_seconds": round(bybit_remaining, 1),
        "symbols": list(_BYBIT_MARKET_DATA_SYMBOLS),
    }
    snapshot["venue_mode"] = PAPER_VENUE_MODE
    snapshot["source_split"] = {
        "binance_symbols": list(_BINANCE_MARKET_DATA_SYMBOLS),
        "bybit_symbols": list(_BYBIT_MARKET_DATA_SYMBOLS),
    }
    with _kline_cache_lock:
        snapshot["kline_cache_entries"] = len(_kline_cache)
    manager = getattr(_legacy, "market_data_manager", None)
    if manager is not None and callable(getattr(manager, "kline_wave_snapshot", None)):
        try:
            snapshot["kline_wave_scheduler"] = manager.kline_wave_snapshot()
        except Exception:
            snapshot["kline_wave_scheduler"] = {"error": "UNAVAILABLE"}
    else:
        snapshot["kline_wave_scheduler"] = {
            "state": "BOOTSTRAP",
            "wave_count": 3,
            "wave_interval_seconds": 30.0,
        }
    return snapshot


def _fetch_mtf_context() -> dict[str, dict[str, list[dict]]]:
    result: dict[str, dict[str, list[dict]]] = {symbol: {} for symbol in TRADING_SYMBOLS}
    lab_stream = _bybit_market_stream if PAPER_VENUE_MODE == "BYBIT_ONLY_LAB" else (
        _binance_market_stream if PAPER_VENUE_MODE == "BINANCE_ONLY_LAB" else None
    )
    jobs: dict[concurrent.futures.Future, tuple[str, str]] = {}
    for symbol in TRADING_SYMBOLS:
        for timeframe in ("1h", "4h"):
            if lab_stream is not None:
                try:
                    ws_rows = lab_stream.get_kline_history(symbol, timeframe, 60)
                except Exception:
                    ws_rows = []
                if len(ws_rows) >= 60:
                    result[symbol][timeframe] = ws_rows
                    continue
            cached = _mtf_cache.get(symbol, timeframe)
            if cached is not None:
                result[symbol][timeframe] = cached
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        for symbol in TRADING_SYMBOLS:
            for timeframe in ("1h", "4h"):
                if timeframe not in result[symbol]:
                    jobs[executor.submit(_legacy.fetch_klines, symbol, timeframe, 60)] = (symbol, timeframe)
        for future in concurrent.futures.as_completed(jobs):
            symbol, timeframe = jobs[future]
            try:
                candles = future.result()
                if candles:
                    _mtf_cache.put(symbol, timeframe, candles)
                    result[symbol][timeframe] = candles
            except Exception as exc:
                _legacy.logger.warning("MTF kline fetch failed for %s %s: %s", symbol, timeframe, exc)
    return result


def _fetch_strategy_data_with_mtf():
    global _mtf_candles

    # One scheduler claim covers the whole market cycle. The same symbol wave
    # is reused for 5m/15m/1h/4h requests in this cycle, keeping REST traffic
    # distributed without changing the strategy's data semantics.
    manager = getattr(_legacy, "market_data_manager", None)
    if manager is not None and callable(getattr(manager, "claim_kline_refresh_wave", None)):
        wave = manager.claim_kline_refresh_wave()
        _legacy.logger.info(
            "[BYBIT-LAB-CYCLE-TRACE] wave_claim index=%s claimed=%s symbols=%s",
            wave.get("wave_index"),
            wave.get("claimed"),
            wave.get("symbols"),
        )
        _legacy._market_data_kline_refresh_symbols = set(wave.get("symbols", []) or [])
        _legacy._market_data_kline_wave = dict(wave)
    else:
        # Preserve the pre-manager behavior only during bootstrap.
        _legacy._market_data_kline_refresh_symbols = None
        _legacy._market_data_kline_wave = {
            "wave_index": None,
            "symbols": [],
            "claimed": False,
        }

    base_started_at = time.time()
    base = _original_fetch_strategy_data()
    _legacy.logger.info(
        "[BYBIT-LAB-CYCLE-TRACE] base_fetch_done elapsed=%.3fs",
        time.time() - base_started_at,
    )
    mtf_started_at = time.time()
    _mtf_candles = _fetch_mtf_context()
    _legacy.logger.info(
        "[BYBIT-LAB-CYCLE-TRACE] mtf_fetch_done elapsed=%.3fs symbols=%d contexts=%d",
        time.time() - mtf_started_at,
        len(_mtf_candles),
        sum(1 for ctx in _mtf_candles.values() if ctx),
    )
    return base


def _score_symbol_with_mtf(symbol, ticker, candles_15m, candles_5m):
    context = _mtf_candles.get(symbol, {})
    scored = score_symbol(
        symbol,
        ticker,
        candles_15m,
        candles_5m,
        context.get("1h", []),
        context.get("4h", []),
    )
    if isinstance(scored, dict):
        scored["market_data_source"] = str(
            ticker.get("market_data_source", "UNKNOWN")
        ).upper()
    return scored


_legacy.fetch_strategy_data = _fetch_strategy_data_with_mtf
_legacy.score_symbol = _score_symbol_with_mtf
_legacy.BUY_SCORE_THRESHOLD = BUY_SCORE_THRESHOLD
app = _legacy.app
runtime = _legacy.runtime
runtime.correlation_provider = KlineCorrelationProvider(
    runtime.repository,
    _correlation_candle_loader,
    lookback_candles=runtime.risk_config.correlation.lookback_candles,
)
runtime.risk_gateway.correlation_provider = runtime.correlation_provider
_legacy.logger.info(
    "[CORRELATION-CONFIG] enabled=%s threshold=%.2f lookback=%d provider=%s",
    runtime.risk_config.options.enable_correlation_control and runtime.risk_config.correlation.enabled,
    runtime.risk_config.correlation.maximum_correlation,
    runtime.risk_config.correlation.lookback_candles,
    type(runtime.correlation_provider).__name__,
)
TRADING_SYMBOLS = _legacy.TRADING_SYMBOLS

def _seed_binance_lab_stream_from_manager_cache(stream) -> int:
    """Hydrate the Binance Lab WS history from the already-validated local snapshot.

    The Binance Lab is intentionally REST-free. When the GitHub market snapshot
    has been loaded into MarketDataManager, the WS runtime must consume that
    closed history immediately instead of waiting for 60/150 closed candles to
    arrive over WebSocket after every deploy/restart.
    """
    if PAPER_VENUE_MODE != "BINANCE_ONLY_LAB" or stream is None:
        return 0
    manager = getattr(_legacy, "market_data_manager", None)
    cache = getattr(manager, "cache", None) if manager is not None else None
    if cache is None:
        return 0
    seeded = 0
    intervals = ("5m", "15m", "1h", "4h")
    limits = {"5m": 60, "15m": 150, "1h": 60, "4h": 60}
    for symbol in TRADING_SYMBOLS:
        for interval in intervals:
            try:
                snapshot = cache.get(f"{interval}:{symbol}:{limits[interval]}")
                if snapshot is None or not isinstance(snapshot.payload, list):
                    continue
                rows = snapshot.payload
                if len(rows) < limits[interval]:
                    continue
                count = stream.seed_kline_history(symbol, interval, rows)
                if count >= limits[interval]:
                    seeded += 1
            except Exception as exc:
                _legacy.logger.debug(
                    "[BINANCE-SNAPSHOT] runtime seed skipped symbol=%s interval=%s error=%s",
                    symbol, interval, type(exc).__name__,
                )
    if seeded:
        _legacy.logger.info(
            "[BINANCE-SNAPSHOT] runtime warm-start seeded=%d/%d series from MarketDataManager",
            seeded, len(TRADING_SYMBOLS) * len(intervals),
        )
    else:
        _legacy.logger.info(
            "[BINANCE-SNAPSHOT] runtime warm-start seeded=0/%d series; WS history will warm normally",
            len(TRADING_SYMBOLS) * len(intervals),
        )
    return seeded


# Venue Lab WebSocket feed.
# MIXED keeps the existing 5m/15m Binance stream contract for the main bot.
# Each isolated lab uses all four strategy timeframes from its own venue so
# 1h/4h context does not silently fall back to the other exchange.
_binance_market_stream = None
_bybit_market_stream = None
if PAPER_VENUE_MODE != "BYBIT_ONLY_LAB":
    _binance_ws_intervals = ("5m", "15m", "1h", "4h") if PAPER_VENUE_MODE == "BINANCE_ONLY_LAB" else ("5m", "15m")
    _binance_market_stream = BinanceMarketStream(
        TRADING_SYMBOLS,
        intervals=_binance_ws_intervals,
    )
    if PAPER_VENUE_MODE == "BINANCE_ONLY_LAB":
        _seed_binance_lab_stream_from_manager_cache(_binance_market_stream)
    if globals().get("_SHADOW_MAIN_EMBEDDED", False):
        _binance_market_stream.start()
    _legacy.binance_market_stream = _binance_market_stream
else:
    _legacy.binance_market_stream = None

if PAPER_VENUE_MODE == "BYBIT_ONLY_LAB":
    _bybit_market_stream = BybitMarketStream(
        TRADING_SYMBOLS,
        intervals=("5m", "15m", "1h", "4h"),
    )
    if globals().get("_SHADOW_MAIN_EMBEDDED", False):
        _bybit_market_stream.start()
    _legacy.bybit_market_stream = _bybit_market_stream
else:
    _legacy.bybit_market_stream = None


def _binance_ws_health():
    if _binance_market_stream is None:
        return jsonify({"available": False, "venue_mode": PAPER_VENUE_MODE}), 200
    return jsonify(_binance_market_stream.snapshot()), 200


def _bybit_ws_health():
    if _bybit_market_stream is None:
        return jsonify({"available": False, "venue_mode": PAPER_VENUE_MODE}), 200
    return jsonify(_bybit_market_stream.snapshot()), 200


if "binance_ws_health" not in app.view_functions:
    app.add_url_rule(
        "/binance-ws-health",
        endpoint="binance_ws_health",
        view_func=_binance_ws_health,
    )
if "bybit_ws_health" not in app.view_functions:
    app.add_url_rule(
        "/bybit-ws-health",
        endpoint="bybit_ws_health",
        view_func=_bybit_ws_health,
    )
brain_shadow_runtime = BrainShadowRuntime()
_brain_shadow_persistence_dir = getattr(runtime, "persistence_dir", None)
_brain_shadow_database_url = database_url_from_env()
if _brain_shadow_database_url:
    brain_shadow_store = PostgresEvidenceStore(
        _brain_shadow_database_url,
        evidence_type=f"BRAIN_SHADOW{'' if PAPER_VENUE_MODE == 'MIXED' else '_' + PAPER_VENUE_MODE}",
        max_records=50_000,
    )
else:
    brain_shadow_store = BrainShadowCaptureStore(
        Path(_brain_shadow_persistence_dir or ".") / "brain_shadow" / "captures.jsonl"
    )
runtime.brain_shadow_store = brain_shadow_store

_original_dual_score_symbol = _score_symbol_with_mtf


def _score_symbol_with_diagnostics(symbol, ticker, candles_15m, candles_5m):
    try:
        result = _original_dual_score_symbol(symbol, ticker, candles_15m, candles_5m)
        _legacy.latest_scores[symbol] = result
        _legacy.market_state[symbol] = result
        return result
    except Exception as exc:
        _legacy.last_score_diagnostics[symbol] = {
            "symbol": symbol, "stage": "SCORE",
            "error": f"{type(exc).__name__}: {exc}", "finished_at": time.time(),
        }
        raise


_legacy.score_symbol = _score_symbol_with_diagnostics
if not hasattr(_legacy, "last_score_diagnostics"):
    _legacy.last_score_diagnostics = {}
_original_process_market_cycle = _legacy.process_market_cycle


def _process_market_cycle_with_diagnostics():
    started = time.time()
    _legacy.last_score_diagnostics = {}
    try:
        return _original_process_market_cycle()
    except Exception as exc:
        _legacy.last_score_diagnostics["__cycle__"] = {
            "stage": "MARKET_CYCLE", "error": f"{type(exc).__name__}: {exc}",
            "finished_at": time.time(),
            "elapsed_seconds": round(time.time() - started, 3),
            "partial_data_count": len(_legacy.latest_scores),
        }
        raise


_legacy.process_market_cycle = _process_market_cycle_with_diagnostics
_original_build_daily_report = _legacy.build_daily_report


def _net_only_daily_report(date_key=None) -> str:
    report = _original_build_daily_report(date_key)
    lines = [line for line in report.splitlines() if not line.startswith("💵 Paper cash:")]
    return "\n".join(lines).replace("TOTAL", "NET P&L", 1)


_legacy.build_daily_report = _net_only_daily_report

_current_trade_mode = {"value": "SWING"}

_PAPER_BOT_IDENTITY = {
    "MIXED": ("MAIN BOT", "MIXED / 22-SYMBOL SHARDED"),
    "BINANCE_ONLY_LAB": ("BINANCE LAB", "BINANCE ONLY / 22 SYMBOLS"),
    "BYBIT_ONLY_LAB": ("BYBIT LAB", "BYBIT ONLY / 22 SYMBOLS"),
}.get(
    PAPER_VENUE_MODE,
    ("UNKNOWN BOT", PAPER_VENUE_MODE),
)


def _telegram_identity_header() -> str:
    name, venue = _PAPER_BOT_IDENTITY
    return f"🤖 BOT: {name}\n🏷️ VENUE: {venue}"


_original_controller_evaluate = runtime.risk_controller.evaluate
_original_controller_has_position = runtime.controller.has_position
_original_portfolio_snapshot = runtime.portfolio_provider.snapshot
_original_runtime_open_position = runtime.open_position
_original_send_telegram_message = _legacy.send_telegram_message


def _mode_aware_risk_evaluate(*, account, symbol, signal, market, symbol_exposure=None, correlation_score=0.0):
    mode = _current_trade_mode["value"]
    return _original_controller_evaluate(account=account, symbol=symbol, signal=mode, market=market, symbol_exposure=symbol_exposure, correlation_score=correlation_score)


runtime.risk_controller.evaluate = _mode_aware_risk_evaluate


def _active_trade_modes(symbol: str) -> set[str]:
    active = {"OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"}
    return {
        str(position.entry_metadata.get("trade_mode", "SWING")).upper()
        for position in runtime.repository.get_by_symbol(symbol)
        if position.status.name in active
    }


def _lane_aware_has_position(symbol: str) -> bool:
    score = _legacy.latest_scores.get(str(symbol).upper(), {}) or {}
    scalp_buy = score.get("scalp_signal") == "BUY"
    swing_buy = score.get("swing_signal") == "BUY"
    active_modes = _active_trade_modes(symbol)
    if scalp_buy and swing_buy:
        return {"SCALP", "SWING"}.issubset(active_modes)
    if scalp_buy:
        return "SCALP" in active_modes
    if swing_buy:
        return "SWING" in active_modes
    return bool(active_modes)


# The legacy pre-entry check used symbol-only identity. Keep the controller's
# lifecycle implementation untouched, but make this one orchestration check
# lane-aware so an existing SCALP does not block an independent SWING (and
# vice-versa).
runtime.controller.has_position = _lane_aware_has_position


def _lane_aware_portfolio_snapshot():
    snapshot = _original_portfolio_snapshot()
    active = [p for p in runtime.repository.get_open_positions() if p.status.name in {"OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"}]
    scalp_count = sum(1 for p in active if str(p.entry_metadata.get("trade_mode", "SWING")).upper() == "SCALP")
    swing_count = sum(1 for p in active if str(p.entry_metadata.get("trade_mode", "SWING")).upper() == "SWING")
    return replace(snapshot, scalp_open_positions=scalp_count, swing_open_positions=swing_count)


runtime.portfolio_provider.snapshot = _lane_aware_portfolio_snapshot


def _open_one_position(symbol: str, entry_price: float, stop_loss: float, mode: str):
    _current_trade_mode["value"] = mode
    position = _original_runtime_open_position(symbol, entry_price, stop_loss, trade_mode=mode)
    if position is not None:
        position.entry_metadata["trade_mode"] = mode
        position.metadata["trade_mode"] = mode
        runtime.repository.update(position)
    return position


def _open_position_with_selected_mode(symbol: str, entry_price: float, stop_loss: float):
    score = _legacy.latest_scores.get(symbol, {}) or {}
    modes = []
    if score.get("scalp_signal") == "BUY":
        modes.append("SCALP")
    if score.get("swing_signal") == "BUY":
        modes.append("SWING")
    if not modes:
        mode = str(score.get("trade_mode", "SWING")).upper()
        modes = [mode if mode in {"SCALP", "SWING"} else "SWING"]

    opened = []
    for mode in modes:
        position = _open_one_position(symbol, entry_price, stop_loss, mode)
        if position is not None:
            opened.append(position)

    trace = runtime.last_entry_diagnostics.setdefault(symbol, {})
    trace["trade_modes_requested"] = list(modes)
    trace["trade_modes_opened"] = [str(p.entry_metadata.get("trade_mode", "SWING")).upper() for p in opened]
    trace["positions_opened"] = [p.position_id for p in opened]
    trace["dual_lane_entry"] = len(opened) > 1
    return opened[0] if opened else None


runtime.open_position = _open_position_with_selected_mode


def _send_telegram_with_trade_type(message: str) -> bool:
    # Every Telegram message is explicitly tagged with the source bot and venue.
    # This makes BUY/SELL/health/report messages unambiguous when all three
    # Paper processes share the same Telegram chat.
    identity_header = _telegram_identity_header()
    if not message.startswith("🤖 BOT: "):
        message = f"{identity_header}\n{message}"

    if message.startswith("🤖 BOT: ") and "=== PAPER BUY ===" in message:
        symbol = ""
        for line in message.splitlines():
            if line.startswith("Symbol:"):
                symbol = line.split(":", 1)[1].strip().upper()
                break
        score = _legacy.latest_scores.get(symbol, {}) or {}
        if score.get("scalp_signal") == "BUY" and score.get("swing_signal") == "BUY":
            mode = "SCALP + SWING (independent positions)"
        else:
            mode = str(score.get("trade_mode", _current_trade_mode["value"])).upper()
            if mode not in {"SCALP", "SWING"}:
                mode = _current_trade_mode["value"]
        lines = message.splitlines()
        try:
            symbol_index = next(i for i, line in enumerate(lines) if line.startswith("Symbol:"))
            lines.insert(symbol_index + 1, f"Trade Type: {mode}")
            message = "\n".join(lines)
        except StopIteration:
            pass
    return _original_send_telegram_message(message)


_legacy.send_telegram_message = _send_telegram_with_trade_type


def _home():
    positions = runtime.facade.get_open_positions()
    metrics = runtime.facade.get_metrics()
    return jsonify({
        "status": "healthy", "mode": "PAPER", "entrypoint": "shadow_main.py",
        "strategy": "SCALP 5m trigger + 15m setup + 1h/4h multi-candle context / SWING 15m macro + 5m confirmation",
        "trade_manager": "modular_parts_1_8", "symbols": TRADING_SYMBOLS,
        "open_positions": len(positions),
        "scalp_open_positions": sum(1 for p in positions if str(p.entry_metadata.get("trade_mode", "SWING")).upper() == "SCALP"),
        "swing_open_positions": sum(1 for p in positions if str(p.entry_metadata.get("trade_mode", "SWING")).upper() == "SWING"),
        "scalp_max_open_positions": runtime.risk_config.exposure.max_scalp_positions,
        "swing_max_open_positions": runtime.risk_config.exposure.max_swing_positions,
        "metrics": getattr(metrics, "__dict__", str(metrics)),
        "score_threshold": SWING_SCORE_THRESHOLD,
        "scalp_score_threshold": SCALP_SCORE_THRESHOLD,
        "swing_score_threshold": SWING_SCORE_THRESHOLD,
        "telegram_configured": bool(_legacy.TELEGRAM_TOKEN and _legacy.TELEGRAM_CHAT_ID),
        "exit_watchdog": runtime.last_exit_watchdog,
        "brain_shadow": brain_shadow_runtime.snapshot(),
    }), 200


app.view_functions["home"] = _home


def _diagnostics():
    rows = sorted(_legacy.latest_scores.values(), key=lambda item: item.get("score", 0), reverse=True)
    return jsonify({
        "mode": "PAPER", "symbol_count": len(TRADING_SYMBOLS), "data_count": len(rows),
        "buy_count": sum(1 for row in rows if row.get("signal") == "BUY"),
        "score_threshold": BUY_SCORE_THRESHOLD,
        "scalp_score_threshold": SCALP_SCORE_THRESHOLD,
        "swing_score_threshold": SWING_SCORE_THRESHOLD,
        "symbols_added": _ADDITIONAL_HALAL_SPOT_SYMBOLS,
        "scores": rows,
        "score_errors": getattr(_legacy, "last_score_diagnostics", {}),
        "market_data_guard": _market_data_guard_snapshot(),
        "entry_diagnostics": runtime.last_entry_diagnostics,
    }), 200


app.view_functions["diagnostics"] = _diagnostics


def _notify_closed_positions() -> int:
    sent = 0
    for position in runtime.repository.get_closed_positions():
        if position.exit_metadata.get("telegram_notification_sent"):
            continue
        reason = getattr(position.close_reason, "name", str(position.close_reason))
        exit_price = float(position.exit_metadata.get("exit_price", position.current_price))
        exit_message = str(position.exit_metadata.get("exit_message", "")).strip()
        entry_value = float(position.entry_price) * float(position.quantity)
        pnl_pct = (float(position.gross_pnl) / entry_value * 100.0) if entry_value else 0.0
        paper_cash = position.exit_metadata.get("paper_cash_after", runtime.execution_adapter.balance.cash)
        entry_metadata = getattr(position, "entry_metadata", {}) or {}
        trade_mode = str(entry_metadata.get("trade_mode", "SWING")).upper()
        message = (
            "=== PAPER SELL ===\n"
            f"Symbol: {position.symbol}\n"
            f"Position ID: {getattr(position, 'position_id', 'UNKNOWN')}\n"
            f"Trade Type: {trade_mode}\n"
            f"Reason: {reason}\n"
            f"Quantity: {position.quantity:.12f}\n"
            f"Entry: {position.entry_price:.8f}\n"
            f"Exit: {exit_price:.8f}\n"
            f"Gross P&L: {position.gross_pnl:+.4f}$\n"
            f"P&L %: {pnl_pct:+.2f}%\n"
            f"Fees: {position.total_fees:.4f}$\n"
            f"Net P&L: {position.realized_pnl:+.4f}$\n"
            + (f"Exit details: {exit_message}\n" if exit_message else "")
            + f"Paper cash: ${float(paper_cash):.2f}\nPAPER ONLY"
        )
        if _legacy.send_telegram_message(message):
            position.exit_metadata["telegram_notification_sent"] = True
            position.exit_metadata["telegram_notification_sent_at"] = time.time()
            runtime.repository.update(position)
            sent += 1
    return sent


def _sanitize_entry_diagnostics() -> None:
    open_positions = {
        str(position.symbol).upper(): position
        for position in runtime.repository.get_open_positions()
        if position.status.name in {"OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"}
    }
    for symbol, trace in runtime.last_entry_diagnostics.items():
        if not isinstance(trace, dict):
            continue
        # The legacy cycle uses setdefault(), so an old rejection can remain
        # beside a later successful fill. Prefer the authoritative execution
        # evidence when it exists; this fixes the diagnostic without touching
        # Trade Manager or the entry decision itself.
        if symbol in open_positions and trace.get("position_id"):
            execution = str(trace.get("execution", "")).upper()
            outcome = str(trace.get("execution_outcome", "")).upper()
            if execution == "FILLED" or outcome in {"FILLED", "EXECUTION_FILLED"}:
                trace["result"] = "POSITION_COMMITTED"
                trace["diagnostic_consistency"] = "CONSISTENT"
                continue
        result = str(trace.get("result", ""))
        if result.startswith("REJECTED_"):
            trace["execution"] = "NOT_RUN"
            trace["execution_outcome"] = None
            trace["facade"] = "NOT_RUN"
            trace.pop("facade_diagnostic", None)
            trace.pop("position_id", None)


def _run_brain_shadow_cycle() -> None:
    latest = getattr(_legacy, "latest_scores", {}) or {}
    btc_guard = globals().get("_last_btc_guard", {})
    market_view = derive_market_breadth(
        latest,
        btc_crashing=bool(btc_guard.get("crashing")) if isinstance(btc_guard, dict) else False,
    )
    runtime.last_entry_diagnostics.setdefault("__brain_shadow__", {})["market_regime"] = market_view.to_dict()

    active_modes_by_symbol: dict[str, set[str]] = {}
    active_statuses = {"OPEN", "HOLD", "REVIEW_REQUIRED", "PARTIALLY_CLOSED"}
    for position in runtime.repository.get_open_positions():
        if position.status.name not in active_statuses:
            continue
        symbol = str(position.symbol).upper()
        mode = str(position.entry_metadata.get("trade_mode", "SWING")).upper()
        active_modes_by_symbol.setdefault(symbol, set()).add(mode)

    for symbol, strategy in latest.items():
        try:
            normalized = str(symbol).upper()
            trace = runtime.last_entry_diagnostics.get(normalized, {}) or {}
            opened_modes = {
                str(mode).upper()
                for mode in trace.get("trade_modes_opened", []) or []
            }

            scalp_buy = strategy.get("scalp_signal") == "BUY"
            swing_buy = strategy.get("swing_signal") == "BUY"
            candidate_modes = []
            if scalp_buy:
                candidate_modes.append("SCALP")
            if swing_buy:
                candidate_modes.append("SWING")
            if not candidate_modes:
                candidate_modes = [str(strategy.get("trade_mode", "NONE") or "NONE").upper()]

            shadow_by_mode: dict[str, dict[str, Any]] = {}
            for mode in candidate_modes:
                mode_context = dict(strategy)
                mode_context["trade_mode"] = mode
                if mode == "SCALP":
                    mode_context["signal"] = "BUY" if scalp_buy else str(strategy.get("scalp_signal", "HOLD")).upper()
                    if strategy.get("scalp_score") is not None:
                        mode_context["score"] = strategy.get("scalp_score")
                elif mode == "SWING":
                    mode_context["signal"] = "BUY" if swing_buy else str(strategy.get("swing_signal", "HOLD")).upper()
                    if strategy.get("swing_score") is not None:
                        mode_context["score"] = strategy.get("swing_score")

                if mode in opened_modes:
                    existing_before_entry = False
                else:
                    existing_before_entry = mode in active_modes_by_symbol.get(normalized, set())
                    if str(trace.get("result", "")).upper() == "REJECTED_EXISTING_POSITION":
                        existing_before_entry = True

                entry_v2_by_mode = trace.get("entry_v2_shadow_by_mode", {}) or {}
                mode_capture = entry_v2_by_mode.get(mode, {}) or {}
                capture_id = mode_capture.get("capture_id")

                # In dual-lane candidates the Brain record must inherit the
                # capture ID belonging to the same lane. Never fall back to a
                # symbol-level capture here, because that would mix SCALP and
                # SWING outcomes during post-hoc attribution.
                record = brain_shadow_runtime.evaluate_entry(
                    normalized,
                    mode_context,
                    existing_position=existing_before_entry,
                    market_regime=market_view.regime,
                    entry_v2_capture_id=capture_id,
                )
                shadow_by_mode[mode] = record.to_dict()

                # Persist the exact entry-cycle Brain Shadow observation onto
                # the matching Paper position. The match uses the immutable
                # Entry v2 capture identity plus lane, so later scan-time
                # HOLD observations cannot overwrite entry evidence.
                if capture_id:
                    attach_brain_shadow_entry(runtime.repository, record.to_dict())

                if (
                    record.strategy_action == "BUY"
                    and capture_id
                ):
                    persisted = brain_shadow_store.append(record.to_dict())
                    if not persisted:
                        runtime.last_entry_diagnostics.setdefault(
                            "__brain_shadow__", {}
                        )["persistence_error"] = brain_shadow_store.last_error

                if not record.agreement:
                    _legacy.logger.info(
                        "Brain shadow disagreement: symbol=%s mode=%s strategy=%s score=%.1f brain=%s confidence=%.2f reason=%s",
                        record.symbol,
                        record.trade_mode,
                        record.strategy_action,
                        record.strategy_score,
                        record.brain_action,
                        record.brain_confidence,
                        record.brain_reason,
                    )

            if shadow_by_mode:
                trace["brain_shadow_by_mode"] = shadow_by_mode
                if len(shadow_by_mode) == 1:
                    trace["brain_shadow"] = next(iter(shadow_by_mode.values()))
                runtime.last_entry_diagnostics[normalized] = trace
        except Exception:
            _legacy.logger.exception("Brain shadow evaluation failed for %s", symbol)


async def _dual_mode_engine():
    _legacy.send_telegram_message(
        "🟢 Paper Trading dual-mode strategy engine started on Render\n"
        f"Universe: {len(TRADING_SYMBOLS)} Binance Spot USDT pairs\n"
        f"Scalp: 5m trigger + 15m setup + 1h/4h candle context | threshold {SCALP_SCORE_THRESHOLD} | max open 15\n"
        f"Swing: 15m macro + 5m confirmation | threshold {SWING_SCORE_THRESHOLD} | max open 10\n"
        "Trade Manager: Parts 1-8\nBrain: GUARDED PAPER ENTRY GATE — Legacy remains execution authority\nNo real exchange orders are submitted."
    )
    _notify_closed_positions()

    cycle_number = 0
    while True:
        cycle_number += 1
        started = time.monotonic()
        heartbeat = runtime.last_entry_diagnostics.setdefault("__paper_loop__", {})
        heartbeat.update({
            "cycle": cycle_number,
            "state": "START",
            "started_at": time.time(),
            "finished_at": None,
            "elapsed_seconds": None,
            "failure": None,
        })
        _legacy.logger.info("PAPER LOOP HEARTBEAT cycle=%d state=START", cycle_number)

        try:
            heartbeat["state"] = "MARKET_CYCLE"
            heartbeat["market_cycle_started_at"] = time.time()
            _legacy.logger.info("PAPER LOOP HEARTBEAT cycle=%d state=MARKET_CYCLE", cycle_number)
            await asyncio.to_thread(_legacy.process_market_cycle)
            heartbeat["market_cycle_finished_at"] = time.time()
            _legacy.logger.info("PAPER LOOP HEARTBEAT cycle=%d state=MARKET_CYCLE_DONE", cycle_number)

            heartbeat["state"] = "BRAIN_SHADOW"
            heartbeat["brain_shadow_started_at"] = time.time()
            _legacy.logger.info("PAPER LOOP HEARTBEAT cycle=%d state=BRAIN_SHADOW", cycle_number)
            _run_brain_shadow_cycle()
            heartbeat["brain_shadow_finished_at"] = time.time()
            _legacy.logger.info("PAPER LOOP HEARTBEAT cycle=%d state=BRAIN_SHADOW_DONE", cycle_number)

            heartbeat["state"] = "EXIT_WATCHDOG"
            heartbeat["exit_watchdog_started_at"] = time.time()
            _legacy.logger.info("PAPER LOOP HEARTBEAT cycle=%d state=EXIT_WATCHDOG", cycle_number)
            watchdog = runtime.run_exit_watchdog()
            heartbeat["exit_watchdog_finished_at"] = time.time()
            if watchdog.exit_signals or watchdog.failed:
                _legacy.logger.info(
                    "Exit watchdog: evaluated=%d signals=%d closed=%d failed=%d",
                    watchdog.evaluated, watchdog.exit_signals, watchdog.closed, watchdog.failed
                )

            heartbeat["state"] = "SANITIZE"
            _legacy.logger.info("PAPER LOOP HEARTBEAT cycle=%d state=SANITIZE", cycle_number)
            _sanitize_entry_diagnostics()
            heartbeat["sanitize_finished_at"] = time.time()
            heartbeat["state"] = "READY"
        except Exception as exc:
            heartbeat["state"] = "ERROR"
            heartbeat["failure"] = f"{type(exc).__name__}: {exc}"
            _legacy.logger.exception("Dual-mode paper market cycle failed")
        finally:
            try:
                heartbeat["state"] = "NOTIFY_CLOSED"
                _legacy.logger.info("PAPER LOOP HEARTBEAT cycle=%d state=NOTIFY_CLOSED", cycle_number)
                _notify_closed_positions()
                heartbeat["notify_closed_finished_at"] = time.time()
            except Exception:
                heartbeat["state"] = "NOTIFY_ERROR"
                heartbeat["failure"] = "Paper SELL notification reconciliation failed"
                _legacy.logger.exception("Paper SELL notification reconciliation failed")

        elapsed = time.monotonic() - started
        heartbeat["finished_at"] = time.time()
        heartbeat["elapsed_seconds"] = round(elapsed, 3)
        if heartbeat["state"] not in {"ERROR", "NOTIFY_ERROR"}:
            heartbeat["state"] = "SLEEP"
        _legacy.logger.info(
            "PAPER LOOP HEARTBEAT cycle=%d state=%s elapsed=%.3fs",
            cycle_number, heartbeat["state"], elapsed
        )
        await asyncio.sleep(max(1.0, _legacy.LOOP_SECONDS - elapsed))


if __name__ == "__main__" and not globals().get("_SHADOW_MAIN_EMBEDDED", False):
    threading.Thread(target=_legacy._daily_report_loop, daemon=True, name="paper-daily-report").start()
    threading.Thread(target=lambda: asyncio.run(_dual_mode_engine()), daemon=True, name="dual-mode-market-engine").start()
    _legacy.run_flask()
