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
