import json
import numpy as np
from typing import List, Dict

class StrictValidationEngine:
    """محرك التحقق الصارم ومصنف استنزاف الأرباح (V18.8 Strict Gatekeeper)"""
    def __init__(self, latency_limit_ms: float = 10.0):
        self.latency_limit_ms = latency_limit_ms
        self.loss_attribution_categories = [
            "SLIPPAGE", "FEES", "LOW_LIQUIDITY", "LOW_CONFIDENCE", 
            "REGIME_DRIFT", "LATENCY", "WIDE_SPREAD", "EXCHANGE_REJECTION", 
            "EARLY_EXIT", "UNKNOWN"
        ]

    def verify_operational_gate(self, audit_records: List[dict], telemetry_latencies: List[float], exceptions_count: int) -> Dict:
        stability_pass = exceptions_count == 0
        p99_latency = np.percentile(telemetry_latencies, 99) if telemetry_latencies else float('inf')
        performance_pass = p99_latency <= self.latency_limit_ms
        
        execution_compliance = True
        for r in audit_records:
            if r.get("eligibility_status") == "DENY" and r.get("execution_style") != "NONE":
                execution_compliance = False
                break
                
        records_intact = len(audit_records) > 0 and all("signal_id" in r for r in audit_records)
        operational_success = stability_pass and performance_pass and execution_compliance and records_intact

        return {
            "validation_passed": operational_success,
            "gate_results": {
                "zero_exceptions": stability_pass,
                "p99_under_limit": performance_pass,
                "execution_compliance": execution_compliance,
                "records_integrity": records_intact
            },
            "metrics": {
                "p99_latency_ms": p99_latency,
                "total_records_audited": len(audit_records)
            }
        }

    def generate_lost_edge_report(self, audit_records: List[dict]) -> Dict[str, int]:
        lost_edge_counters = {category: 0 for category in self.loss_attribution_categories}
        executed_losses = [r for r in audit_records if r.get("eligibility_status") == "ALLOW" and r.get("final_pnl", 0) < 0]
        
        for record in executed_losses:
            attribution = record.get("loss_attribution", "UNKNOWN").upper()
            if attribution in lost_edge_counters:
                lost_edge_counters[attribution] += 1
            else:
                lost_edge_counters["UNKNOWN"] += 1
                
        return dict(sorted(lost_edge_counters.items(), key=lambda item: item[1], reverse=True))
