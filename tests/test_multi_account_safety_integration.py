from __future__ import annotations

from core.account_connection import AccountConnection, ConnectionState, CredentialReference
from core.account_registry import AccountRegistry, AccountRole, RegisteredAccount
from core.binance_reconciliation import AccountLocalPositionView, ExchangeAsset, reconcile_account_spot_positions
from core.execution_models import OrderSide
from core.paper_execution_adapter import PaperExecutionAdapter
from core.paper_replica_executor import PaperReplicaExecutor
from core.replication_dispatcher import TradeReplicationDispatcher
from core.replica_position_state import ReplicaPositionStateStore
from core.settlement_trading_policy import SettlementState, SettlementTradingPolicy
from core.trade_replication import MasterTradeIntent


def user(connection_id: str, capital: float, settlement=SettlementState.CURRENT):
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
    return RegisteredAccount(
        connection,
        AccountRole.FOLLOWER,
        capital,
        settlement_policy=SettlementTradingPolicy(settlement),
    )


def local_view(record):
    return AccountLocalPositionView(
        account_id=record.connection_id,
        position_id=record.position_id,
        master_position_id=record.master_position_id,
        user_position_id=record.user_position_id,
        symbol=record.symbol,
        quantity=record.remaining_quantity,
        stop_price=record.stop_loss_price,
    )


def test_multi_account_restart_reconciliation_settlement_and_existing_close(tmp_path):
    registry = AccountRegistry()
    account_a = user("acct-a", 350.0)
    account_b = user("acct-b", 700.0)
    registry.register(account_a)
    registry.register(account_b)

    adapter_a_path = tmp_path / "account-a.json"
    adapter_b_path = tmp_path / "account-b.json"
    state_path = tmp_path / "replica-state.json"

    adapter_a = PaperExecutionAdapter(
        initial_cash=350.0,
        fee_rate=0.001,
        state_path=str(adapter_a_path),
    )
    adapter_b = PaperExecutionAdapter(
        initial_cash=700.0,
        fee_rate=0.001,
        state_path=str(adapter_b_path),
    )
    store = ReplicaPositionStateStore(str(state_path))
    executor = PaperReplicaExecutor(
        {"acct-a": adapter_a, "acct-b": adapter_b},
        position_store=store,
    )
    dispatcher = TradeReplicationDispatcher(registry)

    original_open = MasterTradeIntent.open(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
        stop_loss_price=98.0,
        trade_mode="SCALP",
        master_position_id="MASTER-ORIGINAL",
        intent_id="INTENT-ORIGINAL-OPEN",
    )
    first_open = dispatcher.dispatch(original_open, executor.execute)
    assert first_open.dispatched == 2

    # Simulate process restart: balances and canonical replica state restore.
    restored_adapter_a = PaperExecutionAdapter(
        initial_cash=350.0,
        fee_rate=0.001,
        state_path=str(adapter_a_path),
    )
    restored_adapter_b = PaperExecutionAdapter(
        initial_cash=700.0,
        fee_rate=0.001,
        state_path=str(adapter_b_path),
    )
    restored_store = ReplicaPositionStateStore(str(state_path))
    restored_executor = PaperReplicaExecutor(
        {"acct-a": restored_adapter_a, "acct-b": restored_adapter_b},
        position_store=restored_store,
    )

    pos_a = restored_store.active_for_master_position(
        connection_id="acct-a",
        master_position_id="MASTER-ORIGINAL",
    )
    pos_b = restored_store.active_for_master_position(
        connection_id="acct-b",
        master_position_id="MASTER-ORIGINAL",
    )
    assert pos_a is not None and pos_b is not None

    # Reconciliation is isolated per exchange account although both accounts
    # hold the same market symbol.
    rec_a = reconcile_account_spot_positions(
        "acct-a",
        [ExchangeAsset("BTCUSDT", pos_a.remaining_quantity)],
        [local_view(pos_a)],
        {pos_a.user_position_id: True},
    )
    rec_b = reconcile_account_spot_positions(
        "acct-b",
        [ExchangeAsset("BTCUSDT", pos_b.remaining_quantity)],
        [local_view(pos_b)],
        {pos_b.user_position_id: True},
    )
    assert rec_a.safe_to_resume is True
    assert rec_b.safe_to_resume is True

    # Account A becomes overdue. Only its NEW entries are blocked; account B
    # remains eligible for the same shared decision.
    registry.replace(user("acct-a", 350.0, SettlementState.SETTLEMENT_REQUIRED))
    registry.replace(user("acct-b", 700.0, SettlementState.CURRENT))

    new_open_result = TradeReplicationDispatcher(registry).dispatch(
        MasterTradeIntent.open(
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            reference_capital=1000.0,
            target_position_value=50.0,
            reference_entry_price=200.0,
            master_position_id="MASTER-NEW",
            intent_id="INTENT-NEW-OPEN",
        ),
        restored_executor.execute,
    )
    assert new_open_result.planned == 2
    assert new_open_result.settlement_rejected == 1
    assert new_open_result.dispatched == 1
    assert restored_store.active_for_master_position(
        connection_id="acct-a",
        master_position_id="MASTER-NEW",
    ) is None
    assert restored_store.active_for_master_position(
        connection_id="acct-b",
        master_position_id="MASTER-NEW",
    ) is not None

    # Existing BTC positions remain fully manageable and can close even for
    # the overdue account.
    close_intent = MasterTradeIntent.close(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        reference_capital=1000.0,
        reference_close_price=105.0,
        master_position_id="MASTER-ORIGINAL",
        close_fraction=1.0,
        intent_id="INTENT-ORIGINAL-CLOSE",
    )
    close_result = TradeReplicationDispatcher(registry).dispatch(
        close_intent,
        restored_executor.execute,
    )
    assert close_result.planned == 2
    assert close_result.dispatched == 2
    assert restored_store.active_for_master_position(
        connection_id="acct-a",
        master_position_id="MASTER-ORIGINAL",
    ) is None
    assert restored_store.active_for_master_position(
        connection_id="acct-b",
        master_position_id="MASTER-ORIGINAL",
    ) is None

    # DeliveryLedger is in-memory; persisted replica state is what makes an
    # identical CLOSE safe after another process restart.
    restart_store = ReplicaPositionStateStore(str(state_path))
    restart_executor = PaperReplicaExecutor(
        {
            "acct-a": PaperExecutionAdapter(
                initial_cash=350.0,
                fee_rate=0.001,
                state_path=str(adapter_a_path),
            ),
            "acct-b": PaperExecutionAdapter(
                initial_cash=700.0,
                fee_rate=0.001,
                state_path=str(adapter_b_path),
            ),
        },
        position_store=restart_store,
    )
    assert restart_executor.execute(close_result.instructions[0]) is True
    assert restart_executor.execute(close_result.instructions[1]) is True
