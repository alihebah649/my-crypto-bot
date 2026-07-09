import numpy as np
from typing import List, Dict

class SanityChecker:
    """محرك فحص السلامة التشغيلية الحتمي (Stage 0)"""
    def __init__(self):
        self.last_timestamp = 0.0
        self.processed_ticks = 0
        self.latencies: List[float] = []

    def verify_tick_mechanics(self, timestamp: float, bid_vol: float, ask_vol: float):
        assert timestamp >= self.last_timestamp, f"❌ خطأ تسلسل زمني: النبضة {timestamp} وصلت بعد {self.last_timestamp}"
        assert bid_vol >= 0 and ask_vol >= 0, f"❌ خطأ سيولة: أحجام سالبة مستلمة ({bid_vol}, {ask_vol})"
        
        self.last_timestamp = timestamp
        self.processed_ticks += 1

    def monitor_performance(self, start_perf: float, end_perf: float):
        latency_ms = (end_perf - start_perf) * 1000.0
        self.latencies.append(latency_ms)
