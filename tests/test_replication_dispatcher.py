from core.account_connection import AccountConnection, ConnectionState, CredentialReference
from core.account_registry import AccountRegistry, AccountRole, RegisteredAccount
from core.execution_models import OrderSide
from core.replication_delivery import DeliveryState
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


def _intent():
    return MasterTradeIntent.open(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
        stop_loss_price=98.0,
        trade_mode="SCALP",
        intent_id="INTENT-100",
    )


def test_dispatches_one_instruction_per_eligible_account():
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0))
    registry.register(_user("user-21", 700.0))

    received = []
    dispatcher = TradeReplicationDispatcher(registry)

    result = dispatcher.dispatch(
        _intent(),
        lambda instruction: received.append(instruction) or True,
    )

    assert result.planned == 2
    assert result.dispatched == 2
    assert result.failed == 0
    assert result.skipped_duplicates == 0
    assert [x.target_quote_value for x in received] == [17.5, 35.0]
    assert [x.reference_entry_price for x in received] == [100.0, 100.0]
    assert [x.stop_loss_price for x in received] == [98.0, 98.0]


def test_same_intent_is_not_dispatched_twice_after_completion():
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0))

    calls = []
    dispatcher = TradeReplicationDispatcher(registry)

    first = dispatcher.dispatch(_intent(), lambda instruction: calls.append(instruction) or True)
    second = dispatcher.dispatch(_intent(), lambda instruction: calls.append(instruction) or True)

    assert first.dispatched == 1
    assert second.dispatched == 0
    assert second.skipped_duplicates == 1
    assert len(calls) == 1


def test_failed_delivery_can_be_retried():
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0))

    dispatcher = TradeReplicationDispatcher(registry)
    calls = []

    first = dispatcher.dispatch(_intent(), lambda instruction: calls.append("first") or False)
    assert first.failed == 1

    second = dispatcher.dispatch(_intent(), lambda instruction: calls.append("second") or True)

    assert second.dispatched == 1
    assert second.skipped_duplicates == 0
    assert calls == ["first", "second"]

    record = dispatcher.ledger.get("INTENT-100:user-20:OPEN")
    assert record is not None
    assert record.state is DeliveryState.COMPLETED


def test_dispatcher_never_receives_market_data_or_credentials():
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0))

    dispatcher = TradeReplicationDispatcher(registry)
    seen = []

    dispatcher.dispatch(
        _intent(),
        lambda instruction: seen.append(instruction.metadata) or True,
    )

    assert seen[0]["market_data_scope"] == "SHARED"
    assert "api_key" not in seen[0]
    assert "api_secret" not in seen[0]



def test_settlement_required_blocks_open_but_allows_close_of_existing_position(tmp_path):
    from core.paper_execution_adapter import PaperExecutionAdapter
    from core.paper_replica_executor import PaperReplicaExecutor
    from core.replica_position_state import ReplicaPositionStateStore
    from core.settlement_trading_policy import SettlementState, SettlementTradingPolicy

    registry = AccountRegistry()
    current = _user("user-30", 350.0)
    registry.register(current)

    adapter = PaperExecutionAdapter(
        initial_cash=350.0,
        fee_rate=0.001,
        state_path=str(tmp_path / "paper-account.json"),
    )
    store = ReplicaPositionStateStore(str(tmp_path / "replica-state.json"))
    executor = PaperReplicaExecutor({"user-30": adapter}, position_store=store)
    dispatcher = TradeReplicationDispatcher(registry)

    open_intent = MasterTradeIntent.open(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
        stop_loss_price=98.0,
        trade_mode="SCALP",
        master_position_id="MASTER-SETTLEMENT-1",
        intent_id="INTENT-SETTLEMENT-OPEN",
    )
    opened = dispatcher.dispatch(open_intent, executor.execute)
    assert opened.dispatched == 1
    assert store.active_for_master_position(
        connection_id="user-30",
        master_position_id="MASTER-SETTLEMENT-1",
    ) is not None

    overdue = RegisteredAccount(
        current.connection,
        AccountRole.FOLLOWER,
        current.capital_basis,
        copy_enabled=True,
        settlement_policy=SettlementTradingPolicy(SettlementState.SETTLEMENT_REQUIRED),
    )
    registry.replace(overdue)

    blocked_open = dispatcher.dispatch(
        MasterTradeIntent.open(
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            reference_capital=1000.0,
            target_position_value=50.0,
            reference_entry_price=100.0,
            intent_id="INTENT-SETTLEMENT-NEW",
        ),
        executor.execute,
    )
    assert blocked_open.planned == 1
    assert blocked_open.settlement_rejected == 1
    assert blocked_open.dispatched == 0

    close_intent = MasterTradeIntent.close(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        reference_capital=1000.0,
        reference_close_price=105.0,
        master_position_id="MASTER-SETTLEMENT-1",
        close_fraction=1.0,
        intent_id="INTENT-SETTLEMENT-CLOSE",
    )
    closed = dispatcher.dispatch(close_intent, executor.execute)
    assert closed.dispatched == 1
    position = store.by_master_position(
        "MASTER-SETTLEMENT-1",
        "user-30",
    )[0]
    assert position.is_active is False
    from trade_manager.models import PositionStatus
    assert position.status is PositionStatus.CLOSED
    assert position.remaining_quantity == 0.0
    assert position.master_position_id == "MASTER-SETTLEMENT-1"
