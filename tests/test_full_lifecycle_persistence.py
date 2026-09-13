from trade_manager.risk_manager import PositionExitDecision, PositionExitReason
from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def test_full_closed_lifecycle_persists_and_reloads(tmp_path):
    runtime = ShadowTradeManagerRuntime(initial_cash=1000.0, persistence_dir=str(tmp_path))
    position = runtime.facade.open_position(
        symbol="BTCUSDT",
        quantity=0.001,
        entry_price=100.0,
        stop_loss=99.0,
        take_profit=102.0,
        account_equity=1000.0,
        free_balance=1000.0,
        entry_metadata={"trade_mode": "SCALP"},
    )

    assert position is not None
    position_id = position.position_id

    decision = PositionExitDecision(
        should_exit=True,
        reason=PositionExitReason.TAKE_PROFIT,
        exit_price=101.0,
        message="test take profit",
    )
    closed = runtime.facade.execute_decision(position_id, decision)

    assert closed is not None
    assert closed.position_id == position_id
    assert closed.status.name == "CLOSED"
    assert closed.close_reason.name == "TAKE_PROFIT"
    assert closed.metadata["exit_decision_trace"]["execution_outcome"] == "CLOSED"

    reloaded = ShadowTradeManagerRuntime(initial_cash=1000.0, persistence_dir=str(tmp_path))
    persisted = reloaded.repository.get(position_id)
    history = reloaded.facade.history_service.repository.get_all_records()

    assert persisted is not None
    assert persisted.position_id == position_id
    assert persisted.status.name == "CLOSED"
    assert len(history) == 1
    assert history[0].position_id == position_id
    assert history[0].close_reason == "TAKE_PROFIT"
    assert history[0].realized_pnl == closed.realized_pnl
    assert history[0].total_fees == closed.total_fees
