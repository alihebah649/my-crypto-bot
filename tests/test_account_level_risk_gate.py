from core.account_connection import AccountConnection, ConnectionState, CredentialReference
from core.account_registry import AccountRegistry, AccountRole, RegisteredAccount
from core.account_risk_gate import (
    AccountExecutionSnapshot,
    AccountLevelRiskGate,
    AccountRiskDecision,
    AccountRiskReason,
)
from core.execution_models import OrderSide
from core.trade_replication import ReplicaInstruction, ReplicationAction


def _user(connection_id: str, capital: float, *, enabled=True, state=ConnectionState.READY):
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
        state=state,
    )
    return RegisteredAccount(connection, AccountRole.FOLLOWER, capital, copy_enabled=enabled)


def _instruction(value: float) -> ReplicaInstruction:
    return ReplicaInstruction(
        intent_id="INTENT-1",
        connection_id="user-20",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        action=ReplicationAction.OPEN,
        target_quote_value=value,
        reference_entry_price=100.0,
    )


def test_gate_approves_within_authorized_capital_and_free_balance():
    result = AccountLevelRiskGate().evaluate(
        account=_user("user-20", 350.0),
        instruction=_instruction(17.5),
        snapshot=AccountExecutionSnapshot(
            account_equity=350.0,
            free_balance=350.0,
            estimated_fee=0.1,
        ),
    )

    assert result.decision is AccountRiskDecision.APPROVED
    assert result.reason is AccountRiskReason.APPROVED
    assert result.target_quote_value == 17.5


def test_gate_rejects_when_copy_value_exceeds_user_authorization():
    result = AccountLevelRiskGate().evaluate(
        account=_user("user-20", 20.0),
        instruction=_instruction(25.0),
        snapshot=AccountExecutionSnapshot(
            account_equity=100.0,
            free_balance=100.0,
        ),
    )

    assert result.decision is AccountRiskDecision.REJECTED
    assert result.reason is AccountRiskReason.TARGET_EXCEEDS_AUTHORIZED_CAPITAL


def test_gate_rejects_when_free_balance_is_insufficient_after_fee():
    result = AccountLevelRiskGate().evaluate(
        account=_user("user-20", 350.0),
        instruction=_instruction(17.5),
        snapshot=AccountExecutionSnapshot(
            account_equity=350.0,
            free_balance=17.5,
            estimated_fee=0.1,
        ),
    )

    assert result.decision is AccountRiskDecision.REJECTED
    assert result.reason is AccountRiskReason.INSUFFICIENT_FREE_BALANCE


def test_gate_rejects_disabled_or_disconnected_account():
    disabled = AccountLevelRiskGate().evaluate(
        account=_user("user-20", 350.0, enabled=False),
        instruction=_instruction(17.5),
        snapshot=AccountExecutionSnapshot(350.0, 350.0),
    )
    disconnected = AccountLevelRiskGate().evaluate(
        account=_user("user-21", 350.0, state=ConnectionState.DISCONNECTED),
        instruction=_instruction(17.5),
        snapshot=AccountExecutionSnapshot(350.0, 350.0),
    )

    assert disabled.reason is AccountRiskReason.ACCOUNT_NOT_ELIGIBLE
    assert disconnected.reason is AccountRiskReason.ACCOUNT_NOT_ELIGIBLE


def test_close_is_approved_without_open_allocation_check():
    instruction = ReplicaInstruction(
        intent_id="INTENT-CLOSE",
        connection_id="user-20",
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        action=ReplicationAction.CLOSE,
        close_fraction=1.0,
    )

    result = AccountLevelRiskGate().evaluate(
        account=_user("user-20", 350.0),
        instruction=instruction,
        snapshot=AccountExecutionSnapshot(350.0, 0.0),
    )

    assert result.decision is AccountRiskDecision.APPROVED
    assert result.reason is AccountRiskReason.APPROVED
