"""Runtime defaults and process-wide Binance REST protection."""

import os
import threading
import time
from urllib.parse import urlparse

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


def _is_binance_market_host(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return host == "data-api.binance.vision" or host.endswith(".binance.com") or host == "binance.com"


if requests is not None:
    def _retry_after(response) -> float:
        value = response.headers.get("Retry-After") if response is not None else None
        try:
            return max(1.0, float(value))
        except (TypeError, ValueError):
            return _BINANCE_DEFAULT_RETRY

    def _synthetic_block_error(remaining: float) -> requests.HTTPError:
        response = requests.Response()
        response.status_code = 418
        response.headers["Retry-After"] = str(max(1, int(remaining)))
        response.url = "https://data-api.binance.vision/api/v3/market-data-circuit"
        return requests.HTTPError("Binance market-data circuit is open", response=response)

    _original_session_request = requests.sessions.Session.request

    def _protected_session_request(self, method, url, **kwargs):
        global _BINANCE_BLOCK_UNTIL
        if _is_binance_market_host(str(url)):
            with _BINANCE_BLOCK_LOCK:
                remaining = _BINANCE_BLOCK_UNTIL - time.time()
            if remaining > 0:
                raise _synthetic_block_error(remaining)

        response = _original_session_request(self, method, url, **kwargs)

        if _is_binance_market_host(str(url)) and response.status_code in {418, 429}:
            retry_after = _retry_after(response)
            with _BINANCE_BLOCK_LOCK:
                _BINANCE_BLOCK_UNTIL = max(_BINANCE_BLOCK_UNTIL, time.time() + retry_after)
        return response

    requests.sessions.Session.request = _protected_session_request
