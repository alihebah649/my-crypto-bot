from types import SimpleNamespace

from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.repository import PositionRepository
from trade_manager.shadow_integration import ShadowMarketState, _PortfolioProvider


def _position(position_id: str, mode: str) -> Position:
    return Position(
        position_id=position_id,
        symbol=f"TST{position_id}USDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=1.0,
        entry_price=10.0,
        current_price=10.0,
        stop_loss=9.0,
        take_profit=None,
        entry_metadata={"trade_mode": mode},
    )


def test_portfolio_snapshot_counts_open_scalp_and_swing_lanes():
    repository = PositionRepository()
    for index in range(3):
        repository.add(_position(f"S{index}", "SCALP"))
    for index in range(2):
        repository.add(_position(f"W{index}", "SWING"))

    adapter = SimpleNamespace(balance=SimpleNamespace(cash=500.0, assets={}))
    market = ShadowMarketState()
    provider = _PortfolioProvider(adapter, repository, market)

    snapshot = provider.snapshot()

    assert snapshot.open_positions == 5
    assert snapshot.scalp_open_positions == 3
    assert snapshot.swing_open_positions == 2
