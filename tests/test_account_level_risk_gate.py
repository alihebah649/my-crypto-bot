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




# Correlation wiring regression coverage
from types import SimpleNamespace
import pytest

from trade_manager.core_risk_gateway import CoreRiskGateway
from trade_manager.core_risk_providers import KlineCorrelationProvider
from trade_manager.integration_contracts import RiskSizingRequest
from trade_manager.models import PositionStatus
from trade_manager.part6_risk import MarketContext, PortfolioSnapshot, RiskConfig, RiskController, SymbolExposure, PositionSizeCalculator


class _CorrelationPortfolio:
    def snapshot(self):
        return PortfolioSnapshot(1000.0, 1000.0, 0.0, 1000.0, 0.0, 0.0, 0.0, 0.0, 0)


class _CorrelationMarket:
    def get_context(self, symbol):
        return MarketContext(symbol, 100.0, 100.0, 100.0, 0.0, 1.0, 1_000_000.0, 0.01, 1000.0)


class _CorrelationExposure:
    def get_exposure(self, symbol):
        return SymbolExposure(symbol, 0.0, 0, 0.0, 0.0, ())


class _CorrelationScore:
    def __init__(self, score):
        self.score = score

    def get_score(self, symbol):
        return self.score


def _correlation_gateway(score):
    config = RiskConfig()
    return CoreRiskGateway(
        controller=RiskController(config),
        position_sizer=PositionSizeCalculator(config),
        portfolio_provider=_CorrelationPortfolio(),
        market_provider=_CorrelationMarket(),
        exposure_provider=_CorrelationExposure(),
        correlation_provider=_CorrelationScore(score),
    )


def test_part6_gateway_rejects_when_existing_correlation_is_above_limit():
    approval = _correlation_gateway(0.85).approve(
        RiskSizingRequest("ETHUSDT", 100.0, 98.0, 1000.0, 1000.0, trade_mode="SCALP")
    )
    assert approval.approved is False
    assert approval.reason == "CORRELATION_LIMIT"
    assert approval.metadata["correlation_score"] == pytest.approx(0.85)


def test_part6_gateway_preserves_existing_boundary_at_exact_limit():
    approval = _correlation_gateway(0.80).approve(
        RiskSizingRequest("ETHUSDT", 100.0, 98.0, 1000.0, 1000.0, trade_mode="SCALP")
    )
    assert approval.approved is True
    assert approval.metadata["correlation_score"] == pytest.approx(0.80)


def _correlation_rows(values):
    return [{"open_time": i, "close": float(v)} for i, v in enumerate(values, start=1)]


def test_cached_kline_correlation_provider_uses_active_other_symbols():
    positions = [
        SimpleNamespace(symbol="BTCUSDT", status=PositionStatus.OPEN),
        SimpleNamespace(symbol="ETHUSDT", status=PositionStatus.OPEN),
        SimpleNamespace(symbol="SOLUSDT", status=PositionStatus.OPEN),
    ]

    class Repository:
        def get_open_positions(self):
            return positions

    rising = list(range(1, 61))
    falling = list(range(60, 0, -1))

    def loader(symbol):
        return {"BTCUSDT": _correlation_rows(rising), "ETHUSDT": _correlation_rows(rising), "SOLUSDT": _correlation_rows(falling)}.get(symbol, [])

    provider = KlineCorrelationProvider(Repository(), loader, lookback_candles=50, minimum_observations=30)
    assert provider.get_score("BTCUSDT") == pytest.approx(1.0)


def test_cached_kline_correlation_provider_returns_zero_without_comparable_data():
    class Repository:
        def get_open_positions(self):
            return [SimpleNamespace(symbol="BTCUSDT", status=PositionStatus.OPEN)]

    provider = KlineCorrelationProvider(Repository(), lambda symbol: [], minimum_observations=30)
    assert provider.get_score("BTCUSDT") == 0.0
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
