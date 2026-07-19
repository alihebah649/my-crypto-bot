import pandas as pd
import numpy as np
from analytics.indicators import QuantIndicators

class QuantBacktestEngine:
    """
    محرك المحاكاة عالي السرعة (NumPy-Accelerated)
    يقوم بمحاكاة التنفيذ الصارم لمنع تداخل الصفقات، حساب الرسوم والانزلاق السعري،
    واستخراج المقاييس الإحصائية المتقدمة للسلة بالكامل.
    """
    def __init__(self, fee_rate=0.001, slippage_rate=0.0005):
        self.fee_rate = fee_rate          # 0.1% رسوم المنصة لكل عملية (دخول + خروج)
        self.slippage_rate = slippage_rate  # 0.05% معدل الانزلاق السعري المتوقع عند التنفيذ الفوري

    def simulate_asset_trades(self, df: pd.DataFrame, params: dict) -> list:
        """
        محاكاة الصفقات لعملة واحدة بسرعة فائقة عبر تحويل البيانات إلى مصفوفات NumPy
        الاستراتيجية الافتراضية للتجربة: Trend Filter (EMA) + Momentum Pullback (RSI)
        """
        df = df.copy()
        # 1. توليد المؤشرات الفيكتورية
        df["ema"] = QuantIndicators.calculate_ema(df["close"], params["ema_period"])
        df["rsi"] = QuantIndicators.calculate_rsi(df["close"], params["rsi_period"])
        
        # 2. تحويل الأعمدة إلى مصفوفات نيمباي لتسريع المعالجة 100 ضعف
        close = df["close"].to_numpy()
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        ema = df["ema"].to_numpy()
        rsi = df["rsi"].to_numpy()
        timestamps = df["timestamp"].to_numpy()
        
        n = len(df)
        trades = []
        
        rsi_lower = params["rsi_lower"]
        tp_pct = params["tp_pct"] / 100.0
        sl_pct = params["sl_pct"] / 100.0
        
        i = 1
        while i < n:
            # شرط الدخول (الشراء): السعر فوق المتوسط (اتجاه صاعد) + الزخم في منطقة تشبع بيعي (تراجع)
            if close[i] > ema[i] and rsi[i] <= rsi_lower:
                entry_idx = i
                # السعر الحقيقي للدخول مع إضافة الانزلاق السعري
                entry_price = close[i] * (1.0 + self.slippage_rate)
                
                # حساب مستويات الخروج بدقة
                tp_price = entry_price * (1.0 + tp_pct)
                sl_price = entry_price * (1.0 - sl_pct)
                
                exit_idx = n - 1
                exit_price = close[-1]
                exit_reason = "End of Data"
                
                # البحث عن أول شمعة تضرب الهدف أو الوقف
                for j in range(i + 1, n):
                    # خروج محافظ: نتحقق من ضرب الوقف أولاً
                    if low[j] <= sl_price:
                        exit_idx = j
                        exit_price = sl_price * (1.0 - self.slippage_rate) # خصم الانزلاق عند الخروج
                        exit_reason = "Stop Loss"
                        break
                    elif high[j] >= tp_price:
                        exit_idx = j
                        exit_price = tp_price * (1.0 - self.slippage_rate)
                        exit_reason = "Take Profit"
                        break
                
                # حساب العائد الإجمالي والصافي بعد خصم الرسوم (دخول وخروج)
                gross_return = (exit_price - entry_price) / entry_price
                net_return = gross_return - (self.fee_rate * 2.0)
                
                duration = exit_idx - entry_idx
                
                trades.append({
                    "entry_time": timestamps[entry_idx],
                    "exit_time": timestamps[exit_idx],
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "return": net_return,
                    "reason": exit_reason,
                    "duration": duration
                })
                
                # منع تداخل الصفقات الحتمي: القفز فوراً إلى الشمعة التي تلي شمعة الخروج
                i = exit_idx + 1
            else:
                i += 1
                
        return trades

    def calculate_advanced_metrics(self, trades: list) -> dict:
        """حساب المقاييس الإحصائية الكوانتية الشاملة بناءً على قائمة الصفقات المنفذة"""
        if not trades:
            return {"status": "REJECTED_NO_TRADES", "score": 0.0}
            
        returns = np.array([t["return"] for t in trades])
        durations = np.array([t["duration"] for t in trades])
        
        total_trades = len(trades)
        win_trades = returns[returns > 0]
        loss_trades = returns[returns <= 0]
        
        win_rate = len(win_trades) / total_trades if total_trades > 0 else 0.0
        
        gross_profit = win_trades.sum() if len(win_trades) > 0 else 0.0
        gross_loss = abs(loss_trades.sum()) if len(loss_trades) > 0 else 0.0
        
        # حساب الـ Profit Factor الصارم
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
        
        avg_trade = returns.mean() if total_trades > 0 else 0.0
        avg_duration = durations.mean() if total_trades > 0 else 0.0
        
        # حساب التوقع الرياضي (Expectancy): متوسط ما تكسبه أو تخسره في الصفقة الواحدة
        expectancy = (win_rate * win_trades.mean() if len(win_trades) > 0 else 0.0) + \
                     ((1.0 - win_rate) * loss_trades.mean() if len(loss_trades) > 0 else 0.0)
                     
        # حساب السحب الرأسمالي الأقصى (Max Drawdown) بدقة على منحنى رأس المال
        equity = np.cumprod(1.0 + returns)
        cum_max = np.maximum.accumulate(equity)
        drawdowns = (equity - cum_max) / cum_max
        max_dd = abs(drawdowns.min()) * 100.0 if len(drawdowns) > 0 else 0.0
        
        # حساب Sharpe & Sortino Ratios (Trade-based)
        std_dev = returns.std(ddof=1) if len(returns) > 1 else 0.0
        sharpe_ratio = (avg_trade / std_dev * np.sqrt(total_trades)) if std_dev > 0 else 0.0
        
        downside_returns = returns[returns < 0]
        downside_std = downside_returns.std(ddof=1) if len(downside_returns) > 1 else std_dev
        sortino_ratio = (avg_trade / downside_std * np.sqrt(total_trades)) if downside_std > 0 else 0.0
        
        return {
            "status": "SUCCESS",
            "total_trades": total_trades,
            "win_rate": round(win_rate * 100, 2),
            "profit_factor": round(profit_factor, 2),
            "expectancy": round(expectancy * 100, 4),
            "max_drawdown": round(max_dd, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "sortino_ratio": round(sortino_ratio, 2),
            "avg_trade_return": round(avg_trade * 100, 2),
            "avg_duration_hours": round(avg_duration, 1)
        }

    def evaluate_basket(self, basket_data: dict, params: dict) -> dict:
        """
        تشغيل المحاكاة على سلة الأصول بالكامل وحساب دالة التقييم المركبة (Multi-Objective Optimization Score)
        مصحوبة بالمتوسطات العامة لمنع انحياز الأصل المالي.
        """
        basket_metrics = {}
        all_metrics_list = []
        
        for asset, df in basket_data.items():
            trades = self.simulate_asset_trades(df, params)
            metrics = self.calculate_advanced_metrics(trades)
            
            if metrics["status"] == "SUCCESS":
                basket_metrics[asset] = metrics
                all_metrics_list.append(metrics)
            else:
                basket_metrics[asset] = {"total_trades": 0, "profit_factor": 0.0, "max_drawdown": 100.0, "sharpe_ratio": 0.0, "expectancy": -100}
        
        if not all_metrics_list:
            return {"basket_score": 0.0, "summary": "REJECTED_ALL_ASSETS"}
            
        # حساب المتوسطات للسلة
        avg_pf = np.mean([m["profit_factor"] for m in all_metrics_list])
        avg_exp = np.mean([m["expectancy"] for m in all_metrics_list])
        avg_mdd = np.mean([m["max_drawdown"] for m in all_metrics_list])
        avg_sharpe = np.mean([m["sharpe_ratio"] for m in all_metrics_list])
        total_basket_trades = sum([m["total_trades"] for m in all_metrics_list])
        
        # دالة التقييم الرياضية المركبة بعد معايرة القيم (Normalization) لمنع خداع الصفقات القليلة
        pf_norm = min(avg_pf / 3.0, 1.0)       # سقف ممتاز للـ Profit Factor عند 3.0
        exp_norm = min(max(avg_exp / 5.0, 0.0), 1.0) # سقف ممتاز للتوقع عند 5% لكل صفقة
        mdd_norm = max(1.0 - (avg_mdd / 25.0), 0.0)  # عقاب تصاعدي إذا تجاوز السحب الرأسمالي 25%
        sharpe_norm = min(max(avg_sharpe / 2.0, 0.0), 1.0) # سقف ممتاز لشارب عند 2.0
        trades_norm = min(total_basket_trades / 300, 1.0) # مكافأة تصاعدية لاستقرار الاستراتيجية حتى 300 صفقة
        
        # التوزيع المقترح للمقاييس: 40% ربحية، 25% توقع، 15% أمان من السحب، 10% جودة مخاطرة، 10% استقرار عددي
        basket_score = (0.40 * pf_norm) + (0.25 * exp_norm) + (0.15 * mdd_norm) + (0.10 * sharpe_norm) + (0.10 * trades_norm)
        
        return {
            "basket_score": round(basket_score * 100, 2),
            "avg_profit_factor": round(avg_pf, 2),
            "avg_expectancy_pct": round(avg_exp, 4),
            "avg_max_drawdown_pct": round(avg_mdd, 2),
            "avg_sharpe_ratio": round(avg_sharpe, 2),
            "total_basket_trades": total_basket_trades,
            "detailed_assets": basket_metrics
        }
