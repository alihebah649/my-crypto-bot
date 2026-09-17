"""Non-authoritative Entry v2 shadow capture.

The capture layer records the exact legacy observation, the translated Entry v2
scenario, the candle-structure evidence, and both decisions. It never executes,
vetoes, mutates positions, or writes to trading state.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .entry_engine import EntryDecision, EntryEngineV2
from .entry_v2_adapter import EntryV2MarketFacts, build_entry_scenario

SCHEMA_VERSION = 1
TIMEFRAMES = ("5m", "15m", "1h", "4h")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _last_closed_window(candles: Any, size: int = 8) -> list[dict[str, Any]]:
    values = list(candles or [])
    closed = values[:-1] if len(values) > 1 else []
    return [_json_safe(candle) for candle in closed[-size:]]


@dataclass(frozen=True)
class EntryV2ShadowCapture:
    schema_version: int
    captured_at: str
    symbol: str
    legacy_result: Mapping[str, Any]
    entry_scenario: Mapping[str, Any]
    v2_decision: Mapping[str, Any]
    closed_candle_windows: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _json_safe(asdict(self))


def _decision_to_dict(decision: EntryDecision) -> dict[str, Any]:
    return {
        "approved": bool(decision.approved),
        "decision": decision.decision,
        "trade_mode": decision.trade_mode,
        "setup_type": decision.setup_type,
        "failed_gate": decision.failed_gate,
        "passed_gates": list(decision.passed_gates),
        "reasons": list(decision.reasons),
        "diagnostics": _json_safe(decision.diagnostics),
    }


def capture_entry_v2(
    symbol: str,
    facts: EntryV2MarketFacts,
    *,
    captured_at: str | None = None,
) -> EntryV2ShadowCapture:
    """Build an immutable audit record from one already-observed market state."""
    scenario = build_entry_scenario(facts)
    decision = EntryEngineV2().evaluate(scenario)
    timestamp = captured_at or datetime.now(timezone.utc).isoformat()

    return EntryV2ShadowCapture(
        schema_version=SCHEMA_VERSION,
        captured_at=str(timestamp),
        symbol=str(symbol),
        legacy_result=deepcopy(_json_safe(facts.legacy_result)),
        entry_scenario=deepcopy(_json_safe(scenario)),
        v2_decision=_decision_to_dict(decision),
        closed_candle_windows={
            "5m": _last_closed_window(facts.candles_5m),
            "15m": _last_closed_window(facts.candles_15m),
            "1h": _last_closed_window(facts.candles_1h),
            "4h": _last_closed_window(facts.candles_4h),
        },
    )


def replay_captured(capture: EntryV2ShadowCapture | Mapping[str, Any]) -> EntryDecision:
    """Re-evaluate only the captured Entry v2 scenario; no exchange/state access."""
    scenario = capture.entry_scenario if isinstance(capture, EntryV2ShadowCapture) else capture.get("entry_scenario", {})
    return EntryEngineV2().evaluate(scenario)


def capture_summary(capture: EntryV2ShadowCapture) -> dict[str, Any]:
    """Return a compact row suitable for CSV/JSON reporting."""
    legacy = capture.legacy_result
    decision = capture.v2_decision
    risk = capture.entry_scenario.get("risk", {})
    return {
        "schema_version": capture.schema_version,
        "captured_at": capture.captured_at,
        "symbol": capture.symbol,
        "legacy_signal": legacy.get("signal", "HOLD"),
        "legacy_trade_mode": legacy.get("trade_mode", "NONE"),
        "legacy_score": legacy.get("score"),
        "legacy_scalp_score": legacy.get("scalp_score"),
        "legacy_swing_score": legacy.get("swing_score"),
        "v2_decision": decision.get("decision"),
        "v2_trade_mode": decision.get("trade_mode"),
        "v2_setup_type": decision.get("setup_type"),
        "v2_failed_gate": decision.get("failed_gate"),
        "v2_approved": decision.get("approved", False),
        "target_price": risk.get("target_price"),
        "target_source": risk.get("target_source"),
        "target_status": risk.get("target_status"),
        "reward_risk": risk.get("reward_risk"),
        "stop_distance_percent": risk.get("stop_distance_percent"),
        "candle_patterns_5m": tuple(capture.entry_scenario.get("structure", {}).get("multi_candle_by_timeframe", {}).get("5m", {}).get("patterns", ())),
        "candle_patterns_15m": tuple(capture.entry_scenario.get("structure", {}).get("multi_candle_by_timeframe", {}).get("15m", {}).get("patterns", ())),
        "candle_patterns_1h": tuple(capture.entry_scenario.get("structure", {}).get("multi_candle_by_timeframe", {}).get("1h", {}).get("patterns", ())),
        "candle_patterns_4h": tuple(capture.entry_scenario.get("structure", {}).get("multi_candle_by_timeframe", {}).get("4h", {}).get("patterns", ())),
    }
