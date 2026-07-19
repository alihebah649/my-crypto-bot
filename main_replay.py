import os
import itertools
import numpy as np
import pandas as pd
from datetime import datetime
from analytics.backtest import QuantBacktestEngine

class QuantOptimizationEngine:
    def __init__(self, storage_dir="data_warehouse", results_dir="research_database"):
        self.storage_dir = storage_dir
        self.results_dir = results_dir
        self.backtester = QuantBacktestEngine(fee_rate=0.001, slippage_rate=0.0005)
        
        if not os.path.exists(self.results_dir):
            os.makedirs(self.results_dir)

    def load_basket_data(self, assets, interval="1h"):
        """تحميل ملفات Parquet المخزنة محلياً للسلة بالكامل"""
        basket_data = {}
        for asset in assets:
            file_path = os.path.join(self.storage_dir, f"{asset}_{interval}.parquet")
            if os.path.exists(file_path):
                basket_data[asset] = pd.read_parquet(file_path)
            else:
                print(f"[X] ملف البيانات غير موجود للعملة: {asset}. يرجى تشغيل fetch_data.py أولاً.")
        return basket_data

    def split_train_test(self, basket_data, train_ratio=0.7):
        """شطر بيانات السلة بالكامل إلى 70% للتدريب والتحسين و 30% للاختبار الأعمى"""
        train_basket = {}
        test_basket = {}
        
        for asset, df in basket_data.items():
            split_idx = int(len(df) * train_ratio)
            train_basket[asset] = df.iloc[:split_idx].reset_index(drop=True)
            test_basket[asset] = df.iloc[split_idx:].reset_index(drop=True)
            
        return train_basket, test_basket

    def check_robustness(self, train_basket, best_params, variance=5):
        """
        اختبار حساسية المعاملات (Sensitivity Analysis)
        يفحص الجيران للتأكد من أن الاستراتيجية صلبة ولا تنهار عند تغيير طفيف في الإعدادات
        """
        robust_scores = []
        # توليد مصفوفة فحص الجيران القريبة
        neighbor_emas = [best_params["ema_period"] - variance, best_params["ema_period"], best_params["ema_period"] + variance]
        neighbor_rsis = [best_params["rsi_period"] - 2, best_params["rsi_period"], best_params["rsi_period"] + 2]
        
        for n_ema, n_rsi in itertools.product(neighbor_emas, neighbor_rsis):
            if n_ema <= 0 or n_rsi <= 0: continue
            test_params = best_params.copy()
            test_params["ema_period"] = n_ema
            test_params["rsi_period"] = n_rsi
            
            res = self.backtester.evaluate_basket(train_basket, test_params)
            robust_scores.append(res["basket_score"])
            
        # إذا كان الانحراف المعياري لنتائج الجيران مرتفعاً، فهذا يعني أن المنطقة هشة
        std_dev = np.std(robust_scores)
        is_robust = std_dev < 15.0 # عتبة القبول: يجب ألا تتذبذب النتائج بأكثر من 15 درجة
        return is_robust, round(std_dev, 2)

    def run_optimization(self, assets):
        # 1. تحميل البيانات وفصلها
        raw_basket = self.load_basket_data(assets)
        if not raw_basket: return
        
        train_basket, test_basket = self.split_train_test(raw_basket)
        
        # 2. تعريف فضاء البحث الشامل (Grid Search Space)
        # يمكنك توسيع هذه القوائم محلياً كما تريد لتشمل آلاف الاحتمالات
        ema_space = [50, 75, 100, 150, 200]
        rsi_space = [25, 28, 30, 32, 35]
        rsi_lower_space = [25, 30]
        tp_space = [2.0, 3.0, 4.0]
        sl_space = [1.0, 1.5, 2.0]
        
        combinations = list(itertools.product(ema_space, rsi_space, rsi_lower_space, tp_space, sl_space))
        total_runs = len(combinations)
        print(f"[+] بدء البحث الشامل: جاري فحص {total_runs} تركيبة استراتيجية على سلة الأصول...")
        
        all_experiments = []
        best_score = -1.0
        best_params = None
        
        start_time = datetime.now()
        
        # 3. حلقة البحث الشامل الفيكتورية الفائقة
        for idx, (ema, rsi_p, rsi_l, tp, sl) in enumerate(combinations):
            params = {
                "ema_period": ema,
                "rsi_period": rsi_p,
                "rsi_lower": rsi_l,
                "tp_pct": tp,
                "sl_pct": sl
            }
            
            # تقييم السلة في مرحلة الـ Train
            res = self.backtester.evaluate_basket(train_basket, params)
            
            status = "SUCCESS" if res["basket_score"] > 0 else "REJECTED_NO_TRADES"
            if res.get("summary") == "REJECTED_ALL_ASSETS":
                status = "REJECTED_NO_TRADES"
                
            # بناء السجل التفاحيلي الكامل للتجربة لحفظه في قاعدة البيانات
            experiment_record = {
                "ema_period": ema,
                "rsi_period": rsi_p,
                "rsi_lower": rsi_l,
                "tp_pct": tp,
                "sl_pct": sl,
                "basket_score_train": res.get("basket_score", 0.0),
                "avg_profit_factor": res.get("avg_profit_factor", 0.0),
                "avg_expectancy": res.get("avg_expectancy_pct", 0.0),
                "avg_max_drawdown": res.get("avg_max_drawdown_pct", 0.0),
                "avg_sharpe": res.get("avg_sharpe_ratio", 0.0),
                "total_trades": res.get("total_basket_trades", 0),
                "status": status
            }
            all_experiments.append(experiment_record)
            
            # تتبع القائد الحالي في مرحلة التدريب
            if status == "SUCCESS" and res["basket_score"] > best_score:
                best_score = res["basket_score"]
                best_params = params
                
        print(f"[✓] اكتمل البحث الشامل في غضون: {datetime.now() - start_time}")
        
        # 4. حفظ قاعدة البيانات الشاملة للبحوث المستقبلية
        df_results = pd.DataFrame(all_experiments)
        db_path = os.path.join(self.results_dir, "optimization_matrix.csv")
        df_results.to_csv(db_path, index=False)
        print(f"[∗] تم حفظ قاعدة بيانات الأبحاث كاملة ({len(df_results)} سجل) في: {db_path}")
        
        if not best_params:
            print("[X] لم تنجح أي استراتيجية في تحقيق شروط الحد الأدنى للتداول.")
            return

        print(f"\n" + "="*50)
        print("   أفضل إعداد تم اكتشافه في مرحلة التدريب (In-Sample)")
        print("="*50)
        print(f"Parameters: {best_params}")
        print(f"Train Score: {best_score}")
        
        # 5. إجراء اختبار الصلابة (Robustness Filter)
        print("\n[+] جاري بدء اختبار صلابة المنطقة المجاورة (Sensitivity Checking)...")
        is_robust, stability_deviation = self.check_robustness(train_basket, best_params)
        print(f"    -> معامل تشتت الاستقرار (Std Dev): {stability_deviation}")
        print(f"    -> نتيجة الفحص البيئي: {'صلبة ومستقرة (ROBUST)' if is_robust else 'هشة ومعزولة (FRAGILE)'}")
        
        # 6. الـ Walk-Forward Validation (الاختبار الأعمى النهائي)
        print("\n[+] إطلاق الـ Walk-Forward Validation على البيانات العمياء (Out-of-Sample)...")
        test_res = self.backtester.evaluate_basket(test_basket, best_params)
        
        print("\n" + "="*50)
        print("        التقرير النهائي لمختبر الاستراتيجيات")
        print("="*50)
        print(f"النتيجة في مرحلة التدريب (70%): {best_score} Pts")
        print(f"النتيجة في مرحلة الاختبار الأعمى (30%): {test_res.get('basket_score', 0.0)} Pts")
        print(f"متوسط الـ Profit Factor الفعلي في الاختبار: {test_res.get('avg_profit_factor', 0.0)}")
        print(f"متوسط الـ Drawdown الفعلي في الاختبار: {test_res.get('avg_max_drawdown_pct', 0.0)}%")
        print(f"إجمالي صفقات التحقق النهائي: {test_res.get('total_basket_trades', 0)}")
        
        # الحكم النهائي الحاسم للمنصة الكمية
        score_drop = best_score - test_res.get('basket_score', 0.0)
        if is_robust and test_res.get('basket_score', 0.0) >= 50.0 and score_drop < 20.0:
            print("\n[🚀 APPROVED] الاستراتيجية نجحت إحصائياً وتأهلت للتنفيذ الحي!")
        else:
            print("\n[⛔ REJECTED] تم رفض الاستراتيجية بسبب الـ Overfitting أو الهشاشة المعاملاتية.")

if __name__ == "__main__":
    basket = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT"]
    optimizer = QuantOptimizationEngine()
    optimizer.run_optimization(basket)
