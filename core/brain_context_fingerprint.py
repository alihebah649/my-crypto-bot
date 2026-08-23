"""Stable fingerprinting for reproducible Brain contexts."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def brain_context_fingerprint(context: Mapping[str, Any]) -> str:
    """Return a deterministic SHA-256 fingerprint of a Brain context."""
    payload = json.dumps(context, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["brain_context_fingerprint"]
