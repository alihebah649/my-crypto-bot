from core.account_connection import AccountConnection, ConnectionState, CredentialReference
from core.account_registry import AccountRegistry, AccountRole, RegisteredAccount
from core.account_risk_gate import AccountExecutionSnapshot, AccountLevelRiskGate
from core.execution_models import OrderSide
from core.replication_dispatcher import TradeReplicationDispatcher
from core.trade_replication import MasterTradeIntent


def _user(connection_id: str, capital: float, *, state=ConnectionState.READY):
    from core.execution_profile import AccountScope, ExecutionProfile

    profile = ExecutionProfile(
        profile_id=connection_id,
        exchange="BINANCE",
        account_scope=AccountScope.USER_SPOT,
        account_ref=connection_id,
        live_enabled=False,
    )
    return RegisteredAccount(
        AccountConnection(
            connection_id=connection_id,
            profile=profile,
            credential=CredentialReference(f"vault://binance/{connection_id}"),
            state=state,
        ),
        AccountRole.FOLLOWER,
        capital,
    )


class StaticAccountStateProvider:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def snapshot(self, account):
        return self.snapshots[account.connection.connection_id]


def _intent(value=50.0):
    return MasterTradeIntent.open(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        reference_capital=1000.0,
        target_position_value=value,
        reference_entry_price=100.0,
        intent_id="INTENT-RISK-1",
    )


def test_dispatcher_rejects_one_user_without_blocking_other_users():
    registry = AccountRegistry()
    registry.register(_user("user-20", 350.0))
    registry.register(_user("user-21", 20.0))

    provider = StaticAccountStateProvider({
        "user-20": AccountExecutionSnapshot(350.0, 350.0),
        "user-21": AccountExecutionSnapshot(20.0, 5.0),
    })
    dispatcher = TradeReplicationDispatcher(
        registry,
        risk_gate=AccountLevelRiskGate(),
        account_state_provider=provider,
    )

    received = []
    result = dispatcher.dispatch(_intent(), lambda instruction: received.append(instruction) or True)

    assert result.planned == 2
    assert result.risk_rejected == 1
    assert result.dispatched == 1
    assert [x.connection_id for x in received] == ["user-20"]


def test_dispatcher_rejects_when_user_authorized_capital_is_below_replica_value():
    registry = AccountRegistry()
    registry.register(_user("user-20", 10.0))

    provider = StaticAccountStateProvider({
        "user-20": AccountExecutionSnapshot(100.0, 100.0),
    })
    dispatcher = TradeReplicationDispatcher(
        registry,
        risk_gate=AccountLevelRiskGate(),
        account_state_provider=provider,
    )

    calls = []
    result = dispatcher.dispatch(_intent(50.0), lambda instruction: calls.append(instruction) or True)

    assert result.risk_rejected == 1
    assert result.dispatched == 0
    assert calls == []


def test_dispatcher_requires_risk_gate_and_snapshot_provider_as_a_pair():
    registry = AccountRegistry()

    try:
        TradeReplicationDispatcher(registry, risk_gate=AccountLevelRiskGate())
    except ValueError as exc:
        assert "supplied together" in str(exc)
    else:
        raise AssertionError("expected ValueError")
