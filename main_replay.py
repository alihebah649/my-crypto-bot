import json
import time
import os
from pipeline.metadata import MetaAuditOrchestrator
from pipeline.monitors import SanityChecker
from analytics.validation import StrictValidationEngine
from analytics.dashboard import EvidenceDashboard, FilterEfficiencyAnalyzer

def run_measurement_baseline():
    print("🚀 بدء محرك المحاكاة الحتمي لـ Binance (Stage A/B)...")
    
    strategy_config = {
        "min_confidence": 0.78,
        "max_spread_pct": 0.0010,
        "min_liquidity_vol": 5.0,
        "execution_mode": "MARKET"
    }
    
    dataset_path = "data/binance_24h_data.json" 
    audit_log_path = "data/decision_audit.jsonl"
    
    os.makedirs("data", exist_ok=True)
    
    if not os.path.exists(dataset_path):
        with open(dataset_path, "w") as f:
            f.write(json.dumps({"ticker": "BTCUSDT", "price": 91000.0}))

    orchestrator = MetaAuditOrchestrator(strategy_config, dataset_path)
    try:
        run_id = orchestrator.write_baseline_header(audit_log_path)
        print(f"🔑 تم قفل الهاش بنجاح! Run ID: {run_id}")
    except Exception as e:
        print(f"❌ فشل تسجيل الترويسة: {e}")
        return

    checker = SanityChecker()
    start_time = time.perf_counter()
    
    checker.verify_tick_mechanics(timestamp=time.time(), bid_vol=12.5, ask_vol=8.4)
    checker.monitor_performance(start_time, time.perf_counter())
    
    print("✅ تم فحص النبضة السعرية الأولى بنجاح دون أي Exceptions.")
    print(f"📊 حالة التشغيل الآن مجمّدة وتنتظر تغذيتها ببيانات Binance الكاملة على جهازك.")

if __name__ == "__main__":
    run_measurement_baseline()
