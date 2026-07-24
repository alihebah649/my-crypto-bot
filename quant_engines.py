import numpy as np
import pandas as pd
from datetime import datetime, timezone
import uuid

class StrategyVersion:
    def __init__(self, core="v2.0.0", risk="v1.0.0", score="v1.0.0", execution="v1.0.0"):
        self.core = core
        self.risk = risk
        self.score = score
        self.execution = execution

class DynamicRiskEngine:
    def __init__(self, account_balance=10000.0, risk_per_trade_pct=0.0075, max_exposure_pct=0.25):
        self.account_balance = account_balance
        self.risk_per_trade_pct = risk_per_trade_pct
        self.max_exposure_pct = max_exposure_pct

    def calculate_position_size(self, entry_price, atr, stop_loss_multiplier=2.0):
        """
        حساب حجم المركز بناءً على رأس المال، نسبة المخاطرة المسموحة، والمسافة إلى وقف الخسارة عبر الـ ATR
        """
        risk_amount = self.account_balance * self.risk_per_trade_pct
        risk_per_share = atr * stop_loss_multiplier
        if risk_per_share <= 0:
            return 0.0
        
        shares = risk_amount / risk_per_share
        position_usd = shares * entry_price
        return position_usd

    def check_portfolio_exposure(self, current_exposure_usd):
        max_allowed = self.account_balance * self.max_exposure_pct
        return current_exposure_usd < max_allowed

class RollingCorrelationFilter:
    def __init__(self, window=100, threshold=0.75):
        self.window = window
        self.threshold = threshold

    def get_returns_correlation(self, prices_df):
        """حساب مصفوفة الارتباط بناءً على العوائد (Returns) وليس الأسعار الخام لتجنب التضليل"""
        returns = prices_df.pct_change().dropna()
        recent_returns = returns.tail(self.window)
        return recent_returns.corr()

    def check_correlation(self, symbol, open_symbols, corr_matrix):
        if not open_symbols:
            return True, "OK"
        for open_sym in open_symbols:
            if symbol in corr_matrix.columns and open_sym in corr_matrix.columns:
                corr = corr_matrix.loc[symbol, open_sym]
                if corr >= self.threshold:
                    return False, f"High correlation ({corr:.2f}) with {open_sym}"
        return True, "OK"

class MultiFactorExitEngine:
    def evaluate_exit(self, current_price, trailing_stop, ema100, momentum_loss, is_bearish_candle, regime_change, market_volatility_high=False):
        """
        محرك خروج متعدد العوامل يمنح النقاط بناءً على حالة السوق ويسجل الأسباب بوضوح تام (Attribution)
        """
        if market_volatility_high:
            weights = {"trailing_atr": 50, "ema_break": 15, "momentum": 15, "candle": 10, "regime": 10}
        else:
            weights = {"trailing_atr": 30, "ema_break": 30, "momentum": 20, "candle": 10, "regime": 10}

        score = 0
        breakdown = {}

        if current_price < trailing_stop:
            score += weights["trailing_atr"]
            breakdown["trailing_atr"] = weights["trailing_atr"]
        if current_price < ema100:
            score += weights["ema_break"]
            breakdown["ema_break"] = weights["ema_break"]
        if momentum_loss:
            score += weights["momentum"]
            breakdown["momentum"] = weights["momentum"]
        if is_bearish_candle:
            score += weights["candle"]
            breakdown["candle"] = weights["candle"]
        if regime_change:
            score += weights["regime"]
            breakdown["regime"] = weights["regime"]

        should_exit = score >= 70
        return should_exit, score, breakdown

