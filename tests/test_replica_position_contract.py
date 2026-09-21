from pathlib import Path

from core.account_connection import AccountConnection, ConnectionState, CredentialReference
from core.account_execution_context import AccountExecutionContext
from core.account_registry import AccountRegistry, AccountRole, RegisteredAccount
from core.execution_models import OrderSide
from core.paper_execution_adapter import PaperExecutionAdapter
from core.paper_replica_executor import PaperReplicaExecutor
from core.replica_position_repository import ReplicaPositionRepository
from core.settlement_trading_policy import SettlementState, SettlementTradingPolicy
from core.trade_replication import MasterTradeIntent, TradeReplicationPlanner
from trade_manager.models import PositionStatus


def _account(connection_id: str, capital: float, settlement=SettlementState.CURRENT):
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


def _open_intent():
    return MasterTradeIntent.open(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=50.0,
        reference_entry_price=100.0,
        stop_loss_price=98.0,
        master_position_id="MASTER-POS-1",
        intent_id="OPEN-1",
    )


def test_open_creates_independent_replica_positions():
    adapters = {
        "u1": PaperExecutionAdapter(1000.0),
        "u2": PaperExecutionAdapter(700.0),
    }
    registry = AccountRegistry()
    registry.register(_account("u1", 350.0))
    registry.register(_account("u2", 700.0))
    repo = ReplicaPositionRepository()
    executor = PaperReplicaExecutor(adapters, repo)
    plans = TradeReplicationPlanner.plan(_open_intent(), registry.followers())

    assert executor.execute(plans[0]) is True
    assert executor.execute(plans[1]) is True
    positions = repo.get_by_master_position("MASTER-POS-1")
    assert len(positions) == 2
    assert {p.account_id for p in positions} == {"u1", "u2"}
    assert {p.quantity for p in positions} == {0.175, 0.35}
    assert all(p.status is PositionStatus.OPEN for p in positions)
    assert all(p.user_position_id != p.master_position_id for p in positions)


def test_replica_repository_survives_restart(tmp_path: Path):
    path = tmp_path / "replicas.json"
    repo = ReplicaPositionRepository(str(path))
    adapters = {"u1": PaperExecutionAdapter(1000.0)}
    executor = PaperReplicaExecutor(adapters, repo)
    executor.execute(TradeReplicationPlanner.plan(_open_intent(), [_account("u1", 350.0).as_follower()])[0])

    restored = ReplicaPositionRepository(str(path))
    positions = restored.get_by_master_position("MASTER-POS-1", "u1")
    assert len(positions) == 1
    assert positions[0].status is PositionStatus.OPEN
    assert positions[0].quantity == 0.175


def test_open_idempotency_is_preserved_by_delivery_and_position_identity():
    repo = ReplicaPositionRepository()
    adapters = {"u1": PaperExecutionAdapter(1000.0)}
    executor = PaperReplicaExecutor(adapters, repo)
    instruction = TradeReplicationPlanner.plan(_open_intent(), [_account("u1", 350.0).as_follower()])[0]

    assert executor.execute(instruction) is True
    assert executor.execute(instruction) is False
    assert len(repo.all()) == 1
    assert len(adapters["u1"].orders) == 1


def test_master_close_closes_all_linked_user_positions():
    adapters = {"u1": PaperExecutionAdapter(1000.0), "u2": PaperExecutionAdapter(1000.0)}
    registry = AccountRegistry()
    registry.register(_account("u1", 350.0))
    registry.register(_account("u2", 700.0))
    repo = ReplicaPositionRepository()
    executor = PaperReplicaExecutor(adapters, repo)

    open_plans = TradeReplicationPlanner.plan(_open_intent(), registry.followers())
    for plan in open_plans:
        assert executor.execute(plan) is True

    close = MasterTradeIntent.close(
        symbol="BTCUSDT",
        master_position_id="MASTER-POS-1",
        reference_close_price=105.0,
        intent_id="CLOSE-1",
    )
    close_plans = TradeReplicationPlanner.plan(close, registry.followers())
    for plan in close_plans:
        assert executor.execute(plan) is True

    positions = repo.get_by_master_position("MASTER-POS-1")
    assert all(p.status is PositionStatus.CLOSED for p in positions)
    assert all(p.close_intent_id == "CLOSE-1" for p in positions)


def test_settlement_required_blocks_open_but_does_not_block_close():
    account = _account("u1", 350.0, SettlementState.SETTLEMENT_REQUIRED)
    context = AccountExecutionContext.from_account(account)
    assert context.allows_replication_action(__import__("core.trade_replication", fromlist=["ReplicationAction"]).ReplicationAction.OPEN) is False
    assert context.allows_replication_action(__import__("core.trade_replication", fromlist=["ReplicationAction"]).ReplicationAction.CLOSE) is True


def test_one_failed_user_does_not_block_other_users():
    registry = AccountRegistry()
    registry.register(_account("u1", 350.0))
    registry.register(_account("u2", 700.0))
    from core.replication_dispatcher import TradeReplicationDispatcher
    calls = []
    dispatcher = TradeReplicationDispatcher(registry)
    result = dispatcher.dispatch(
        _open_intent(),
        lambda instruction: calls.append(instruction.connection_id) or instruction.connection_id == "u2",
    )
    assert result.failed == 1
    assert result.dispatched == 1
    assert calls == ["u1", "u2"]



def test_duplicate_master_close_does_not_repeat_user_close():
    adapters = {"u1": PaperExecutionAdapter(1000.0)}
    repo = ReplicaPositionRepository()
    executor = PaperReplicaExecutor(adapters, repo)
    follower = _account("u1", 350.0).as_follower()
    open_plan = TradeReplicationPlanner.plan(_open_intent(), [follower])[0]
    assert executor.execute(open_plan) is True

    close = MasterTradeIntent.close(
        symbol="BTCUSDT",
        master_position_id="MASTER-POS-1",
        reference_close_price=105.0,
        intent_id="CLOSE-1",
    )
    close_plan = TradeReplicationPlanner.plan(close, [follower])[0]
    assert executor.execute(close_plan) is True
    assert executor.execute(close_plan) is False
    assert len(repo.get_by_master_position("MASTER-POS-1", "u1")) == 1
