from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_paper_cycle_emits_market_data_completeness_diagnostics():
    source = (ROOT / "shadow_main_legacy.py").read_text(encoding="utf-8")
    assert "[MARKET-DATA-COMPLETENESS]" in source
    assert "len(tickers)" in source
    assert "len(candles_15m)" in source
    assert "len(candles_5m)" in source
    assert "missing_symbols" in source
