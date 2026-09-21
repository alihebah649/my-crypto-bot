from __future__ import annotations

import pytest

from core.execution_adapter import ExecutionAdapter
from core.execution_models import ExecutionResult, ExecutionSource, OrderFees, OrderSide, OrderStatus, OrderType, SlippageInfo
from core.execution_profile import AccountScope, ExecutionProfile
from trade_manager.core_execution_gateway import CoreExecutionGateway
from trade_manager.integration_contracts import ExecutionRequest, ExecutionSide


class CaptureAdapter(ExecutionAdapter):
    def __init__(self):
        super().__init__("BINANCE")
        self.connected = False
        self.last_request = None

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def is_connected(self):
        return self.connected

    def execute(self, request):
        self.last_request = request
        return ExecutionResult(
            request_id=request.request_id,
            client_order_id=request.client_order_id,
            exchange_order_id="TEST-1",
            symbol=request.symbol,
            side=request.side,
            order_type=request.order_type,
            status=OrderStatus.FILLED,
            requested_quantity=request.quantity,
            executed_quantity=request.quantity,
            executed_price=100.0,
            average_price=100.0,
            fees=OrderFees(),
            slippage=SlippageInfo(requested_price=100.0, executed_price=100.0),
            exchange=self.exchange_name,
        )

    def cancel_order(self, symbol, order_id):
        return False

    def get_order(self, symbol, order_id):
        return {}


def test_execution_profile_rejects_live_paper_scope():
    with pytest.raises(ValueError, match="Paper execution profile"):
        ExecutionProfile(
            profile_id="bad",
            exchange="PAPER",
            account_scope=AccountScope.PAPER,
            live_enabled=True,
        )


def test_gateway_carries_non_secret_account_scope_metadata():
    adapter = CaptureAdapter()
    profile = ExecutionProfile(
        profile_id="lead-spot-main",
        exchange="BINANCE",
        account_scope=AccountScope.BINANCE_LEAD_SPOT,
        account_ref="lead-portfolio-001",
        live_enabled=False,
    )
    gateway = CoreExecutionGateway(
        adapter,
        source=ExecutionSource.LIVE,
        execution_profile=profile,
    )
    result = gateway.submit(
        ExecutionRequest(
            symbol="BTCUSDT",
            side=ExecutionSide.BUY,
            quantity=0.1,
            order_type="MARKET",
        )
    )

    assert result.success is True
    assert adapter.last_request is not None
    metadata = adapter.last_request.context.metadata
    assert metadata["execution_profile_id"] == "lead-spot-main"
    assert metadata["account_scope"] == "BINANCE_LEAD_SPOT"
    assert metadata["account_ref"] == "lead-portfolio-001"
    assert metadata["live_enabled"] is False


def test_paper_profile_is_still_the_runtime_default():
    profile = ExecutionProfile.paper()

    assert profile.is_paper is True
    assert profile.account_scope is AccountScope.PAPER
    assert profile.exchange == "PAPER"
    assert profile.live_enabled is False
