"""Final Trade Manager integration and failure-path tests.

These tests exercise the real Part-6/7/8 boundary used by the paper runner.
They intentionally avoid network access and live credentials.
"""

import unittest

from pipeline.trade_manager_paper_runner import TradeManagerPaperTradingRunner
from trade_manager import (
    PositionCloseReason,
    RiskEvaluation,
)


class TestTradeManagerIntegration(unittest.TestCase):
    def setUp(self):
        self.runner = TradeManagerPaperTradingRunner(initial_balance=1000.0, symbols=("BTCUSDT",))
        self.runner.start()

    def tearDown(self):
        self.runner.stop()

    def _approved_risk(self, position_size=200.0):
        return RiskEvaluation(
            approved=True,
            reason="TEST_APPROVED",
            risk_percent=1.0,
            position_value=position_size,
            capital_required=position_size,
        )

    def test_canonical_boundary_opens_and_closes_through_paper_broker(self):
        position, buy = self.runner.trade_manager.open_position_with_execution(
            symbol="BTCUSDT",
            quantity=2.0,
            entry_price=100.0,
            stop_loss=98.0,
            entry_metadata={"test": True},
            risk_evaluation=self._approved_risk(200.0),
        )

        self.assertIsNotNone(position)
        self.assertTrue(buy.success)
        self.assertEqual(len(self.runner.trade_manager.get_open_positions()), 1)
        self.assertEqual(self.runner.paper_adapter.balance.assets["BTCUSDT"], 2.0)

        closed = self.runner.trade_manager.close_position(
            position.position_id,
            102.0,
            PositionCloseReason.TAKE_PROFIT,
        )

        self.assertIsNotNone(closed)
        self.assertEqual(closed.status.name, "CLOSED")
        self.assertEqual(len(self.runner.trade_manager.get_open_positions()), 0)
        self.assertAlmostEqual(self.runner.paper_adapter.balance.assets.get("BTCUSDT", 0.0), 0.0)
        self.assertGreater(self.runner.paper_adapter.balance.cash, 1000.0)
        self.assertGreater(closed.realized_pnl, 0.0)

    def test_entry_risk_rejection_never_reaches_paper_broker(self):
        before_orders = len(self.runner.paper_adapter.orders)
        position, execution = self.runner.trade_manager.open_position_with_execution(
            symbol="BTCUSDT",
            quantity=2.0,
            entry_price=100.0,
            stop_loss=98.0,
            risk_evaluation=RiskEvaluation(False, "RISK_REJECTED"),
        )

        self.assertIsNone(position)
        self.assertFalse(execution.success)
        self.assertEqual(execution.message, "ENTRY_RISK_REJECTED:RISK_REJECTED")
        self.assertEqual(len(self.runner.paper_adapter.orders), before_orders)
        self.assertEqual(self.runner.trade_manager.get_open_positions(), [])

    def test_failed_exit_does_not_mark_position_closed(self):
        position, buy = self.runner.trade_manager.open_position_with_execution(
            symbol="BTCUSDT",
            quantity=2.0,
            entry_price=100.0,
            stop_loss=98.0,
            risk_evaluation=self._approved_risk(200.0),
        )
        self.assertTrue(buy.success)
        self.assertIsNotNone(position)

        # Simulate an external balance/state mismatch at the broker boundary.
        self.runner.paper_adapter.balance.assets["BTCUSDT"] = 0.0

        closed = self.runner.trade_manager.close_position(
            position.position_id,
            102.0,
            PositionCloseReason.MANUAL,
        )

        self.assertIsNotNone(closed)
        self.assertEqual(closed.status.name, "OPEN")
        self.assertIn("last_exit_execution_error", closed.metadata)
        self.assertEqual(len(self.runner.trade_manager.get_open_positions()), 1)

    def test_runner_snapshot_reports_trade_manager_boundary(self):
        snapshot = self.runner.snapshot()
        self.assertEqual(snapshot["mode"], "PAPER")
        self.assertEqual(snapshot["paper_adapter"]["source"], "PAPER")
        self.assertEqual(len(self.runner.trade_manager.get_open_positions()), 0)


if __name__ == "__main__":
    unittest.main()
