from __future__ import annotations

import json

from engine.entry_v2_capture_store import EntryV2CaptureStore


def _record(symbol: str, approved: bool, lane: str = "SCALP") -> dict:
    return {
        "schema_version": 1,
        "captured_at": "2026-09-17T08:00:00+00:00",
        "symbol": symbol,
        "legacy_result": {"signal": "BUY", "trade_mode": lane},
        "v2_decision": {
            "approved": approved,
            "trade_mode": lane,
            "failed_gate": None if approved else "NO_TARGET_ABOVE_ENTRY",
        },
        "entry_scenario": {"risk": {"target_status": "VALID" if approved else "NO_TARGET_ABOVE_ENTRY"}},
    }


def test_store_persists_records_and_survives_reconstruction(tmp_path):
    path = tmp_path / "entry_v2_shadow" / "captures.jsonl"
    store = EntryV2CaptureStore(path)

    assert store.append(_record("ADAUSDT", False)) is True
    assert store.append_many([_record("BNBUSDT", True), _record("LINKUSDT", True, "SWING")]) == 2
    assert store.count() == 3

    rebuilt = EntryV2CaptureStore(path)
    assert rebuilt.count() == 3
    assert [row["symbol"] for row in rebuilt.recent(2)] == ["BNBUSDT", "LINKUSDT"]

    summary = rebuilt.summary()
    assert summary["record_count"] == 3
    assert summary["approved"] == 2
    assert summary["rejected"] == 1
    assert summary["lanes"] == {"SCALP": 2, "SWING": 1}
    assert summary["failed_gates"]["NO_TARGET_ABOVE_ENTRY"] == 1


def test_store_retention_keeps_only_latest_records(tmp_path):
    path = tmp_path / "captures.jsonl"
    store = EntryV2CaptureStore(path, max_records=3)
    for index in range(5):
        assert store.append(_record(f"S{index}USDT", approved=True)) is True

    assert store.count() == 3
    assert [row["symbol"] for row in store.read_all()] == ["S2USDT", "S3USDT", "S4USDT"]


def test_store_ignores_malformed_lines_without_breaking_history(tmp_path):
    path = tmp_path / "captures.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not-json\n" + json.dumps(_record("ADAUSDT", False)) + "\n", encoding="utf-8")

    store = EntryV2CaptureStore(path)
    assert store.count() == 1
    assert store.recent(1)[0]["symbol"] == "ADAUSDT"
