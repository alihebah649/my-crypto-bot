import json
import time
import os
from flask import Flask, jsonify
from pipeline.metadata import MetaAuditOrchestrator
from pipeline.monitors import SanityChecker
from analytics.validation import StrictValidationEngine
from analytics.dashboard import EvidenceDashboard, FilterEfficiencyAnalyzer

# إنشاء خادم ويب مصغر لمنع ريندر من إغلاق السكربت
app = Flask(__name__)
REPORT_DATA = {"status": "Initializing"}

def run_measurement_baseline():
    global REPORT_DATA
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
            f.write(json.dumps([{"timestamp": time.time(), "open_price": 91000.0, "high": 91200.0, "low": 90800.0, "close_price": 91100.0, "bid_vol": 10.0, "ask_vol": 8.0}]))

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
    
    # حفظ تقرير النجاح لعرضه عبر الإنترنت
    REPORT_DATA = {
        "status": "SUCCESS_CODE_FREEZE",
        "run_id": run_id,
        "msg": "حالة التشغيل الآن مجمّدة وتنتظر تغذيتها ببيانات Binance الكاملة.",
        "timestamp": time.time()
    }

# تشغيل الفحص أولاً قبل فتح السيرفر
run_measurement_baseline()

@app.route('/')
def home():
    # عند الدخول لروابط ريندر سيظهر لك التقرير فوراً هنا
    return jsonify(REPORT_DATA)

if __name__ == "__main__":
    # تشغيل السيرفر على البورت الذي يطلبه ريندر
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
