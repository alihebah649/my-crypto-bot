import unittest

from core.market_data_source_policy import (
    market_data_policy_label,
    market_data_symbol_groups,
)


SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT")


class MarketDataSymbolPolicyTests(unittest.TestCase):
    def test_mixed_mode_keeps_existing_balanced_sharding_by_default(self):
        self.assertEqual(
            market_data_symbol_groups(SYMBOLS, "MIXED"),
            (SYMBOLS[:3], SYMBOLS[3:], ()),
        )

    def test_main_override_assigns_every_symbol_to_binance(self):
        self.assertEqual(
            market_data_symbol_groups(SYMBOLS, "MIXED", main_binance_only=True),
            (SYMBOLS, (), ()),
        )

    def test_main_override_cannot_change_bybit_lab(self):
        self.assertEqual(
            market_data_symbol_groups(SYMBOLS, "BYBIT_ONLY_LAB", main_binance_only=True),
            ((), SYMBOLS, ()),
        )

    def test_main_override_cannot_change_okx_lab(self):
        self.assertEqual(
            market_data_symbol_groups(SYMBOLS, "OKX_ONLY_LAB", main_binance_only=True),
            ((), (), SYMBOLS),
        )

    def test_binance_lab_remains_isolated(self):
        self.assertEqual(
            market_data_symbol_groups(SYMBOLS, "BINANCE_ONLY_LAB"),
            (SYMBOLS, (), ()),
        )


if __name__ == "__main__":
    unittest.main()

class MarketDataPolicyLabelTests(unittest.TestCase):
    def test_main_binance_only_policy_is_distinct_from_mixed_venue_mode(self):
        self.assertEqual(
            market_data_policy_label("MIXED", main_binance_only=True),
            "BINANCE_ONLY_MAIN",
        )

    def test_default_main_policy_remains_sharded(self):
        self.assertEqual(
            market_data_policy_label("MIXED"),
            "VENUE_SHARDED",
        )

    def test_isolated_labs_have_an_explicit_policy_label(self):
        for mode in ("BINANCE_ONLY_LAB", "BYBIT_ONLY_LAB", "OKX_ONLY_LAB"):
            self.assertEqual(
                market_data_policy_label(mode, main_binance_only=True),
                "ISOLATED_VENUE_LAB",
            )

