from __future__ import annotations

import json

from core.brain_shadow_capture_store import BrainShadowCaptureStore


def test_get_by_identity_streams_latest_matching_capture_without_read_all(tmp_path, monkeypatch):
    path = tmp_path / "brain-captures.jsonl"
    records = [
        {"capture_id": f"CAP-{index}", "sequence": index, "context": {"score": index}}
        for index in range(1500)
    ]
    records.extend([
        {"capture_id": "TARGET", "sequence": 1500, "context": {"score": 80}},
        {"capture_id": "TARGET", "sequence": 1501, "context": {"score": 81}},
    ])
    path.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records)
        + "{malformed-json}\n",
        encoding="utf-8",
    )
    store = BrainShadowCaptureStore(path)

    def fail_read_all():
        raise AssertionError("identity lookup must not call read_all()")

    monkeypatch.setattr(store, "read_all", fail_read_all)

    assert store.get_by_identity("TARGET") == {
        "capture_id": "TARGET",
        "sequence": 1501,
        "context": {"score": 81},
    }
    assert store.get_by_identity("MISSING") is None
    assert store.get_by_identity("") is None


def test_summary_uses_record_counter_without_loading_jsonl(tmp_path, monkeypatch):
    path = tmp_path / "brain-captures.jsonl"
    path.write_text('{"capture_id":"CAP-1"}\n{"capture_id":"CAP-2"}\n', encoding="utf-8")
    store = BrainShadowCaptureStore(path)

    def fail_read_all():
        raise AssertionError("summary must not materialize the JSONL history")

    monkeypatch.setattr(store, "read_all", fail_read_all)

    assert store.summary() == {
        "path": str(path),
        "record_count": 2,
        "last_error": None,
    }
