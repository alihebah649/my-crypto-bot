from pathlib import Path

from trade_manager.history import PositionHistoryRepository, PositionHistoryService
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.shadow_integration import ShadowTradeManagerRuntime


def test_runtime_uses_paper_persistence_dir_for_position_history(tmp_path):
    runtime = ShadowTradeManagerRuntime(
        initial_cash=1000.0,
        fee_rate=0.001,
        persistence_dir=str(tmp_path),
    )

    assert Path(runtime.repository.persistence_path) == tmp_path / "positions.json"
    assert Path(runtime.execution_adapter.state_path) == tmp_path / "paper_account.json"
    assert Path(runtime.facade.history_service.repository.path) == tmp_path / "position_history.json"

    position = Position(
        position_id="POS-history-path",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.CLOSED,
        quantity=0.01,
        entry_price=100.0,
        current_price=99.0,
        stop_loss=95.0,
        take_profit=None,
        entry_metadata={"trade_mode": "SCALP"},
        realized_pnl=-0.01,
        gross_pnl=-0.009,
        total_fees=0.001,
        entry_fee=0.0005,
        exit_fee=0.0005,
    )
    runtime.facade.history_service.record_closed_position(position)

    assert (tmp_path / "position_history.json").exists()
    reloaded = PositionHistoryService(
        repository=PositionHistoryRepository(str(tmp_path / "position_history.json"))
    ).get_all_closed_positions()
    assert len(reloaded) == 1
    assert reloaded[0].position_id == "POS-history-path"
    assert reloaded[0].entry_metadata["trade_mode"] == "SCALP"
