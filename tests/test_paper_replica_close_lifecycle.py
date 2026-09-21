from core.account_connection import AccountConnection, ConnectionState, CredentialReference
from core.account_registry import AccountRegistry, AccountRole, RegisteredAccount
from core.execution_models import OrderSide, OrderStatus
from core.execution_profile import AccountScope, ExecutionProfile
from core.paper_execution_adapter import PaperExecutionAdapter
from core.paper_replica_executor import PaperReplicaExecutor
from core.replica_position_state import ReplicaPositionStateStore, ReplicaPositionStatus
from core.replication_dispatcher import TradeReplicationDispatcher
from core.settlement_trading_policy import SettlementState, SettlementTradingPolicy
from core.trade_replication import MasterTradeIntent


def _user(connection_id: str, capital: float, settlement: SettlementState):
    profile = ExecutionProfile(
        profile_id=connection_id,
        exchange="BINANCE",
        account_scope=AccountScope.USER_SPOT,
        account_ref=connection_id,
        live_enabled=False,
    )
    connection = AccountConnection(
        connection_id=connection_id,
        profile=profile,
        credential=CredentialReference(f"vault://binance/{connection_id}"),
        state=ConnectionState.READY,
    )
    return RegisteredAccount(
        connection=connection,
        role=AccountRole.FOLLOWER,
        capital_basis=capital,
        settlement_policy=SettlementTradingPolicy(settlement),
    )


def _open_intent():
    return MasterTradeIntent.open(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
        stop_loss_price=98.0,
        trade_mode="SCALP",
        intent_id="INTENT-OPEN-LIFECYCLE",
    )


def test_master_open_then_close_updates_each_account_position_independently():
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0, SettlementState.CURRENT))
    registry.register(_user("user-21", 700.0, SettlementState.CURRENT))

    adapters = {
        "user-20": PaperExecutionAdapter(initial_cash=350.0, fee_rate=0.001),
        "user-21": PaperExecutionAdapter(initial_cash=700.0, fee_rate=0.001),
    }
    positions = ReplicaPositionStateStore()
    executor = PaperReplicaExecutor(adapters, position_store=positions)
    dispatcher = TradeReplicationDispatcher(registry)

    opened = dispatcher.dispatch(_open_intent(), executor.execute)
    assert opened.dispatched == 2
    assert positions.active_for_account(
        connection_id="user-20",
        source_intent_id="INTENT-OPEN-LIFECYCLE",
    ) is not None

    close_intent = MasterTradeIntent.close(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        reference_exit_price=105.0,
        source_open_intent_id="INTENT-OPEN-LIFECYCLE",
        close_fraction=1.0,
        trade_mode="SCALP",
        intent_id="INTENT-CLOSE-LIFECYCLE",
    )
    closed = dispatcher.dispatch(close_intent, executor.execute)

    assert closed.planned == 2
    assert closed.dispatched == 2
    assert all(
        execution.result.status is OrderStatus.FILLED
        for execution in executor.executions[-2:]
    )
    assert positions.active_for_account(
        connection_id="user-20",
        source_intent_id="INTENT-OPEN-LIFECYCLE",
    ) is None
    assert positions.active_for_account(
        connection_id="user-21",
        source_intent_id="INTENT-OPEN-LIFECYCLE",
    ) is None
    assert adapters["user-20"].balance.assets.get("BTCUSDT", 0.0) == 0.0
    assert adapters["user-21"].balance.assets.get("BTCUSDT", 0.0) == 0.0


def test_partial_master_close_uses_each_account_remaining_quantity():
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0, SettlementState.CURRENT))

    adapter = PaperExecutionAdapter(initial_cash=350.0, fee_rate=0.001)
    positions = ReplicaPositionStateStore()
    executor = PaperReplicaExecutor(
        {"user-20": adapter},
        position_store=positions,
    )
    dispatcher = TradeReplicationDispatcher(registry)

    assert dispatcher.dispatch(_open_intent(), executor.execute).dispatched == 1

    close_intent = MasterTradeIntent.close(
        symbol="BTCUSDT",
        reference_exit_price=102.0,
        source_open_intent_id="INTENT-OPEN-LIFECYCLE",
        close_fraction=0.5,
        intent_id="INTENT-PARTIAL-CLOSE",
    )
    result = dispatcher.dispatch(close_intent, executor.execute)

    assert result.dispatched == 1
    position = positions.by_source_intent("INTENT-OPEN-LIFECYCLE")[0]
    assert position.status is ReplicaPositionStatus.PARTIALLY_CLOSED
    assert position.remaining_quantity == 0.0875
    assert adapter.balance.assets["BTCUSDT"] == 0.0875


def test_settlement_required_user_can_still_close_existing_replica_position():
    registry = AccountRegistry()
    registry.register(_user("user-overdue", 350.0, SettlementState.SETTLEMENT_REQUIRED))

    adapter = PaperExecutionAdapter(initial_cash=350.0, fee_rate=0.001)
    positions = ReplicaPositionStateStore()
    executor = PaperReplicaExecutor(
        {"user-overdue": adapter},
        position_store=positions,
    )
    dispatcher = TradeReplicationDispatcher(registry)

    assert dispatcher.dispatch(_open_intent(), executor.execute).dispatched == 1

    close_intent = MasterTradeIntent.close(
        symbol="BTCUSDT",
        reference_exit_price=105.0,
        source_open_intent_id="INTENT-OPEN-LIFECYCLE",
        intent_id="INTENT-OVERDUE-CLOSE",
    )
    result = dispatcher.dispatch(close_intent, executor.execute)

    assert result.dispatched == 1
    assert result.settlement_rejected == 0
    assert positions.by_source_intent("INTENT-OPEN-LIFECYCLE")[0].status is ReplicaPositionStatus.CLOSED


def test_close_is_fail_closed_without_tracked_position():
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0, SettlementState.CURRENT))

    positions = ReplicaPositionStateStore()
    executor = PaperReplicaExecutor(
        {"user-20": PaperExecutionAdapter(initial_cash=350.0)},
        position_store=positions,
    )
    dispatcher = TradeReplicationDispatcher(registry)

    close_intent = MasterTradeIntent.close(
        symbol="BTCUSDT",
        reference_exit_price=105.0,
        source_open_intent_id="MISSING-OPEN",
        intent_id="INTENT-MISSING-CLOSE",
    )
    result = dispatcher.dispatch(close_intent, executor.execute)

    assert result.dispatched == 0
    assert result.failed == 1


def test_existing_deterministic_replica_position_prevents_duplicate_open():
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0, SettlementState.CURRENT))

    adapter = PaperExecutionAdapter(initial_cash=350.0, fee_rate=0.001)
    positions = ReplicaPositionStateStore()
    executor = PaperReplicaExecutor({"user-20": adapter}, position_store=positions)
    dispatcher = TradeReplicationDispatcher(registry)

    first = dispatcher.dispatch(_open_intent(), executor.execute)
    second = dispatcher.dispatch(_open_intent(), executor.execute)

    assert first.dispatched == 1
    assert second.skipped_duplicates == 1
    assert len(adapter.orders) == 1
    assert len(positions.by_source_intent("INTENT-OPEN-LIFECYCLE")) == 1
