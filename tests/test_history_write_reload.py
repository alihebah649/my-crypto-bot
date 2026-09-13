from trade_manager.history import PositionHistoryService
from trade_manager.models import Position, PositionCloseReason, PositionSide, PositionStatus


def test_closed_position_history_survives_runtime_reload(tmp_path):
    persistence_dir = str(tmp_path)
    service = PositionHistoryService(persistence_dir=persistence_dir)

    position = Position(
        position_id="POS-HISTORY-RELOAD",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.CLOSED,
        quantity=0.001,
        entry_price=100.0,
        current_price=101.0,
        stop_loss=99.0,
        take_profit=102.0,
        opened_at=1000.0,
        closed_at=1100.0,
        close_reason=PositionCloseReason.TAKE_PROFIT,
        gross_pnl=0.001,
        realized_pnl=0.0008,
        total_fees=0.0002,
        entry_fee=0.0001,
        exit_fee=0.0001,
        entry_metadata={"trade_mode": "SCALP"},
    )

    service.record_closed_position(position)

    reloaded = PositionHistoryService(persistence_dir=persistence_dir)
    records = reloaded.repository.get_all_records()

    assert len(records) == 1
    record = records[0]
    assert record.position_id == "POS-HISTORY-RELOAD"
    assert record.symbol == "BTCUSDT"
    assert record.realized_pnl == 0.0008
    assert record.total_fees == 0.0002
    assert record.close_reason == "TAKE_PROFIT"
    assert record.entry_metadata["trade_mode"] == "SCALP"
