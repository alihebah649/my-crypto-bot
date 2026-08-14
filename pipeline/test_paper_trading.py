import unittest

from core.execution_engine import ExecutionEngine
from core.execution_models import ExecutionContext, ExecutionRequest, ExecutionSource, OrderSide, OrderType
from core.models import Position, TradeType
from core.paper_execution_adapter import PaperExecutionAdapter
from core.portfolio_engine import PortfolioEngine
from core.recovery_engine import RecoveryEngine


class TestPaperTradingIntegration(unittest.TestCase):
    def setUp(self):
        self.adapter = PaperExecutionAdapter(initial_cash=1000.0, fee_rate=0.001)
        self.engine = ExecutionEngine(self.adapter)
        self.portfolio = PortfolioEngine(1000.0)
        self.adapter.connect()
        self.engine.connect()

    def _request(self, symbol, side, quantity, price, reason):
        return ExecutionRequest(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=price,
            request_id=f"TEST-{symbol}-{reason}",
            client_order_id=f"TEST-{symbol}-{reason}",
            context=ExecutionContext(
                strategy_name="TEST",
                strategy_version="1",
                run_id="test",
                signal_id=reason,
                exchange_name="PAPER",
                source=ExecutionSource.PAPER,
            ),
        )

    def test_buy_then_sell_keeps_execution_and_portfolio_balanced(self):
        price = 100.0
        quantity = 2.0

        buy = self.engine.execute(self._request("BTCUSDT", OrderSide.BUY, quantity, price, "BUY"))
        self.assertTrue(buy.is_success)

        position = Position(
            symbol="BTCUSDT",
            quantity=quantity,
            entry_price=price,
            highest_price=price,
            trade_type=TradeType.SCALPING_SWING,
            trade_id=buy.exchange_order_id,
            strategy_name="TEST",
            strategy_version="1",
            run_id="test",
        )
        self.portfolio.open_position(position)

        sell_price = 102.0
        sell = self.engine.execute(self._request("BTCUSDT", OrderSide.SELL, quantity, sell_price, "SELL"))
        self.assertTrue(sell.is_success)

        closed = self.portfolio.close_position(
            "BTCUSDT",
            exit_price=sell.average_price,
            fees=sell.fees.total,
            exit_reason="TEST",
            strategy_version="1",
            run_id="test",
        )
        self.assertIsNotNone(closed)
        self.assertEqual(self.portfolio.total_open_positions(), 0)
        self.assertGreater(self.portfolio.total_equity(), 1000.0)
        self.assertAlmostEqual(
            self.adapter.balance.cash,
            self.portfolio.available_balance(),
            places=8,
        )

    def test_recovery_waits_for_a_losing_position(self):
        recovery = RecoveryEngine(max_recovery_days=7, emergency_loss_pct=0.08)
        position = Position(
            symbol="ETHUSDT",
            quantity=1.0,
            entry_price=100.0,
            trade_type=TradeType.SCALPING_SWING,
        )
        recovery.start_recovery(position, current_timestamp=1000.0)
        decision = recovery.should_exit(
            position,
            current_price=99.0,
            indicators=None,
            market_regime="BULL",
            current_timestamp=2000.0,
        )
        self.assertEqual(decision.action, "HOLD")
        self.assertTrue(position.recovery_mode)

    def test_paper_adapter_never_requires_live_credentials(self):
        self.assertEqual(self.adapter.exchange_name, "PAPER")
        self.assertTrue(self.adapter.is_connected())


if __name__ == "__main__":
    unittest.main()
