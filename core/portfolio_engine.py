from typing import Dict, Optional
from core.models import (
Position,
PortfolioSnapshot,
ClosedTrade,
)
from core.trade_ledger import TradeLedger
class PortfolioEngine:
"""
المسؤول عن إدارة المحفظة بالكامل.
"""
def __init__(self, initial_balance: float):
self.balance = initial_balance
self.ledger = TradeLedger()
self.positions: Dict[str, Position] = {}
# ==========================================================
# معلومات المحفظة
# ==========================================================
def get_balance(self) -> float:
return self.balance
def get_position(self, symbol: str) -> Optional[Position]:
return self.positions.get(symbol)
def has_position(self, symbol: str) -> bool:
return symbol in self.positions
def positions_count(self):
return len(self.positions)
# ==========================================================
# Equity
# ==========================================================
def get_equity(self, prices: Dict[str, float]):
equity = self.balance
for position in self.positions.values():
price = prices.get(
position.symbol,
position.entry_price,
)
equity += position.quantity * price
return equity
# ==========================================================
# Exposure
# ==========================================================
def get_exposure(self):
exposure = 0.0
for position in self.positions.values():
exposure += (
position.quantity
* position.entry_price
)
return exposure
# ==========================================================
# فتح صفقة
# ==========================================================
def open_position(
self,
symbol: str,
quantity: float,
entry_price: float,
stop_loss: float,
take_profit: float,
confidence: float,
trade_type,
risk_level,
recovery_allowed=False,
strategy_version="V3",
entry_reason="",
):
if self.has_position(symbol):
return False
cost = quantity * entry_price
if cost > self.balance:
return False
self.balance -= cost
position = Position()
position.symbol = symbol
position.quantity = quantity
position.entry_price = entry_price
position.current_price = entry_price
position.highest_price = entry_price
position.lowest_price = entry_price
position.stop_loss = stop_loss
position.take_profit = take_profit
position.trailing_stop = stop_loss
position.confidence = confidence
position.trade_type = trade_type
position.risk_level = risk_level
position.recovery_allowed = recovery_allowed
position.strategy_version = strategy_version
position.entry_reason = entry_reason
self.positions[symbol] = position
return True
# ==========================================================
# تحديث السعر الحالي
# ==========================================================
def update_price(
self,
symbol,
current_price,
):
if symbol not in self.positions:
return
position = self.positions[symbol]
position.current_price = current_price
if current_price > position.highest_price:
position.highest_price = current_price
if (
position.lowest_price == 0
or
current_price < position.lowest_price
):
position.lowest_price = current_price
# ==========================================================
# إغلاق صفقة
# ==========================================================
def close_position(
self,
symbol: str,
exit_price: float,
fees: float = 0.0,
exit_reason=None,
):
if symbol not in self.positions:
return None
position = self.positions.pop(symbol)
gross_profit = (
exit_price - position.entry_price
) * position.quantity
net_profit = gross_profit - fees
proceeds = (
position.quantity * exit_price
) - fees
self.balance += proceeds
profit_percent = (
(
exit_price
- position.entry_price
)
/ position.entry_price
) * 100
trade = ClosedTrade(
trade_id=position.trade_id,
symbol=position.symbol,
trade_type=position.trade_type,
quantity=position.quantity,
entry_price=position.entry_price,
exit_price=exit_price,
gross_profit=gross_profit,
fees=fees,
net_profit=net_profit,
profit_percent=profit_percent,
confidence=position.confidence,
risk_level=position.risk_level,
exit_reason=exit_reason,
strategy_version=position.strategy_version,
entry_time=position.entry_time,
exit_time=position.entry_time.replace(),
)
self.ledger.closed_trades.append(trade)
return trade
# ==========================================================
# تحديث Trailing Stop
# ==========================================================
def update_trailing_stop(
self,
symbol: str,
distance: float,
):
