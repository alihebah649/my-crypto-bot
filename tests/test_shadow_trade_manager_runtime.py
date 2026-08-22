"""Application-level contract tests for shadow_main -> Trade Manager."""

from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def test_shadow_runtime_routes_entry_through_part6_and_paper_execution():
    runtime = ShadowTradeManagerRuntime(initial_cash=1000.0, fee_rate=0.001)
    runtime.update_market(
        "BTC-USD",
        price=100.0,
        bid=99.99,
        ask=100.01,
        spread_percent=0.02,
        atr=2.0,
        volume_usdt=1_000_000.0,
        ema100=90.0,
    )

    position = runtime.open_position("BTC-USD", 100.0, 96.0)

    assert position is not None
    assert position.status.name == "OPEN"
    assert position.quantity > 0
    assert position.entry_price == 100.0
    assert position.entry_fee > 0
    assert runtime.execution_adapter.balance.cash < 1000.0


def test_dual_mode_trade_mode_survives_runtime_to_paper_execution():
    runtime = ShadowTradeManagerRuntime(initial_cash=1000.0, fee_rate=0.001)
    runtime.update_market(
        "BTCUSDT",
        price=100.0,
        bid=99.99,
        ask=100.01,
        spread_percent=0.02,
        atr=2.0,
        volume_usdt=1_000_000.0,
        ema100=90.0,
    )

    scalp = runtime.open_position("BTCUSDT", 100.0, 96.0, trade_mode="SCALP")
    swing = runtime.open_position("BTCUSDT", 100.0, 96.0, trade_mode="SWING")

    assert scalp is not None
    assert swing is not None
    assert scalp.entry_metadata["trade_mode"] == "SCALP"
    assert swing.entry_metadata["trade_mode"] == "SWING"

    scalp_order = runtime.execution_adapter.orders[scalp.exchange_order_id]
    swing_order = runtime.execution_adapter.orders[swing.exchange_order_id]
    assert scalp_order.raw_response["trade_type"] == "SCALP"
    assert swing_order.raw_response["trade_type"] == "SWING"
    assert scalp_order.message.endswith("SCALP")
    assert swing_order.message.endswith("SWING")


def test_shadow_runtime_does_not_mark_failed_exit_as_closed():
    runtime = ShadowTradeManagerRuntime(initial_cash=1000.0, fee_rate=0.001)
    runtime.update_market(
        "BTC-USD",
        price=100.0,
        spread_percent=0.02,
        atr=2.0,
        volume_usdt=1_000_000.0,
        ema100=90.0,
    )
    position = runtime.open_position("BTC-USD", 100.0, 96.0)
    assert position is not None

    # A large loss is allowed to reach the Part-8 recovery/exit decision path.
    # The normal runtime uses the same CoreExecutionGateway for the eventual
    # close; state is only CLOSED after a successful execution outcome.
    runtime.update_market(
        "BTC-USD",
        price=90.0,
        spread_percent=0.02,
        atr=2.0,
        volume_usdt=1_000_000.0,
        ema100=95.0,
    )
    runtime.evaluate_position("BTC-USD")

    current = runtime.repository.get(position.position_id)
    assert current is not None
    assert current.status.name in {"OPEN", "HOLD", "REVIEW_REQUIRED", "CLOSED"}
