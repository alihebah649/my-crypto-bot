import pytest

from trade_manager.controller import PositionController
from trade_manager.history import PositionHistoryService
from trade_manager.models import Position, PositionSide, PositionStatus
from trade_manager.risk_manager import PositionExitDecision, PositionExitReason


class _Outcome:
    success = True
    executed_quantity = 1.0
    average_price = 101.0
    commission = 0.101
    exchange_order_id = "paper-sell-1"
    metadata = {}


class _Gateway:
    def close_spot(self, **kwargs):
        return _Outcome()


class _Risk:
    def evaluate(self, position):
        return PositionExitDecision(
            should_exit=True,
            reason=PositionExitReason.TAKE_PROFIT,
            exit_price=101.0,
            message="test exit",
        )


class _Repository:
    def __init__(self):
        self.positions = {}

    def add(self, position):
        self.positions[position.position_id] = position

    def update(self, position):
        self.positions[position.position_id] = position

    def get(self, position_id):
        return self.positions.get(position_id)

    def get_all(self):
        return list(self.positions.values())

    def get_open_positions(self):
        return [p for p in self.positions.values() if p.status in {PositionStatus.OPEN, PositionStatus.HOLD}]

    def get_by_symbol(self, symbol):
        return [p for p in self.positions.values() if p.symbol == symbol]


class _Calculator:
    def break_even_price(self, position):
        return position.entry_price

    def calculate(self, position, exit_price):
        class Result:
            gross_pnl = 1.0
            entry_fee = 0.1
            exit_fee = 0.101
        return Result()


def test_closed_position_is_archived_with_entry_and_exit_metadata():
    repo = _Repository()
    history = PositionHistoryService()
    controller = PositionController(_Risk(), repo, _Gateway(), history_service=history)

    position = Position(
        position_id="pos-1",
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        status=PositionStatus.OPEN,
        quantity=1.0,
        entry_price=100.0,
        current_price=100.0,
        stop_loss=98.0,
        take_profit=101.0,
        entry_metadata={"score": 72, "mtf": {"5m": "bullish", "15m": "bullish"}},
        metadata={"multi_candle": {"3": "bullish", "5": "bullish"}},
    )
    repo.add(position)

    decision = PositionExitDecision(True, PositionExitReason.TAKE_PROFIT, 101.0, "test exit")
    controller.execute_exit_decision("pos-1", decision, _Calculator())

    records = history.repository.get_all_records()
    assert len(records) == 1
    record = records[0]
    assert record.position_id == "pos-1"
    assert record.entry_metadata["score"] == 72
    assert record.metadata["multi_candle"]["5"] == "bullish"
    assert record.exit_metadata["exit_price"] == 101.0
    assert record.realized_pnl == pytest.approx(0.799)


def test_failed_exit_does_not_archive_position():
    class FailedGateway:
        def close_spot(self, **kwargs):
            class Outcome:
                success = False
                executed_quantity = 0.0
                average_price = 0.0
                commission = 0.0
                exchange_order_id = None
                metadata = {}
            return Outcome()

    repo = _Repository()
    history = PositionHistoryService()
    controller = PositionController(_Risk(), repo, FailedGateway(), history_service=history)
    position = Position(
        position_id="pos-2", symbol="BTCUSDT", side=PositionSide.LONG,
        status=PositionStatus.OPEN, quantity=1.0, entry_price=100.0,
        current_price=100.0, stop_loss=98.0, take_profit=101.0,
    )
    repo.add(position)
    decision = PositionExitDecision(True, PositionExitReason.TAKE_PROFIT, 101.0, "test exit")
    controller.execute_exit_decision("pos-2", decision, _Calculator())

    assert repo.get("pos-2").status == PositionStatus.OPEN
    assert history.repository.get_all_records() == []