class ExecutionModel:
    def __init__(self, maker_fee=0.0002, taker_fee=0.0005):
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee

    def calculate_execution_price(self, signal_price, side, order_size_usd, avg_daily_volume_usd, atr_pct, base_slippage_bps=2.0):
        """
        حساب الانزلاق السعري (Slippage) بشكل ديناميكي بناءً على عمق السيولة وحجم الصفقة والتقلبات
        """
        volatility_component = atr_pct * 10.0
        liquidity_impact = (order_size_usd / max(avg_daily_volume_usd, 1)) * 100.0
        total_slippage_bps = base_slippage_bps + volatility_component + liquidity_impact
        total_slippage_pct = total_slippage_bps / 10000.0

        if side.upper() == 'BUY':
            exec_price = signal_price * (1.0 + total_slippage_pct)
        else:
            exec_price = signal_price * (1.0 - total_slippage_pct)

        return exec_price, total_slippage_bps

    def monte_carlo_stress_test(self, signal_price, exit_price, side, order_size_usd, avg_daily_volume_usd, atr_pct, simulations=200):
        """
        اختبار مونت كارلو للتحقق من بقاء التوقع (Expectancy) موجباً حتى تحت أسوأ ظروف التنفيذ
        """
        pnl_results = []
        for _ in range(simulations):
            noise = np.random.normal(0, 1.5)
            base_slip = max(1.0, 2.0 + noise)
            
            exec_entry, _ = self.calculate_execution_price(signal_price, side, order_size_usd, avg_daily_volume_usd, atr_pct, base_slippage_bps=base_slip)
            exec_exit, _ = self.calculate_execution_price(exit_price, 'SELL' if side.upper()=='BUY' else 'BUY', order_size_usd, avg_daily_volume_usd, atr_pct, base_slippage_bps=base_slip)
            
            fees = (exec_entry * self.taker_fee) + (exec_exit * self.taker_fee)
            raw_pnl = (exec_exit - exec_entry) if side.upper() == 'BUY' else (exec_entry - exec_exit)
            net_pnl = raw_pnl - fees
            pnl_results.append(net_pnl)

        return {
            "mean_pnl": np.mean(pnl_results),
            "worst_case_5pct": np.percentile(pnl_results, 5),
            "prob_profit": np.mean(np.array(pnl_results) > 0) * 100
        }

class TradeAdmissionCommittee:
    def __init__(self, risk_engine, correlation_filter):
        self.risk_engine = risk_engine
        self.correlation_filter = correlation_filter
        self.shadow_ledger = [] # دفتر الأستاذ الظلي لمراقبة الصفقات المرفوضة

    def evaluate_admission(self, signal, current_exposure_usd, open_symbols, prices_df):
        # 1. التحقق من التعرض العام للمحفظة
        if not self.risk_engine.check_portfolio_exposure(current_exposure_usd + signal.get('proposed_size', 0)):
            self.log_rejection(signal, "Exposure Limit Exceeded")
            return False, "Rejected by Exposure Limit"

        # 2. فحص الارتباط
        corr_matrix = self.correlation_filter.get_returns_correlation(prices_df)
        passed, msg = self.correlation_filter.check_correlation(signal.get('symbol'), open_symbols, corr_matrix)
        if not passed:
            self.log_rejection(signal, f"Correlation Filter: {msg}")
            return False, f"Rejected: {msg}"

        return True, "Approved for Execution"

    def log_rejection(self, signal, reason):
        self.shadow_ledger.append({
            "timestamp": datetime.now(timezone.utc),
            "symbol": signal.get('symbol'),
            "filter_reason": reason,
            "entry_price": signal.get('entry_price'),
            "status": "REJECTED_TRACKING"
        })

class ValidationGate:
    def evaluate_release(self, baseline_metrics, candidate_metrics, tolerance=0.05):
        """
        بوابة التحقق الصارمة: تمنع نشر أي تحديث ما لم يثبت تحسناً حقيقياً عبر المعايير المحددة
        """
        improvements = 0
        degradations = 0
        reasons = []

        metrics_to_maximize = ['Expectancy', 'Profit_Factor', 'Recovery_Factor']
        for m in metrics_to_maximize:
            if m in baseline_metrics and m in candidate_metrics:
                change = (candidate_metrics[m] - baseline_metrics[m]) / baseline_metrics[m]
                if change > 0.02:
                    improvements += 1
                elif change < -tolerance:
                    degradations += 1
                    reasons.append(f"Drop in {m}")

        if 'Max_Drawdown' in baseline_metrics and 'Max_Drawdown' in candidate_metrics:
            if candidate_metrics['Max_Drawdown'] < baseline_metrics['Max_Drawdown']:
                improvements += 1
            elif candidate_metrics['Max_Drawdown'] > baseline_metrics['Max_Drawdown'] * (1 + tolerance):
                degradations += 1
                reasons.append("Max Drawdown worsened")

        approved = (improvements >= 2) and (degradations == 0)
        return approved, reasons
