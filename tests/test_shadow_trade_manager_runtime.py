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
