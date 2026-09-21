from core.account_connection import AccountConnection, ConnectionState, CredentialReference
from core.account_execution_context import AccountExecutionContext
from core.account_registry import AccountRegistry, AccountRole, RegisteredAccount
from core.execution_models import OrderSide
from core.execution_profile import AccountScope, ExecutionProfile
from core.settlement_trading_policy import SettlementState, SettlementTradingPolicy
from core.trade_replication import MasterTradeIntent


def _user(connection_id: str, capital: float, settlement_state: SettlementState):
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
        settlement_policy=SettlementTradingPolicy(settlement_state),
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
        intent_id="INTENT-SETTLE-OPEN",
    )


def test_context_exposes_settlement_entry_boundary():
    account = _user("user-overdue", 350.0, SettlementState.SETTLEMENT_REQUIRED)

    context = AccountExecutionContext.from_account(account)

    assert context.allow_new_entries is False
    assert context.manage_existing_positions is True
    assert context.force_close_existing_positions is False
    assert context.metadata()["settlement_state"] == "SETTLEMENT_REQUIRED"


def test_settlement_required_blocks_only_new_replication_entries():
    registry = AccountRegistry()
    registry.register(
        _user("user-overdue", 350.0, SettlementState.SETTLEMENT_REQUIRED)
    )

    calls = []
    dispatcher = __import__(
        "core.replication_dispatcher",
        fromlist=["TradeReplicationDispatcher"],
    ).TradeReplicationDispatcher(registry)

    result = dispatcher.dispatch(
        _open_intent(),
        lambda instruction: calls.append(instruction) or True,
    )

    assert result.planned == 1
    assert result.dispatched == 0
    assert result.settlement_rejected == 1
    assert calls == []
    assert dispatcher.ledger.get("INTENT-SETTLE-OPEN:user-overdue:OPEN") is None


def test_settled_account_allows_new_replication_entry_with_context_metadata():
    registry = AccountRegistry()
    registry.register(_user("user-current", 350.0, SettlementState.CURRENT))

    received = []
    from core.replication_dispatcher import TradeReplicationDispatcher

    result = TradeReplicationDispatcher(registry).dispatch(
        _open_intent(),
        lambda instruction: received.append(instruction) or True,
    )

    assert result.dispatched == 1
    metadata = received[0].metadata["account_execution_context"]
    assert metadata["settlement_state"] == "CURRENT"
    assert metadata["allow_new_entries"] is True


def test_settlement_required_does_not_block_close_replication():
    registry = AccountRegistry()
    registry.register(
        _user("user-overdue-close", 350.0, SettlementState.SETTLEMENT_REQUIRED)
    )

    close_intent = MasterTradeIntent.close(
        symbol="BTCUSDT",
        reference_capital=1000.0,
        close_fraction=1.0,
        trade_mode="SCALP",
        intent_id="INTENT-SETTLE-CLOSE",
    )

    received = []
    from core.replication_dispatcher import TradeReplicationDispatcher

    result = TradeReplicationDispatcher(registry).dispatch(
        close_intent,
        lambda instruction: received.append(instruction) or True,
    )

    assert result.planned == 1
    assert result.dispatched == 1
    assert result.settlement_rejected == 0
    assert received[0].action.value == "CLOSE"
    assert (
        received[0].metadata["account_execution_context"]["force_close_existing_positions"]
        is False
    )
