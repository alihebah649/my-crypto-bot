from core.execution_models import OrderSide
from core.trade_replication import (
    FollowerAccount,
    MasterTradeIntent,
    ReplicationAction,
    TradeReplicationPlanner,
)


def test_open_intent_scales_by_follower_capital():
    intent = MasterTradeIntent.open(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
        trade_mode="SCALP",
        intent_id="INTENT-1",
    )
    followers = [
        FollowerAccount("user-20", 350.0),
        FollowerAccount("user-21", 700.0),
    ]

    plans = TradeReplicationPlanner.plan(intent, followers)

    assert [p.target_quote_value for p in plans] == [17.5, 35.0]
    assert all(p.intent_id == "INTENT-1" for p in plans)
    assert all(p.metadata["market_data_scope"] == "SHARED" for p in plans)


def test_disabled_follower_is_not_planned():
    intent = MasterTradeIntent.open(
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
    )

    plans = TradeReplicationPlanner.plan(
        intent,
        [
            FollowerAccount("active", 350.0),
            FollowerAccount("disabled", 350.0, enabled=False),
        ],
    )

    assert [p.connection_id for p in plans] == ["active"]


def test_close_intent_copies_fraction_not_master_quantity():
    intent = MasterTradeIntent.close(
        symbol="SOLUSDT",
        close_fraction=1.0,
        intent_id="INTENT-CLOSE",
    )

    plans = TradeReplicationPlanner.plan(
        intent,
        [
            FollowerAccount("user-1", 350.0),
            FollowerAccount("user-2", 5000.0),
        ],
    )

    assert len(plans) == 2
    assert all(p.action is ReplicationAction.CLOSE for p in plans)
    assert all(p.close_fraction == 1.0 for p in plans)
    assert all(p.target_quote_value == 0.0 for p in plans)


def test_planner_does_not_need_market_data_or_exchange_adapter():
    intent = MasterTradeIntent.open(
        symbol="BNBUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
    )

    plans = TradeReplicationPlanner.plan(
        intent, [FollowerAccount("user-1", 350.0)]
    )

    assert len(plans) == 1
    assert plans[0].symbol == "BNBUSDT"
    assert plans[0].reference_entry_price == 100.0
