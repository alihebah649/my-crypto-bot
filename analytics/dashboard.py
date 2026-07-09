import numpy as np
from typing import List, Dict

class EvidenceDashboard:
    """لوحة قياس الأدلة واستخراج الميزة الإحصائية"""
    def __init__(self, audit_records: List[dict]):
        self.records = audit_records

    def generate_comprehensive_report(self) -> Dict:
        executed = [r for r in self.records if r.get("eligibility_status") == "ALLOW" and r.get("result_status") in ["WIN", "LOSS"]]
        rejected = [r for r in self.records if r.get("eligibility_status") == "DENY"]
        
        if not executed:
            return {"edge_detected": False, "reason": "No executed trades found in the log."}

        total_gross_profit = sum(r.get("final_pnl", 0) for r in executed if r.get("final_pnl", 0) > 0)
        total_gross_loss = sum(abs(r.get("final_pnl", 0)) for r in executed if r.get("final_pnl", 0) <= 0)
        total_fees = sum(r.get("fees_paid", 0) for r in executed)
        net_pnl = total_gross_profit - total_gross_loss - total_fees
        
        win_rate = sum(1 for r in executed if r.get("final_pnl", 0) > 0) / len(executed)
        profit_factor = total_gross_profit / (total_gross_loss + total_fees + 1e-8)
        expectancy = net_pnl / len(executed)
        
        valid_rejects = sum(1 for r in rejected if r.get("opportunity_cost", 0) <= 0)
        reject_precision = (valid_rejects / len(rejected)) * 100 if rejected else 100.0

        return {
            "edge_detected": net_pnl > 0 and profit_factor > 1.1,
            "metrics": {
                "net_pnl": net_pnl,
                "win_rate_pct": win_rate * 100,
                "profit_factor": profit_factor,
                "expectancy_per_trade": expectancy
            },
            "gatekeeper_efficiency": {
                "reject_rate_pct": (len(rejected) / len(self.records)) * 100,
                "reject_precision_pct": reject_precision
            }
        }

class FilterEfficiencyAnalyzer:
    """محلل كفاءة جينات الفلاتر لوقف النزيف"""
    def __init__(self, records: List[dict]):
        self.records = records

    def generate_filter_blockage_report(self) -> Dict:
        rejected_signals = [r for r in self.records if r.get("eligibility_status") == "DENY"]
        if not rejected_signals:
            return {"status": "No rejected signals."}

        filter_fail_counts = {}
        for r in rejected_signals:
            filters = r.get("filters_passed", {})
            for filter_name, passed in filters.items():
                if not passed:
                    filter_fail_counts[filter_name] = filter_fail_counts.get(filter_name, 0) + 1

        return {
            "total_rejected_signals": len(rejected_signals),
            "rejection_triggers": filter_fail_counts
        }
