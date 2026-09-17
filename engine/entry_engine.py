"""Entry v2 decision contract for separate SCALP and SWING lanes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class EntryDecision:
    approved: bool
    decision: str
    trade_mode: str
    setup_type: str | None
    failed_gate: str | None = None
    passed_gates: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    diagnostics: Mapping[str, Any] = field(default_factory=dict)


class EntryEngineV2:
    """Pure Entry v2 gate engine. Score is diagnostic, never authorization."""

    SCALP_SCORE_THRESHOLD = 65
    SWING_SCORE_THRESHOLD = 80
    MAX_STOP_DISTANCE_PERCENT = 3.0
    MAX_SWING_STOP_DISTANCE_PERCENT = 5.0
    MIN_REWARD_RISK = 1.0
    MIN_SWING_REWARD_RISK = 1.5
    MAX_SPREAD_PERCENT = 0.15
    MIN_SCALP_VOLUME_RATIO = 1.0
    MIN_SWING_VOLUME_RATIO = 0.9

    def evaluate(self, scenario: Any) -> EntryDecision:
        market = self._mapping(scenario, "market")
        structure = self._mapping(scenario, "structure")
        trigger = self._mapping(scenario, "trigger")
        execution = self._mapping(scenario, "execution")
        risk = self._mapping(scenario, "risk")
        metadata = self._mapping(scenario, "metadata")
        mode = self._value(scenario, "trade_mode", "SCALP")
        mode = str(mode or "SCALP").upper()
        requested_setup = self._value(scenario, "setup_type")
        passed: list[str] = []

        if mode not in {"SCALP", "SWING"}:
            return self._reject(mode, requested_setup, "REJECT_DATA_UNAVAILABLE", "UNKNOWN_TRADE_MODE", passed)
        if execution.get("closed_candle") is not True:
            return self._reject(mode, requested_setup, "REJECT_DATA_UNAVAILABLE", "CLOSED_CANDLE_REQUIRED", passed)
        passed.append("DATA_READY")

        if str(market.get("btc_guard", "PASS")).upper() != "PASS":
            return self._reject(mode, requested_setup, "REJECT_BTC_GUARD", "BTC_GUARD_FAILED", passed)
        passed.append("BTC_GUARD_PASS")

        prior_exit = metadata.get("prior_exit")
        same_context = bool(metadata.get("prior_context_fingerprint_same"))
        if prior_exit == "STOP_LOSS" and same_context and not structure.get("new_structure_after_prior_stop"):
            return self._reject(mode, requested_setup, "REJECT_REENTRY_LOCK", "SAME_CONTEXT_AFTER_STOP", passed)
        passed.append("REENTRY_CHECK")

        if mode == "SWING":
            return self._swing(market, structure, trigger, execution, risk, metadata, passed, requested_setup, same_context)
        return self._scalp(market, structure, trigger, execution, risk, metadata, passed, requested_setup, same_context)

    def _scalp(self, market, structure, trigger, execution, risk, metadata, passed, requested_setup, same_context):
        bearish = all(str(market.get(tf, "NEUTRAL")).upper() == "BEARISH" for tf in ("15m_bias", "1h_bias", "4h_bias"))
        weak_recovery = str(market.get("5m_bias", "")).upper() == "RECOVERY" and not trigger.get("confirmed_reversal")
        if bearish and weak_recovery:
            return self._reject("SCALP", requested_setup, "REJECT_COUNTERTREND", "WEAK_RECOVERY_AGAINST_HTF_BEARISH", passed)
        passed.append("REGIME_ALLOWED")
        if not (structure.get("location_at_support") or structure.get("location_pullback")):
            return self._reject("SCALP", requested_setup, "REJECT_NO_LOCATION", "NO_VALID_ENTRY_LOCATION", passed)
        passed.append("LOCATION_VALID")
        continuation = bool(structure.get("continuation_break") and structure.get("pullback_holds"))
        if not structure.get("selling_pressure_weakening") and not continuation:
            return self._reject("SCALP", requested_setup, "REJECT_NO_SELLER_FAILURE", "SELLER_PRESSURE_NOT_INVALIDATED", passed)
        passed.append("SELLER_FAILURE_OR_CONTINUATION")
        reversal = bool(structure.get("reclaim") and structure.get("higher_low") and trigger.get("confirmed_reversal"))
        if not (continuation or reversal):
            return self._reject("SCALP", requested_setup, "REJECT_NO_RECLAIM", "STRUCTURAL_RECLAIM_NOT_CONFIRMED", passed)
        passed.append("STRUCTURE_CONFIRMED")
        setup = "CONTINUATION" if continuation else "REVERSAL"
        return self._risk("SCALP", setup, trigger, execution, risk, metadata, passed, same_context, 1.0, 3.0, 1.0)

    def _swing(self, market, structure, trigger, execution, risk, metadata, passed, requested_setup, same_context):
        h1 = str(market.get("1h_bias", "NEUTRAL")).upper()
        h4 = str(market.get("4h_bias", "NEUTRAL")).upper()
        if h1 == "BEARISH" and h4 == "BEARISH":
            return self._reject("SWING", requested_setup, "REJECT_COUNTERTREND", "SWING_HIGHER_TIMEFRAMES_BEARISH", passed)
        passed.append("SWING_REGIME_ALLOWED")
        if not (structure.get("location_at_support") or structure.get("location_pullback")):
            return self._reject("SWING", requested_setup, "REJECT_NO_LOCATION", "NO_VALID_SWING_LOCATION", passed)
        passed.append("LOCATION_VALID")
        aligned = h1 == "BULLISH" or h4 == "BULLISH"
        continuation = bool(structure.get("continuation_break") and structure.get("pullback_holds"))
        reversal = bool(structure.get("higher_low") and structure.get("reclaim") and trigger.get("confirmed_reversal"))
        if not aligned or not (continuation or reversal):
            return self._reject("SWING", requested_setup, "REJECT_NO_RECLAIM", "SWING_STRUCTURE_OR_HTF_ALIGNMENT_MISSING", passed)
        passed.append("SWING_STRUCTURE_CONFIRMED")
        setup = "CONTINUATION" if continuation else "REVERSAL"
        return self._risk("SWING", setup, trigger, execution, risk, metadata, passed, same_context, 0.9, 5.0, 1.5)

    def _risk(self, mode, setup, trigger, execution, risk, metadata, passed, same_context, min_volume, max_stop, min_rr):
        if bool(trigger.get("overextended")):
            return self._reject(mode, setup, "REJECT_OVEREXTENDED", "ENTRY_TOO_FAR_FROM_VALID_LOCATION", passed)
        passed.append("EXTENSION_VALID")
        volume = self._float(trigger.get("volume_ratio_5m", 0.0))
        if volume < min_volume:
            return self._reject(mode, setup, "REJECT_NO_VOLUME_CONFIRM", "VOLUME_NOT_CONFIRMING", passed)
        passed.append("VOLUME_CONFIRMED")
        if self._float(execution.get("spread_percent", 0.0)) > self.MAX_SPREAD_PERCENT:
            return self._reject(mode, setup, "REJECT_DATA_UNAVAILABLE", "SPREAD_TOO_WIDE", passed)
        passed.append("EXECUTION_QUALITY")
        stop = self._float(risk.get("stop_distance_percent", 999.0))
        if stop <= 0 or stop > max_stop:
            return self._reject(mode, setup, "REJECT_STOP_TOO_WIDE", "STOP_DISTANCE_OUT_OF_RANGE", passed)
        passed.append("STOP_WIDTH_VALID")
        if risk.get("reward_risk") is None:
            target_status = str(risk.get("target_status", "")).upper()
            target_reason = {
                "NO_TARGET_ABOVE_ENTRY": "NO_TARGET_ABOVE_ENTRY",
                "NO_TARGET_MEETS_RR": "NO_TARGET_MEETS_RR",
            }.get(target_status)
            if target_reason:
                return self._reject(mode, setup, "REJECT_NO_VALID_TARGET", target_reason, passed)
            return self._reject(mode, setup, "REJECT_DATA_UNAVAILABLE", "REWARD_RISK_PENDING", passed)
        rr = self._float(risk.get("reward_risk"))
        if rr < min_rr:
            return self._reject(mode, setup, "REJECT_LOW_REWARD", "REWARD_RISK_TOO_LOW", passed)
        passed.append("REWARD_RISK_VALID")
        return EntryDecision(True, f"APPROVED_{mode}", mode, setup, passed_gates=tuple(passed), diagnostics={
            "legacy_score": metadata.get("legacy_score"),
            "legacy_score_used_as_gate": False,
            "volume_ratio_5m": volume,
            "stop_distance_percent": stop,
            "reward_risk": rr,
            "target_price": risk.get("target_price"),
            "target_source": risk.get("target_source"),
            "reentry_same_context": same_context,
            "lane_threshold": self.SCALP_SCORE_THRESHOLD if mode == "SCALP" else self.SWING_SCORE_THRESHOLD,
        })

    @staticmethod
    def _value(obj: Any, name: str, default: Any = None) -> Any:
        if isinstance(obj, Mapping):
            return obj.get(name, default)
        return getattr(obj, name, default)

    @classmethod
    def _mapping(cls, obj: Any, name: str) -> Mapping[str, Any]:
        value = cls._value(obj, name, {})
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _float(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _reject(mode, setup, decision, reason, passed):
        return EntryDecision(False, decision, mode, setup, reason, tuple(passed), (reason,), {"legacy_score_used_as_gate": False})


def evaluate_entry(scenario: Any) -> EntryDecision:
    return EntryEngineV2().evaluate(scenario)
