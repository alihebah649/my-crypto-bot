from trade_manager.history import PositionHistoryRecord, PositionHistoryRepository


def _record():
    return PositionHistoryRecord(
        position_id="pos-persist-1", symbol="BTCUSDT", side="LONG", quantity=1.0,
        entry_price=100.0, exit_price=101.0, stop_loss=98.0, take_profit=101.0,
        highest_price=101.0, lowest_price=99.0, max_profit_percent=1.0,
        max_drawdown_percent=-1.0, opened_at=1000.0, closed_at=1600.0,
        close_reason="TAKE_PROFIT", gross_pnl=1.0, realized_pnl=0.799,
        total_fees=0.201, entry_fee=0.1, exit_fee=0.101, holding_hours=1/6,
        roi_percent=0.799, entry_metadata={"score": 72, "mtf": {"5m": "bullish"}},
        exit_metadata={"exit_price": 101.0}, metadata={"multi_candle": {"5": "bullish"}},
    )


def test_position_history_survives_repository_reload(tmp_path):
    path = tmp_path / "position_history.json"
    first = PositionHistoryRepository(str(path))
    first.add_record(_record())

    second = PositionHistoryRepository(str(path))
    records = second.get_all_records()

    assert len(records) == 1
    record = records[0]
    assert record.position_id == "pos-persist-1"
    assert record.realized_pnl == 0.799
    assert record.entry_metadata["score"] == 72
    assert record.metadata["multi_candle"]["5"] == "bullish"


def test_position_history_upsert_does_not_duplicate_ids(tmp_path):
    path = tmp_path / "position_history.json"
    repo = PositionHistoryRepository(str(path))
    record = _record()
    repo.add_record(record)
    record.realized_pnl = 0.5
    repo.add_record(record)

    records = repo.get_all_records()
    assert len(records) == 1
    assert records[0].realized_pnl == 0.5
