import unittest

from core.market_data_source_policy import market_data_symbol_groups


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
