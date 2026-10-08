"""Non-authoritative structural stop diagnostics.

This module only proposes a structure-derived invalidation level for comparison
against the current ATR stop model. It never changes execution or risk sizing.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

LANE_STOP_TIMEFRAMES={"SCALP":("5m","15m"),"SWING":("15m","1h","4h")}

@dataclass(frozen=True)
class StructuralStopCandidate:
    trade_mode:str
    price:float|None
    source:str|None
    timeframe:str|None
    candle_index:int|None
    def to_dict(self)->dict[str,Any]:
        return {"trade_mode":self.trade_mode,"price":self.price,"source":self.source,"timeframe":self.timeframe,"candle_index":self.candle_index}

def _closed(candles:Sequence[Mapping[str,Any]])->list[Mapping[str,Any]]:
    values=list(candles or [])
    return values[:-1] if len(values)>1 else []

def _pivot_lows(candles:Sequence[Mapping[str,Any]],limit:int=48)->list[tuple[float,int]]:
    closed=_closed(candles)
    if len(closed)<3:return []
    window=closed[-limit:]
    pivots=[]
    for index in range(1,len(window)-1):
        try:
            low=float(window[index]["low"])
            left=float(window[index-1]["low"]); right=float(window[index+1]["low"])
        except (KeyError,TypeError,ValueError):
            continue
        if low<left and low<=right:pivots.append((low,index))
    return pivots

def calculate_structural_stop_candidate(*,trade_mode:str,entry_price:float,candles_by_timeframe:Mapping[str,Sequence[Mapping[str,Any]]])->StructuralStopCandidate:
    mode=str(trade_mode or "").upper(); entry=float(entry_price or 0.0)
    for timeframe in LANE_STOP_TIMEFRAMES.get(mode,()):
        eligible=[(p,i) for p,i in _pivot_lows(candles_by_timeframe.get(timeframe,())) if p>0 and p<entry]
        if eligible:
            price,index=max(eligible,key=lambda item:item[1])
            return StructuralStopCandidate(mode,price,f"{timeframe}_PIVOT_LOW",timeframe,index)
    return StructuralStopCandidate(mode,None,None,None,None)

__all__=["StructuralStopCandidate","calculate_structural_stop_candidate"]
