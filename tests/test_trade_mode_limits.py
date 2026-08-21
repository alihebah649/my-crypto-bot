"""Paper Trading coverage for independent SCALP/SWING position limits."""
from trade_manager.shadow_integration import ShadowTradeManagerRuntime
from trade_manager.models import PositionStatus


def _runtime() -> ShadowTradeManagerRuntime:
    return ShadowTradeManagerRuntime(initial_cash=2000.0, fee_rate=0.001)


def _market(runtime, symbol: str) -> None:
    runtime.update_market(
        symbol,
        price=100.0,
        bid=99.99,
        ask=100.01,
        spread_percent=0.02,
        atr=2.0,
        volume_usdt=1_000_000.0,
        volatility=0.02,
        ema100=90.0,
    )


def _open(runtime, symbol: str, mode: str):
    _market(runtime, symbol)
    return runtime.open_position(symbol, 100.0, 96.0, trade_mode=mode)


def test_scalp_limit_is_15_and_swing_limit_is_10_independently():
    runtime = _runtime()

    scalp_positions = [_open(runtime, f"S{i}USDT", "SCALP") for i in range(15)]
    swing_positions = [_open(runtime, f"W{i}USDT", "SWING") for i in range(10)]

    assert all(position is not None for position in scalp_positions)
    assert all(position is not None for position in swing_positions)
    assert sum(p.status in {PositionStatus.OPEN, PositionStatus.HOLD, PositionStatus.REVIEW_REQUIRED} for p in runtime.repository.get_all()) == 25

    assert _open(runtime, "S15USDT", "SCALP") is None
    assert runtime.last_entry_diagnostics["S15USDT"]["risk_reason"] == "MAX_OPEN_SCALP_POSITIONS"

    assert _open(runtime, "W10USDT", "SWING") is None
    assert runtime.last_entry_diagnostics["W10USDT"]["risk_reason"] == "MAX_OPEN_SWING_POSITIONS"


def test_buy_position_persists_trade_mode_for_telegram_and_diagnostics():
    runtime = _runtime()
    scalp = _open(runtime, "BTCUSDT", "SCALP")
    swing = _open(runtime, "ETHUSDT", "SWING")

    assert scalp is not None and scalp.entry_metadata["trade_mode"] == "SCALP"
    assert swing is not None and swing.entry_metadata["trade_mode"] == "SWING"
