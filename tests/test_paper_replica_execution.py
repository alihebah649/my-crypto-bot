from core.account_connection import AccountConnection, ConnectionState, CredentialReference
from core.account_registry import AccountRegistry, AccountRole, RegisteredAccount
from core.replica_position_state import ReplicaPositionStateStore, ReplicaPositionStatus
from core.settlement_trading_policy import SettlementState, SettlementTradingPolicy
from core.execution_models import OrderSide, OrderStatus
from core.paper_execution_adapter import PaperExecutionAdapter
from core.paper_replica_executor import PaperReplicaExecutor
from core.replication_dispatcher import TradeReplicationDispatcher
from core.trade_replication import MasterTradeIntent


def _user(connection_id: str, capital: float):
    from core.execution_profile import AccountScope, ExecutionProfile

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
    return RegisteredAccount(connection, AccountRole.FOLLOWER, capital)


def test_one_master_intent_executes_to_multiple_independent_paper_accounts():
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0))
    registry.register(_user("user-21", 700.0))
    registry.register(_user("user-22", 2000.0))

    adapters = {
        "user-20": PaperExecutionAdapter(initial_cash=350.0, fee_rate=0.001),
        "user-21": PaperExecutionAdapter(initial_cash=700.0, fee_rate=0.001),
        "user-22": PaperExecutionAdapter(initial_cash=2000.0, fee_rate=0.001),
    }
    executor = PaperReplicaExecutor(adapters)
    dispatcher = TradeReplicationDispatcher(registry)

    intent = MasterTradeIntent.open(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
        stop_loss_price=98.0,
        trade_mode="SCALP",
        intent_id="INTENT-E2E-1",
    )

    result = dispatcher.dispatch(intent, executor.execute)

    assert result.planned == 3
    assert result.dispatched == 3
    assert result.failed == 0
    assert [x.target_quote_value for x in result.instructions] == [17.5, 35.0, 100.0]

    assert adapters["user-20"].balance.assets["BTCUSDT"] == 0.175
    assert adapters["user-21"].balance.assets["BTCUSDT"] == 0.35
    assert adapters["user-22"].balance.assets["BTCUSDT"] == 1.0

    # The dispatcher/executor use the price embedded in the shared intent.
    # No adapter market-price lookup is required.
    assert all(
        execution.result.status is OrderStatus.FILLED
        for execution in executor.executions
    )
    assert all(
        execution.result.requested_price == 100.0
        for execution in executor.executions
    )


def test_repeat_of_same_master_intent_does_not_duplicate_paper_orders():
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0))

    adapter = PaperExecutionAdapter(initial_cash=350.0, fee_rate=0.001)
    executor = PaperReplicaExecutor({"user-20": adapter})
    dispatcher = TradeReplicationDispatcher(registry)

    intent = MasterTradeIntent.open(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
        intent_id="INTENT-E2E-2",
    )

    first = dispatcher.dispatch(intent, executor.execute)
    second = dispatcher.dispatch(intent, executor.execute)

    assert first.dispatched == 1
    assert second.dispatched == 0
    assert second.skipped_duplicates == 1
    assert len(adapter.orders) == 1
    assert adapter.balance.assets["BTCUSDT"] == 0.175


def test_existing_position_closes_after_settlement_becomes_required():
    registry = AccountRegistry()
    account = _user("user-overdue", 350.0)
    registry.register(account)

    store = ReplicaPositionStateStore()
    adapter = PaperExecutionAdapter(initial_cash=350.0, fee_rate=0.001)
    executor = PaperReplicaExecutor({"user-overdue": adapter}, position_store=store)
    dispatcher = TradeReplicationDispatcher(registry)

    open_intent = MasterTradeIntent.open(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
        stop_loss_price=98.0,
        trade_mode="SCALP",
        intent_id="INTENT-LIFECYCLE-OPEN",
    )
    opened = dispatcher.dispatch(open_intent, executor.execute)

    assert opened.dispatched == 1
    position = store.active_for_account(
        connection_id="user-overdue",
        source_intent_id="INTENT-LIFECYCLE-OPEN",
    )
    assert position is not None
    assert position.remaining_quantity == 0.175
    assert position.status is ReplicaPositionStatus.OPEN

    # Payment becomes overdue after the position already exists.
    registry.replace(
        RegisteredAccount(
            connection=account.connection,
            role=account.role,
            capital_basis=account.capital_basis,
            copy_enabled=account.copy_enabled,
            settlement_policy=SettlementTradingPolicy(
                SettlementState.SETTLEMENT_REQUIRED
            ),
        )
    )

    close_intent = MasterTradeIntent.close(
        symbol="BTCUSDT",
        reference_capital=1000.0,
        close_fraction=1.0,
        reference_exit_price=110.0,
        source_position_intent_id="INTENT-LIFECYCLE-OPEN",
        trade_mode="SCALP",
        intent_id="INTENT-LIFECYCLE-CLOSE",
    )
    closed = dispatcher.dispatch(close_intent, executor.execute)

    assert closed.dispatched == 1
    assert closed.settlement_rejected == 0
    restored = store.get(position.position_id)
    assert restored is not None
    assert restored.remaining_quantity == 0.0
    assert restored.status is ReplicaPositionStatus.CLOSED
    assert adapter.balance.assets.get("BTCUSDT", 0.0) == 0.0
    assert adapter.balance.cash > 350.0
