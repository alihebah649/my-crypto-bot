from core.account_connection import AccountConnection, ConnectionState, CredentialReference
from core.account_registry import AccountRegistry, AccountRole, RegisteredAccount
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



def test_same_open_intent_is_idempotent_after_process_restart(tmp_path):
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0))

    adapter_path = tmp_path / "paper-account.json"
    position_path = tmp_path / "replica-state.json"

    adapter = PaperExecutionAdapter(
        initial_cash=350.0,
        fee_rate=0.001,
        state_path=str(adapter_path),
    )
    first_store = __import__("core.replica_position_state", fromlist=["ReplicaPositionStateStore"]).ReplicaPositionStateStore(
        str(position_path)
    )
    first_executor = PaperReplicaExecutor(
        {"user-20": adapter},
        position_store=first_store,
    )
    dispatcher = TradeReplicationDispatcher(registry)

    intent = MasterTradeIntent.open(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
        master_position_id="MASTER-RESTART-1",
        intent_id="INTENT-RESTART-1",
    )

    first = dispatcher.dispatch(intent, first_executor.execute)
    assert first.dispatched == 1
    assert adapter.balance.assets["BTCUSDT"] == 0.175

    restored_adapter = PaperExecutionAdapter(
        initial_cash=350.0,
        fee_rate=0.001,
        state_path=str(adapter_path),
    )
    restored_store = __import__("core.replica_position_state", fromlist=["ReplicaPositionStateStore"]).ReplicaPositionStateStore(
        str(position_path)
    )
    restored_executor = PaperReplicaExecutor(
        {"user-20": restored_adapter},
        position_store=restored_store,
    )

    retry = restored_executor.execute(first.instructions[0])
    assert retry is True
    # Orders are intentionally not restored by PaperExecutionAdapter; the
    # persisted account balance proves the original execution survived restart,
    # while the replica state makes the retry a safe no-op.
    assert len(restored_adapter.orders) == 0
    assert restored_adapter.balance.assets["BTCUSDT"] == 0.175



def test_same_close_intent_is_idempotent_after_process_restart(tmp_path):
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0))

    adapter_path = tmp_path / "paper-account.json"
    position_path = tmp_path / "replica-state.json"

    adapter = PaperExecutionAdapter(
        initial_cash=350.0,
        fee_rate=0.001,
        state_path=str(adapter_path),
    )
    store = __import__("core.replica_position_state", fromlist=["ReplicaPositionStateStore"]).ReplicaPositionStateStore(
        str(position_path)
    )
    executor = PaperReplicaExecutor({"user-20": adapter}, position_store=store)
    dispatcher = TradeReplicationDispatcher(registry)

    open_intent = MasterTradeIntent.open(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
        master_position_id="MASTER-CLOSE-RESTART",
        intent_id="INTENT-CLOSE-RESTART-OPEN",
    )
    assert dispatcher.dispatch(open_intent, executor.execute).dispatched == 1

    close_intent = MasterTradeIntent.close(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        reference_close_price=105.0,
        master_position_id="MASTER-CLOSE-RESTART",
        close_fraction=1.0,
        intent_id="INTENT-CLOSE-RESTART",
    )
    first_close = dispatcher.dispatch(close_intent, executor.execute)
    assert first_close.dispatched == 1

    restored_adapter = PaperExecutionAdapter(
        initial_cash=350.0,
        fee_rate=0.001,
        state_path=str(adapter_path),
    )
    restored_store = __import__("core.replica_position_state", fromlist=["ReplicaPositionStateStore"]).ReplicaPositionStateStore(
        str(position_path)
    )
    restored_executor = PaperReplicaExecutor(
        {"user-20": restored_adapter},
        position_store=restored_store,
    )

    retry = restored_executor.execute(first_close.instructions[0])
    assert retry is True
    assert restored_adapter.balance.assets.get("BTCUSDT", 0.0) == 0.0
