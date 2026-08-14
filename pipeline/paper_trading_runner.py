"""Paper-trading orchestration for Shadow Trading Bot.

This module is deliberately paper-only: it consumes public Binance market data
and sends orders only to PaperExecutionAdapter.  It is the integration seam
between the current signal/risk/portfolio/recovery/execution components.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from config import (
    ALLOWED_SYMBOLS,
    ATR_PERIOD,
    BUY_SCORE,
    EMA_TREND,
    HEARTBEAT_SECONDS,
    INITIAL_BALANCE,
    MAX_OPEN_TRADES,
    MAX_PORTFOLIO_EXPOSURE,
    MIN_ORDER_SIZE,
    RECONNECT_DELAY,
    SELL_SCORE,
    TRADING_FEE,
    BREAK_EVEN_OFFSET,
    BREAK_EVEN_TRIGGER,
    ENABLE_BREAK_EVEN,
    ENABLE_RECOVERY,
    ENABLE_TRAILING,
    TRAILING_DISTANCE,
    TRAILING_START,
    MAX_RECOVERY_DAYS,
    EMERGENCY_STOP_LOSS,
)
from core.execution_engine import ExecutionEngine
from core.execution_models import (
    ExecutionContext,
    ExecutionRequest,
    ExecutionSource,
    OrderSide,
    OrderType,
)
from core.indicators_engine import IndicatorEngine
from core.models import Position, TradeType
from core.paper_execution_adapter import PaperExecutionAdapter
from core.portfolio_engine import PortfolioEngine
from core.recovery_engine import RecoveryEngine
from core.risk_engine import RiskEngine

logger = logging.getLogger("ShadowTrading.PaperRunner")


@dataclass(slots=True)
class SymbolState:
    price: float = 0.0
    atr: float = 0.0
    ema100: float = 0.0
    rsi: float = 0.0
    score: float = 0.0
    volatility: float = 0.0
    market_regime: str = "NEUTRAL"
    updated_at: float = 0.0


class BinancePublicMarketData:
    """Read-only public market-data client. No trading credentials are used."""

    BASE_URL = "https://api.binance.com/api/v3"

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()

    def klines(self, symbol: str, interval: str = "5m", limit: int = 250) -> pd.DataFrame:
        response = self.session.get(
            f"{self.BASE_URL}/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
            timeout=self.timeout,
        )
        response.raise_for_status()
        rows = response.json()
        if not rows:
            raise ValueError(f"No klines returned for {symbol}")

        frame = pd.DataFrame(
            rows,
            columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_volume", "trades",
                "taker_buy_base", "taker_buy_quote", "ignore",
            ],
        )
        for column in ("open", "high", "low", "close", "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame["timestamp"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        return frame[["timestamp", "open", "high", "low", "close", "volume"]].dropna()


class PaperTradingRunner:
    """Coordinates market data -> indicators -> risk -> paper execution -> portfolio."""

    def __init__(
        self,
        *,
        initial_balance: float = INITIAL_BALANCE,
        symbols: tuple[str, ...] | None = None,
    ) -> None:
        self.symbols = tuple(symbols or ALLOWED_SYMBOLS)
        self.market = BinancePublicMarketData()
        self.paper_adapter = PaperExecutionAdapter(
            initial_cash=initial_balance,
            fee_rate=TRADING_FEE,
        )
        self.execution = ExecutionEngine(self.paper_adapter)
        self.portfolio = PortfolioEngine(initial_balance)
        self.risk = RiskEngine(
            max_portfolio_exposure=MAX_PORTFOLIO_EXPOSURE,
            max_open_trades=MAX_OPEN_TRADES,
        )
        self.recovery = RecoveryEngine(
            max_recovery_days=MAX_RECOVERY_DAYS,
            emergency_loss_pct=EMERGENCY_STOP_LOSS,
        )
        self.states: dict[str, SymbolState] = {s: SymbolState() for s in self.symbols}
        self._stop_event = threading.Event()
        self._started = False
        self._cycle = 0

    def start(self) -> None:
        if self._started:
            return
        self.paper_adapter.connect()
        self.execution.connect()
        self._started = True
        logger.info("Paper trading runner started; execution source=PAPER")

    def stop(self) -> None:
        self._stop_event.set()
        if self._started:
            self.execution.shutdown()
        self._started = False
        logger.info("Paper trading runner stopped")

    def snapshot(self) -> dict[str, Any]:
        return {
            "mode": "PAPER",
            "cycle": self._cycle,
            "symbols": len(self.symbols),
            "open_positions": self.portfolio.total_open_positions(),
            "equity": self.portfolio.total_equity(),
            "free_balance": self.portfolio.available_balance(),
            "unrealized_profit": self.portfolio.unrealized_profit(),
            "realized_profit": self.portfolio.realized_profit(),
            "paper_adapter": self.paper_adapter.snapshot(),
        }

    def run_once(self) -> dict[str, Any]:
        if not self._started:
            self.start()

        self._cycle += 1
        states: dict[str, SymbolState] = {}

        for symbol in self.symbols:
            try:
                frame = self.market.klines(symbol)
                indicators = IndicatorEngine.prepare(frame)
                if indicators is None:
                    logger.warning("%s skipped: insufficient indicator history", symbol)
                    continue

                price = float(frame["close"].iloc[-1])
                atr = float(indicators["atr"].iloc[-1])
                ema100 = float(IndicatorEngine.ema(frame["close"], 100).iloc[-1])
                rsi = float(indicators["rsi"].iloc[-1])
                score = self._score(price, ema100, rsi)
                volatility = atr / price if price > 0 and atr > 0 else 0.0
                regime = "BULL" if price >= float(indicators["ema200"].iloc[-1]) else "BEAR"

                state = SymbolState(
                    price=price,
                    atr=atr,
                    ema100=ema100,
                    rsi=rsi,
                    score=score,
                    volatility=volatility,
                    market_regime=regime,
                    updated_at=time.time(),
                )
                states[symbol] = state
                self.states[symbol] = state

                self.paper_adapter.set_market_price(symbol, price)
                self.portfolio.update_position_price(symbol, price)
                self._manage_existing_position(symbol, frame, indicators, state)
                self._consider_entry(symbol, state)

            except Exception:
                logger.exception("Cycle error for %s", symbol)

        return self.snapshot() | {"processed_symbols": len(states)}

    def run_forever(self) -> None:
        self.start()
        while not self._stop_event.is_set():
            started = time.monotonic()
            self.run_once()
            elapsed = time.monotonic() - started
            self._stop_event.wait(max(1.0, HEARTBEAT_SECONDS - elapsed))
            if self._stop_event.is_set():
                break
            if elapsed > HEARTBEAT_SECONDS * 2:
                logger.warning("Paper cycle is slow: %.2fs", elapsed)
            time.sleep(0)

    @staticmethod
    def _score(price: float, ema100: float, rsi: float) -> int:
        score = 0
        if price > ema100:
            score += 50
        if rsi < 40:
            score += 30
        if rsi > 70:
            score -= 50
        return score

    def _consider_entry(self, symbol: str, state: SymbolState) -> None:
        if state.score < BUY_SCORE or self.portfolio.has_position(symbol):
            return

        confidence = 90.0 if state.score >= 80 else 80.0
        snapshot = self.portfolio.snapshot
        decision = self.risk.evaluate_trade(
            symbol=symbol,
            equity=snapshot.equity,
            free_balance=snapshot.free_balance,
            confidence=confidence,
            volatility=state.volatility,
            trade_type=TradeType.SCALPING_SWING,
            current_market_value_exposure=getattr(snapshot, "market_value", snapshot.invested),
            open_positions=self.portfolio.total_open_positions(),
            current_open_symbols=list(self.portfolio.positions.keys()),
            atr_percent=state.volatility,
            min_notional=MIN_ORDER_SIZE,
            market_regime={
                "adx": 25,
                "trend_score": 1 if state.market_regime == "BULL" else -1,
                "btc_regime": "BULLISH" if state.market_regime == "BULL" else "BEARISH",
                "btc_crash_signal": False,
                "total_market_trend": "UPTREND" if state.market_regime == "BULL" else "DOWNTREND",
                "fear_and_greed": 50,
                "usdt_dominance": 5,
            },
            recovery_engine=self.recovery,
        )
        if not decision.allowed:
            logger.info("ENTRY REJECTED %s: %s", symbol, decision.reason_code)
            return

        quantity = decision.position_size / state.price
        if quantity <= 0 or decision.position_size < MIN_ORDER_SIZE:
            return

        request = self._request(symbol, OrderSide.BUY, quantity, state.price, "ENTRY")
        result = self.execution.execute(request)
        if not result.is_success:
            logger.warning("PAPER BUY rejected %s: %s", symbol, result.message)
            return

        position = Position(
            symbol=symbol,
            quantity=result.executed_quantity,
            entry_price=result.average_price,
            highest_price=result.average_price,
            stop_loss=max(0.0, result.average_price - (state.atr * 2.0)),
            take_profit=0.0,
            atr_stop=state.atr,
            confidence=confidence,
            trade_type=TradeType.SCALPING_SWING,
            trade_id=result.exchange_order_id,
            strategy_name="Shadow Trading System V3",
            strategy_version="paper-integrated",
            run_id=f"paper-{self._cycle}",
        )
        try:
            self.portfolio.open_position(position)
        except Exception:
            logger.exception("Portfolio rejected a paper BUY after execution: %s", symbol)
            raise RuntimeError("Execution/portfolio state divergence after paper BUY")

        logger.info("PAPER BUY %s qty=%.10f price=%.8f", symbol, result.executed_quantity, result.average_price)

    def _manage_existing_position(
        self,
        symbol: str,
        frame: pd.DataFrame,
        indicators: pd.DataFrame,
        state: SymbolState,
    ) -> None:
        position = self.portfolio.get_position(symbol)
        if position is None:
            return

        current = state.price
        entry = position.entry_price
        pnl_pct = (current - entry) / entry if entry > 0 else 0.0

        if current > position.highest_price:
            position.highest_price = current

        if ENABLE_BREAK_EVEN and pnl_pct >= BREAK_EVEN_TRIGGER:
            position.break_even_active = True
            position.runtime.break_even_enabled = True
            position.runtime.break_even_price = entry * (1.0 + BREAK_EVEN_OFFSET)

        if ENABLE_TRAILING and pnl_pct >= TRAILING_START:
            position.trailing_active = True
            position.runtime.trailing_enabled = True
            candidate = position.highest_price * (1.0 - TRAILING_DISTANCE)
            position.runtime.trailing_stop_price = max(position.runtime.trailing_stop_price, candidate)

        stop_triggered = current <= position.stop_loss if position.stop_loss > 0 else False
        trailing_triggered = (
            position.trailing_active
            and position.runtime.trailing_stop_price > 0
            and current <= position.runtime.trailing_stop_price
        )
        break_even_triggered = (
            position.break_even_active
            and current <= position.runtime.break_even_price
        )

        if stop_triggered or trailing_triggered or break_even_triggered:
            self._paper_sell(symbol, current, "STOP_LOSS" if stop_triggered else "TRAILING_STOP" if trailing_triggered else "BREAK_EVEN")
            return

        if ENABLE_RECOVERY and pnl_pct <= -0.015 and not position.recovery_mode:
            self.recovery.start_recovery(position)

        if position.recovery_mode:
            decision = self.recovery.should_exit(position, current, indicators, state.market_regime)
            if decision.action == "SELL":
                self._paper_sell(symbol, current, f"RECOVERY:{decision.reason}")
                return

        if state.score <= SELL_SCORE:
            if pnl_pct > 0:
                self._paper_sell(symbol, current, "SIGNAL")
            elif ENABLE_RECOVERY:
                if not position.recovery_mode:
                    self.recovery.start_recovery(position)
            else:
                logger.info("SELL signal held for losing position %s", symbol)

    def _paper_sell(self, symbol: str, price: float, reason: str) -> None:
        position = self.portfolio.get_position(symbol)
        if position is None:
            return

        request = self._request(symbol, OrderSide.SELL, position.runtime.remaining_quantity, price, reason)
        result = self.execution.execute(request)
        if not result.is_success:
            logger.warning("PAPER SELL rejected %s: %s", symbol, result.message)
            return

        closed = self.portfolio.close_position(
            symbol,
            exit_price=result.average_price,
            fees=result.fees.total,
            exit_reason=reason,
            strategy_version=position.strategy_version,
            run_id=position.run_id,
        )
        if closed is None:
            raise RuntimeError("Execution/portfolio state divergence after paper SELL")
        logger.info("PAPER SELL %s qty=%.10f price=%.8f reason=%s", symbol, result.executed_quantity, result.average_price, reason)

    @staticmethod
    def _request(symbol: str, side: OrderSide, quantity: float, price: float, reason: str) -> ExecutionRequest:
        now = datetime.now(timezone.utc)
        return ExecutionRequest(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=price,
            request_id=f"PAPER-REQ-{time.time_ns()}",
            client_order_id=f"PAPER-{symbol}-{time.time_ns()}",
            context=ExecutionContext(
                strategy_name="Shadow Trading System V3",
                strategy_version="paper-integrated",
                run_id="paper",
                signal_id=reason,
                exchange_name="PAPER",
                source=ExecutionSource.PAPER,
                created_at=now,
                metadata={"trade_type": TradeType.SCALPING_SWING.value, "reason": reason},
            ),
        )
