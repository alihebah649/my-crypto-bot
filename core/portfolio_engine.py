import threading
from datetime import datetime, timezone
from typing import Dict, Optional

from core.models import (
    Position,
    PositionStatus,
    PortfolioSnapshot,
    RecoveryState,
)

from core.trade_ledger import (
    TradeLedger,
)


# ==========================================================
# Floating-Point Safety Utilities (Updated Epsilon Layer)
# ==========================================================
EPSILON = 1e-8

def is_zero(x: float) -> bool:
    """التحقق مما إذا كانت القيمة تقترب من الصفر ضمن هامش Binance"""
    return abs(x) < EPSILON

def is_positive(x: float) -> bool:
    """التحقق مما إذا كانت القيمة موجبة وحقيقية فوق هامش Binance"""
    return x > EPSILON

def safe_round(x: float) -> float:
    """تقريب داخلي لـ 10 خانات للحفاظ على الدقة وتجنب التشتت الثنائي"""
    return round(float(x), 10)


# ==========================================================
# Portfolio Engine
# ==========================================================

class PortfolioEngine:
    """
    مسؤول عن إدارة المحفظة المالية بالحساب الكامل دون تقريب بيني،
    مع تطبيق رقابة صارمة عبر Epsilon عند الأطراف والمخازن.
    """

    def __init__(self, initial_balance: float):
        self.initial_balance = float(initial_balance)
        self.balance = self.initial_balance
        self.fee_rate = 0.001  # 0.1%

        self.positions: Dict[str, Position] = {}
        self.trade_ledger = TradeLedger()

        # قفل متكرر الدخول (RLock) لمنع الـ Deadlocks
        self._lock = threading.RLock()

        self.snapshot = PortfolioSnapshot()
        self.snapshot.balance = self.balance
        self.snapshot.free_balance = self.balance
        self.snapshot.equity = self.balance
        self.snapshot.invested = 0.0
        self.snapshot.unrealized_profit = 0.0
        self.snapshot.realized_profit = 0.0

        try:
            self.snapshot.market_value = 0.0
        except AttributeError:
            pass

    # ==========================================================
    # Helper: Validate and Clean Balance (Strict Monitoring)
    # ==========================================================
    def _validate_and_clean_balance(self):
        """
        فحص ومعالجة الأرصدة عند تخزينها:
        1. إذا نزل الرصيد تحت الصفر وتجاوز EPSILON -> استثناء فوري.
        2. إذا كان قريباً جداً من الصفر -> تصفير لحسم الكسر الثنائي.
        """
        if self.snapshot.balance < -EPSILON:
            raise RuntimeError(
                f"Critical Accounting Error: Negative balance detected ({self.snapshot.balance})."
            )
        if is_zero(self.snapshot.balance):
            self.snapshot.balance = 0.0

        if self.snapshot.free_balance < -EPSILON:
            raise RuntimeError(
                f"Critical Accounting Error: Negative free balance detected ({self.snapshot.free_balance})."
            )
        if is_zero(self.snapshot.free_balance):
            self.snapshot.free_balance = 0.0

        # تقريب خفيف للتخزين الداخلي فقط (10 خانات) لمنع تراكم الـ jitter
        self.snapshot.balance = safe_round(self.snapshot.balance)
        self.snapshot.free_balance = safe_round(self.snapshot.free_balance)

    # ==========================================================
    # Position Exists / Get
    # ==========================================================
    def has_position(self, symbol: str) -> bool:
        with self._lock:
            return symbol in self.positions

    def get_position(self, symbol: str) -> Optional[Position]:
        with self._lock:
            return self.positions.get(symbol)

    # ==========================================================
    # Add Position
    # ==========================================================
    def open_position(self, position: Position):
        if not is_positive(position.entry_price) or not is_positive(position.quantity):
            raise ValueError("Entry price and quantity must be greater than zero.")

        with self._lock:
            if position.symbol in self.positions:
                raise ValueError(f"Position for symbol '{position.symbol}' already exists.")

            # حساب كامل بدون تقريب بيني لعدم تشويه الأرقام
            entry_fee = position.entry_price * position.quantity * self.fee_rate
            cost = position.entry_price * position.quantity
            total_required = cost + entry_fee

            if total_required > self.snapshot.free_balance:
                raise ValueError("Insufficient balance including entry fees.")

            self.positions[position.symbol] = position

            position.runtime.remaining_quantity = position.quantity
            position.runtime.average_entry_price = position.entry_price
            position.runtime.highest_price_seen = position.entry_price
            position.runtime.last_price = position.entry_price
            position.fees_paid = entry_fee
            position.runtime.entry_completed = True
            position.runtime.last_update = datetime.now(timezone.utc)

            self.snapshot.open_positions += 1

            self.snapshot.balance -= total_required
            self.snapshot.free_balance -= total_required
            
            self._validate_and_clean_balance()
            self.update_snapshot_unlocked()

            return position

    # ==========================================================
    # Remove Position (Private & Unlocked)
    # ==========================================================
    def _remove_position_unlocked(self, symbol: str):
        if symbol not in self.positions:
            return None

        position = self.positions.pop(symbol)
        self.snapshot.open_positions = max(0, self.snapshot.open_positions - 1)
        self.snapshot.closed_positions += 1
        return position

    # ==========================================================
    # Update Position Price
    # ==========================================================
    def update_position_price(self, symbol: str, current_price: float):
        if not is_positive(current_price):
            return

        with self._lock:
            position = self.positions.get(symbol)
            if position is None:
                return

            runtime = position.runtime
            runtime.last_price = current_price
            position.last_update = datetime.now(timezone.utc)

            if current_price > position.highest_price:
                position.highest_price = current_price
                runtime.highest_price_seen = current_price

            # حساب الأرباح غير المحققة بالدقة الكاملة بناءً على الكمية الحقيقية المتبقية
            runtime.unrealized_profit = (current_price - position.entry_price) * runtime.remaining_quantity
            position.unrealized_profit = runtime.unrealized_profit

            if is_positive(position.entry_price):
                profit_percent = ((current_price - position.entry_price) / position.entry_price) * 100
                runtime.highest_profit_percent = max(float(runtime.highest_profit_percent), profit_percent)
                runtime.lowest_profit_percent = min(float(runtime.lowest_profit_percent), profit_percent)

            self.update_snapshot_unlocked()

    # ==========================================================
    # Update Portfolio Snapshot
    # ==========================================================
    def update_snapshot(self):
        with self._lock:
            self.update_snapshot_unlocked()

    def update_snapshot_unlocked(self):
        invested_cost = 0.0
        market_value = 0.0
        unrealized = 0.0
        reserved = 0.0

        for position in self.positions.values():
            rem_qty = position.runtime.remaining_quantity
            invested_cost += position.entry_price * rem_qty
            
            current_price = getattr(position.runtime, 'last_price', position.entry_price)
            market_value += current_price * rem_qty
            unrealized += position.unrealized_profit

            if position.recovery_mode:
                reserved += position.entry_price * rem_qty

        # تخزين الأرقام النهائية مقربة لـ 10 خانات لحماية السناب شوت
        self.snapshot.invested = safe_round(invested_cost)
        try:
            self.snapshot.market_value = safe_round(market_value)
        except AttributeError:
            pass

        self.snapshot.unrealized_profit = safe_round(unrealized)
        self.snapshot.reserved_for_recovery = safe_round(reserved)
        self.snapshot.equity = safe_round(self.snapshot.balance + market_value)
        
        self.snapshot.free_balance = self.snapshot.balance if self.snapshot.balance > 0.0 else 0.0
        self.balance = self.snapshot.balance

    # ==========================================================
    # Portfolio Statistics (المخرجات النهائية للواجهة)
    # ==========================================================
    def total_open_positions(self) -> int:
        with self._lock: return len(self.positions)

    def total_invested(self) -> float:
        with self._lock: return safe_round(self.snapshot.invested)

    def total_equity(self) -> float:
        with self._lock: return safe_round(self.snapshot.equity)

    def available_balance(self) -> float:
        with self._lock: return safe_round(self.snapshot.free_balance)

    def unrealized_profit(self) -> float:
        with self._lock: return safe_round(self.snapshot.unrealized_profit)

    def realized_profit(self) -> float:
        with self._lock: return safe_round(self.snapshot.realized_profit)

    # ==========================================================
    # Partial Close
    # ==========================================================
    def partial_close(self, symbol: str, quantity: float, exit_price: float):
        if not is_positive(quantity) or not is_positive(exit_price):
            return None

        with self._lock:
            position = self.positions.get(symbol)
            if position is None:
                return None

            total_quantity_before_sale = position.runtime.remaining_quantity
            if not is_positive(total_quantity_before_sale):
                return None

            if quantity > total_quantity_before_sale:
                quantity = total_quantity_before_sale

            # العمليات الحسابية هنا تتم بالدقة الرياضية الكاملة دون أي بتر (No safe_round inside)
            entry_fee_share = position.fees_paid * quantity / total_quantity_before_sale
            gross_profit = (exit_price - position.entry_price) * quantity
            exit_fees = exit_price * quantity * self.fee_rate
            net_profit = gross_profit - exit_fees - entry_fee_share
            returned_cash = exit_price * quantity

            position.runtime.remaining_quantity = total_quantity_before_sale - quantity
            if position.runtime.remaining_quantity < 0.0:
                position.runtime.remaining_quantity = 0.0

            position.quantity = position.runtime.remaining_quantity

            if is_positive(position.quantity):
                position.runtime.average_entry_price = position.entry_price

            if hasattr(position.runtime, 'scalp_quantity'):
                position.runtime.scalp_quantity = max(0.0, position.runtime.scalp_quantity - quantity)
            
            if hasattr(position.runtime, 'swing_quantity'):
                position.runtime.swing_quantity = max(0.0, position.runtime.swing_quantity - quantity)

            position.runtime.realized_profit += net_profit
            position.realized_profit += net_profit
            position.fees_paid = (position.fees_paid - entry_fee_share) + exit_fees

            position.runtime.partial_exit_done = True
            position.runtime.last_partial_exit_price = exit_price
            position.runtime.last_partial_exit_time = datetime.now(timezone.utc)

            # تعديل الرصيد الإجمالي ثم التحقق منه
            self.snapshot.balance += (returned_cash - exit_fees)
            self._validate_and_clean_balance()

            self.snapshot.realized_profit += net_profit
            self.update_snapshot_unlocked()

            position.last_update = datetime.now(timezone.utc)
            position.runtime.last_update = datetime.now(timezone.utc)

            if is_zero(position.quantity):
                return self._close_position_unlocked(
                    symbol=symbol,
                    exit_price=exit_price,
                    fees=0.0,
                    exit_reason="FINAL_PARTIAL_EXIT",
                    strategy_version=position.strategy_version,
                    run_id=position.run_id,
                )

            return position

    # ==========================================================
    # Close Position
    # ==========================================================
    def close_position(
        self,
        symbol: str,
        exit_price: float,
        fees: Optional[float] = None,
        exit_reason: str = "MANUAL_CLOSE",
        strategy_version: str = "1.0",
        run_id: str = "default",
    ):
        with self._lock:
            return self._close_position_unlocked(
                symbol, exit_price, fees, exit_reason, strategy_version, run_id
            )

    def _close_position_unlocked(
        self,
        symbol: str,
        exit_price: float,
        fees: Optional[float] = None,
        exit_reason: str = "MANUAL_CLOSE",
        strategy_version: str = "1.0",
        run_id: str = "default",
    ):
        if not is_positive(exit_price):
            return None

        position = self._remove_position_unlocked(symbol)
        if position is None:
            return None

        if fees is None:
            fees = exit_price * position.quantity * self.fee_rate

        position.highest_price = max(position.highest_price, exit_price)
        position.runtime.highest_price_seen = position.highest_price

        # حسابات الإغلاق بالكامل بدون تدخل safe_round لتجنب تشويه الربح النهائي
        gross_profit = (exit_price - position.entry_price) * position.quantity
        total_fees_incurred = position.fees_paid + fees
        net_profit = gross_profit - total_fees_incurred
        returned_cash = exit_price * position.quantity

        self.snapshot.balance += (returned_cash - fees)
        self._validate_and_clean_balance()

        self.snapshot.realized_profit += net_profit

        position.status = PositionStatus.CLOSED
        if exit_reason in ["STOP_LOSS", "TRAILING_STOP", "BREAK_EVEN"]:
            if hasattr(position, 'last_stop_time'):
                position.last_stop_time = datetime.now(timezone.utc)

        position.is_open = False
        position.exit_reason = exit_reason
        position.realized_profit = net_profit
        total_final_fees = position.fees_paid + fees

        # تمرير البيانات بالحساب الرياضي الكامل، ونقل مسؤولية الـ 8 decimals إلى TradeLedger
        self.trade_ledger.add_trade(
            symbol=position.symbol,
            entry_time=position.entry_time,
            exit_time=datetime.now(timezone.utc),
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            gross_profit=gross_profit,
            fees=total_final_fees,
            net_profit=net_profit,
            exit_reason=exit_reason,
            strategy_version=strategy_version,
            run_id=run_id,
        )

        position.runtime.remaining_quantity = 0.0
        position.runtime.unrealized_profit = 0.0
        position.runtime.last_price = exit_price
        position.runtime.break_even_enabled = False
        position.runtime.trailing_enabled = False
        position.runtime.trailing_stop_price = 0.0
        position.runtime.break_even_price = 0.0
        position.runtime.partial_exit_done = False
        position.runtime.average_entry_price = 0.0
        position.runtime.last_partial_exit_price = 0.0
        position.runtime.last_partial_exit_time = None
        
        # السطور التالية تم تعديلها: الإبقاء على النسب التاريخية للتقارير وعدم تصفيرها
        # position.runtime.highest_profit_percent تظل كما هي
        # position.runtime.lowest_profit_percent تظل كما هي

        position.runtime.entry_completed = True  
        position.runtime.exit_completed = True

        position.recovery_mode = False
        if hasattr(position, 'recovery_state'):
            position.recovery_state = RecoveryState.FINISHED

        if hasattr(position.runtime, 'scalp_quantity'):
            position.runtime.scalp_quantity = 0.0
        if hasattr(position.runtime, 'swing_quantity'):
            position.runtime.swing_quantity = 0.0

        position.fees_paid = total_final_fees

        self.update_snapshot_unlocked()
        position.last_update = datetime.now(timezone.utc)
        position.runtime.last_update = datetime.now(timezone.utc)

        return position

    # ==========================================================
    # Portfolio Reset
    # ==========================================================
    def reset(self, clear_history: bool = False):
        with self._lock:
            self.positions.clear()
            self.balance = self.initial_balance

            self.snapshot = PortfolioSnapshot()
            self.snapshot.balance = self.balance
            self.snapshot.free_balance = self.balance
            self.snapshot.equity = self.balance
            self.snapshot.invested = 0.0
            
            try:
                self.snapshot.market_value = 0.0
            except AttributeError:
                pass

            self.snapshot.realized_profit = 0.0
            self.snapshot.unrealized_profit = 0.0
            self.snapshot.open_positions = 0
            self.snapshot.closed_positions = 0
            self.snapshot.reserved_for_recovery = 0.0

            if clear_history:
                self.trade_ledger = TradeLedger()
