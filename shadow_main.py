from __future__
import asyncio, concurrent.futures, json, logging, os, threading, time
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo
import pandas as pd, requests
from flask import Flask, jsonify
from trade_manager.shadow_integration import ShadowTradeManagerRuntime

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
logger=logging.getLogger("ShadowMain")
INITIAL_CASH=float(os.getenv("PAPER_INITIAL_CASH","1000.0")); FEE_RATE=float(os.getenv("PAPER_FEE_RATE","0.001")); PAPER_STATE_DIR=os.getenv("PAPER_STATE_DIR","data/paper"); LOOP_SECONDS=float(os.getenv("PAPER_LOOP_SECONDS","30")); REPORT_TIMEZONE=ZoneInfo(os.getenv("PAPER_REPORT_TIMEZONE","Asia/Aden")); BINANCE_REST=os.getenv("BINANCE_REST_URL","https://api.binance.com")
TRADING_SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","LINKUSDT","ADAUSDT","DOTUSDT","NEARUSDT","ARBUSDT","OPUSDT","RENDERUSDT","BNBUSDT","AVAXUSDT","ALGOUSDT","ATOMUSDT","FETUSDT","LTCUSDT"]
SWING_SCORE_THRESHOLD=80; BUY_SCORE_THRESHOLD=SWING_SCORE_THRESHOLD; SCALP_SCORE_THRESHOLD=int(os.getenv("PAPER_SCALP_SCORE_THRESHOLD","65")); EMA_POINTS,RSI_POINTS,BB_POINTS,VOLUME_POINTS,CANDLE_POINTS=20,20,25,15,20
app=Flask(__name__); runtime=ShadowTradeManagerRuntime(initial_cash=INITIAL_CASH,fee_rate=FEE_RATE,persistence_dir=PAPER_STATE_DIR); latest_scores={}; TELEGRAM_TOKEN=os.getenv("TOKEN") or os.getenv("TELEGRAM_TOKEN"); TELEGRAM_CHAT_ID=os.getenv("TELEGRAMID") or os.getenv("TELEGRAM_CHAT_ID"); _last_report_date=None; _report_lock=threading.RLock()

def send_telegram_message(message:str)->bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:return False
    try:
        r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",json={"chat_id":TELEGRAM_CHAT_ID,"text":message},timeout=10); return r.status_code==200 and bool(r.json().get("ok",True))
    except Exception: logger.exception("Telegram notification failed"); return False

def _get(path:str,params:Optional[dict]=None):
    r=requests.get(f"{BINANCE_REST}{path}",params=params,headers={"User-Agent":"ShadowTradingBot/Paper"},timeout=12); r.raise_for_status(); return r.json()

def fetch_24h_tickers():
    raw=_get("/api/v3/ticker/24hr",{"symbols":json.dumps(TRADING_SYMBOLS,separators=(",",":"))}); return {x["symbol"]:x for x in raw if x.get("symbol") in TRADING_SYMBOLS}

def fetch_klines(symbol,interval,limit):
    raw=_get("/api/v3/klines",{"symbol":symbol,"interval":interval,"limit":limit}); return [{"open_time":int(x[0]),"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5]),"close_time":int(x[6])} for x in raw]

def fetch_strategy_data():
    tickers=fetch_24h_tickers(); c15={}; c5={}; jobs={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for s in TRADING_SYMBOLS: jobs[ex.submit(fetch_klines,s,"15m",150)]=(s,"15m"); jobs[ex.submit(fetch_klines,s,"5m",60)]=(s,"5m")
        for f in concurrent.futures.as_completed(jobs):
            s,t=jobs[f]
            try:data=f.result()
            except Exception as e: logger.warning("Kline fetch failed for %s %s: %s",s,t,e); continue
            (c15 if t=="15m" else c5)[s]=data
    return tickers,c15,c5

def calculate_ema(prices,period=100):
    if len(prices)<period:return 0.0
    return float(pd.Series(prices,dtype="float64").ewm(span=period,adjust=False).mean().iloc[-1])

def calculate_rsi(prices,period=14):
    if len(prices)<period+1:return 0.0
    s=pd.Series(prices,dtype="float64"); d=s.diff(); g=d.clip(lower=0); l=-d.clip(upper=0); ag=g.ewm(alpha=1/period,adjust=False).mean(); al=l.ewm(alpha=1/period,adjust=False).mean()
    if float(al.iloc[-1])==0:return 100.0 if float(ag.iloc[-1])>0 else 50.0
    return float((100-100/(1+ag/al)).iloc[-1])

def calculate_atr(candles,period=14):
    if len(candles)<period+1:return 0.0
    h=pd.Series([c["high"] for c in candles]); l=pd.Series([c["low"] for c in candles]); cl=pd.Series([c["close"] for c in candles]); p=cl.shift(1); tr=pd.concat([h-l,(h-p).abs(),(l-p).abs()],axis=1).max(axis=1); return float(tr.ewm(alpha=1/period,adjust=False).mean().iloc[-1])

def calculate_bollinger(candles,period=20,deviations=2.0):
    if len(candles)<period:return 0.0,0.0,0.0
    cl=pd.Series([c["close"] for c in candles]); m=float(cl.rolling(period).mean().iloc[-1]); sd=float(cl.rolling(period).std(ddof=0).iloc[-1]); return m-deviations*sd,m,m+deviations*sd

def bullish_pattern(c):
    if len(c)<4:return False,"INSUFFICIENT_CANDLES",False
    a,b,d=c[-1],c[-2],c[-3]; ba=abs(a["close"]-a["open"]); bb=abs(b["close"]-b["open"]); bd=abs(d["close"]-d["open"]); bull_a=a["close"]>a["open"]; bull_b=b["close"]>b["open"]; bear_b=b["close"]<b["open"]; bear_d=d["close"]<d["open"]; ls=min(a["open"],a["close"])-a["low"]; us=a["high"]-max(a["open"],a["close"]); name=""
    if bear_d and bull_b and b["close"]>=d["open"] and b["open"]<=d["close"] and bb>bd:name="BULLISH_OUTSIDE"
    elif bear_d and bb<=bd*.30 and bull_a and b["low"]<d["low"] and b["low"]<a["low"]:name="MORNING_STAR"
    elif bear_b and bull_a and a["close"]>=b["open"] and a["open"]<=b["close"] and ba>bb:name="BULLISH_ENGULFING"
    elif ls>=2*ba and us<.4*max(ba,1e-12) and ba>0:name="HAMMER"
    elif bull_a and bull_b and a["close"]>b["high"]:name="BULLISH_BREAKOUT"
    if not name:return False,"NEUTRAL",False
    return True,name,bool(bull_a and a["close"]>b["high"])

def _closed(c):return c[:-1] if len(c)>1 else []
def _vr(c):
    if len(c)<21:return 0.0
    avg=sum(x["volume"] for x in c[-21:-1])/20; return c[-1]["volume"]/avg if avg>0 else 0.0

def _macro(price,lo,mid):
    if lo<=0:return 0,""
    dist=(price-lo)/price
    if price<=lo:return 15,"15M_BOLLINGER_LOWER_SUPPORT"
    if dist<=.005:return 12,"15M_BOLLINGER_NEAR_SUPPORT"
    if price<=mid:return 6,"15M_BOLLINGER_LOWER_HALF"
    return 0,""

def _swing(price,ema,rsi,lo,mid,vr,found,name,confirmed):
    sc=0; rs=[]
    if price>ema:sc+=20;rs.append("EMA100_TREND")
    if rsi<=30:sc+=20;rs.append("RSI_DEEP_OVERSOLD")
    elif rsi<40:sc+=15;rs.append("RSI_OVERSOLD")
    elif rsi<50:sc+=8;rs.append("RSI_RECOVERY_ZONE")
    if lo>0:
        dist=(price-lo)/price
        if price<=lo:sc+=25;rs.append("BOLLINGER_LOWER_SUPPORT")
        elif dist<=.005:sc+=18;rs.append("BOLLINGER_NEAR_SUPPORT")
        elif price<=mid:sc+=8;rs.append("BOLLINGER_LOWER_HALF")
    if vr>=1.2:sc+=15;rs.append("VOLUME_CONFIRMATION")
    elif vr>=1.05:sc+=8;rs.append("VOLUME_RISING")
    if found and confirmed:sc+=20;rs.append(f"5M_{name}_CONFIRMED")
    elif found:sc+=8;rs.append(f"5M_{name}")
    return min(sc,100),rs

def _scalp(price,rsi5,lo5,mid5,vr5,found,name,confirmed,mp,mr):
    sc=mp; rs=[mr] if mr else []
    if rsi5<=25:sc+=20;rs.append("5M_RSI_DEEP_OVERSOLD")
    elif rsi5<=35:sc+=16;rs.append("5M_RSI_OVERSOLD")
    elif rsi5<=45:sc+=10;rs.append("5M_RSI_RECOVERY_ZONE")
    if lo5>0:
        dist=(price-lo5)/price
        if price<=lo5:sc+=20;rs.append("5M_BOLLINGER_LOWER_SUPPORT")
        elif dist<=.005:sc+=16;rs.append("5M_BOLLINGER_NEAR_SUPPORT")
        elif price<=mid5:sc+=8;rs.append("5M_BOLLINGER_LOWER_HALF")
    if vr5>=1.2:sc+=15;rs.append("5M_VOLUME_CONFIRMATION")
    elif vr5>=1.05:sc+=8;rs.append("5M_VOLUME_RISING")
    if found and confirmed:sc+=30;rs.append(f"5M_{name}_CONFIRMED")
    elif found:sc+=8;rs.append(f"5M_{name}")
    return min(sc,100),rs

def score_symbol(symbol,ticker,candles_15m,candles_5m):
    c15=_closed(candles_15m); c5=_closed(candles_5m); price=float(ticker.get("lastPrice",0))
    if len(c15)<100 or len(c5)<20 or price<=0:return {"symbol":symbol,"score":0,"signal":"HOLD","swing_score":0,"scalp_score":0,"swing_signal":"HOLD","scalp_signal":"HOLD","trade_mode":"NONE","reasons":["INSUFFICIENT_DATA"],"price":price,"ema100":0.0,"rsi":0.0,"rsi5m":0.0,"atr":0.0}
    p15=[x["close"] for x in c15]; p5=[x["close"] for x in c5]; ema=calculate_ema(p15); r15=calculate_rsi(p15); r5=calculate_rsi(p5); a15=calculate_atr(c15); a5=calculate_atr(c5); lo15,mid15,up15=calculate_bollinger(c15); lo5,mid5,up5=calculate_bollinger(c5); v15=_vr(c15); v5=_vr(c5); found,name,confirmed=bullish_pattern(c5); mp,mr=_macro(price,lo15,mid15); sw,swr=_swing(price,ema,r15,lo15,mid15,v15,found,name,confirmed); sc,scr=_scalp(price,r5,lo5,mid5,v5,found,name,confirmed,mp,mr)
    gate=bool(found and confirmed and r5<=45 and v5>=1.05 and mp>0); ss="BUY" if sw>=SWING_SCORE_THRESHOLD else "HOLD"; cs="BUY" if sc>=SCALP_SCORE_THRESHOLD and gate else "HOLD"
    if cs=="BUY":mode="SCALP";selected=sc;reasons=scr
    elif ss=="BUY":mode="SWING";selected=sw;reasons=swr
    else:mode="NONE";selected=max(sc,sw);reasons=scr if sc>=sw else swr
    return {"symbol":symbol,"score":selected,"signal":"BUY" if mode!="NONE" else "HOLD","trade_mode":mode,"swing_score":sw,"scalp_score":sc,"swing_signal":ss,"scalp_signal":cs,"scalp_gate":gate,"reasons":reasons,"swing_reasons":swr,"scalp_reasons":scr,"price":price,"ema100":ema,"rsi":r15,"rsi5m":r5,"atr":a15,"atr5m":a5,"lower_band":lo15,"middle_band":mid15,"upper_band":up15,"lower_band_5m":lo5,"middle_band_5m":mid5,"upper_band_5m":up5,"volume_ratio":v15,"volume_ratio_5m":v5,"pattern":name,"pattern_confirmed":confirmed}

def btc_crash_guard(c):
    c=_closed(c) or c
    if len(c)<3:return False,0.0
    cur=c[-1]["close"]; hi=max(x["close"] for x in c[-3:]); drop=(cur-hi)/hi if hi>0 else 0; return drop<=-.03,drop*100

def _closed_positions(date_key):
    return [p for p in runtime.repository.get_closed_positions() if datetime.fromtimestamp(p.closed_at or p.opened_at,REPORT_TIMEZONE).strftime("%Y-%m-%d")==date_key]

def build_daily_report(date_key=None):
    date_key=date_key or datetime.now(REPORT_TIMEZONE).strftime("%Y-%m-%d"); closed=_closed_positions(date_key); by={}
    for p in closed:
        coin=p.symbol.replace("USDT",""); row=by.setdefault(coin,{"wins":0,"losses":0,"net":0.0}); pnl=float(p.realized_pnl); row["wins" if pnl>0 else "losses"]+=1; row["net"]+=pnl
    lines=["📊 حصاد اليوم الشامل (PAPER TRADING)",f"📅 التاريخ المنتهي: {date_key}","","```",f"{'COIN':<8} | {'WIN':<3} | {'LOSS':<4} | {'NET (FEES)':<10}","---------------------------------"]; tw=tl=0;tn=0
    for coin,row in sorted(by.items()):tw+=row["wins"];tl+=row["losses"];tn+=row["net"];lines.append(f"{coin:<8} | {row['wins']:<3} | {row['losses']:<4} | {row['net']:+.2f}$")
    lines += ["---------------------------------",f"{'TOTAL':<8} | {tw:<3} | {tl:<4} | {tn:+.2f}$","```","📄 Paper Trading — لا توجد أوامر حقيقية" if not closed else "📄 Paper Trading — أوامر محاكاة فقط",f"💵 Paper cash: ${runtime.execution_adapter.balance.cash:.2f}",f"📦 Open positions: {len(runtime.repository.get_open_positions())}"]; return "\n".join(lines)

def build_score_diagnostic():
    rows=sorted(latest_scores.values(),key=lambda x:x.get("score",0),reverse=True); lines=["🔎 تشخيص الاستراتيجية — Paper Trading",f"📡 البيانات: {len(latest_scores)}/{len(TRADING_SYMBOLS)}",f"🎯 Scalping BUY: {sum(1 for r in rows if r.get('scalp_signal')=='BUY')}",f"🎯 Swing BUY: {sum(1 for r in rows if r.get('swing_signal')=='BUY')},","","أعلى الفرص:"]
    for r in rows[:8]:lines.append(f"• {r['symbol']}: SCALP {r.get('scalp_score',0)}/100 | SWING {r.get('swing_score',0)}/100 | {r.get('trade_mode','NONE')} | RSI5={r.get('rsi5m',0):.1f} | VOL5={r.get('volume_ratio_5m',0):.2f}")
    return "\n".join(lines)

def _daily_loop():
    global _last_report_date
    while True:
        try:
            d=datetime.now(REPORT_TIMEZONE).strftime("%Y-%m-%d")
            with _report_lock:
                if _last_report_date is None:_last_report_date=d
                elif d!=_last_report_date:
                    prev=_last_report_date
                    if send_telegram_message(build_daily_report(prev)):_last_report_date=d
            time.sleep(30)
        except Exception:logger.exception("Daily report loop failed");time.sleep(30)

@app.get("/")
def home():
    m=runtime.facade.get_metrics(); return jsonify({"status":"healthy","mode":"PAPER","entrypoint":"shadow_main.py","trade_manager":"modular_parts_1_8","symbols":TRADING_SYMBOLS,"open_positions":len(runtime.facade.get_open_positions()),"metrics":getattr(m,"__dict__",str(m)),"last_update":time.time(),"persistence":bool(PAPER_STATE_DIR),"telegram_configured":bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID),"score_threshold":SWING_SCORE_THRESHOLD,"scalp_score_threshold":SCALP_SCORE_THRESHOLD,"swing_score_threshold":SWING_SCORE_THRESHOLD,"strategy":"SCALP 5m reversal + 15m context / SWING 15m macro + 5m confirmation"}),200

@app.get("/trade-manager/positions")
def positions():return jsonify([{"position_id":p.position_id,"symbol":p.symbol,"status":p.status.name,"quantity":p.quantity,"entry_price":p.entry_price,"current_price":p.current_price,"stop_loss":p.stop_loss,"take_profit":p.take_profit,"realized_pnl":p.realized_pnl,"fees":p.total_fees} for p in runtime.repository.get_all()]),200

@app.get("/paper/daily-report")
def daily_report():return jsonify({"mode":"PAPER","date":datetime.now(REPORT_TIMEZONE).strftime("%Y-%m-%d"),"report":build_daily_report()}),200

@app.get("/paper/diagnostics")
def diagnostics():
    rows=sorted(latest_scores.values(),key=lambda x:x.get("score",0),reverse=True); return jsonify({"mode":"PAPER","symbol_count":len(TRADING_SYMBOLS),"data_count":len(latest_scores),"buy_count":sum(1 for r in rows if r.get("signal")=="BUY"),"scalp_buy_count":sum(1 for r in rows if r.get("scalp_signal")=="BUY"),"swing_buy_count":sum(1 for r in rows if r.get("swing_signal")=="BUY"),"scalp_score_threshold":SCALP_SCORE_THRESHOLD,"swing_score_threshold":SWING_SCORE_THRESHOLD,"scores":rows}),200

def process_market_cycle():
    global latest_scores
    tickers,c15,c5=fetch_strategy_data(); new={}; btc_crashing,btc_drop=btc_crash_guard(fetch_klines("BTCUSDT","1h",6))
    if btc_crashing:logger.warning("BTC crash guard active: %.2f%%",btc_drop)
    for s in TRADING_SYMBOLS:
        t=tickers.get(s); a=c15.get(s,[]); b=c5.get(s,[])
        if not t:continue
        price=float(t.get("lastPrice",0)); bid=float(t.get("bidPrice",price) or price); ask=float(t.get("askPrice",price) or price); spread=((ask-bid)/price*100) if price else 0; qv=float(t.get("quoteVolume",0) or 0); row=score_symbol(s,t,a,b); new[s]=row
        runtime.update_market(s,price=price,bid=bid,ask=ask,spread_percent=spread,atr=float(row.get("atr",0)),volume_usdt=qv,volatility=0,ema100=float(row.get("ema100",0))); runtime.evaluate_position(s)
    latest_scores=new
    for s,row in sorted(new.items(),key=lambda x:x[1].get("score",0),reverse=True):
        mode=row.get("trade_mode")
        if row.get("signal")!="BUY" or btc_crashing or runtime.controller.has_position(s) or mode not in {"SCALP","SWING"}:continue
        price=float(row.get("price",0)); atr=float(row.get("atr",0))
        if price<=0 or atr<=0:continue
        stop=price-(1.25 if mode=="SCALP" else 2.0)*atr
        if stop<=0:continue
        p=runtime.open_position(s,price,stop)
        if p is not None:send_telegram_message(f"=== PAPER {mode} BUY ===\nSymbol: {s}\nScalp Score: {row.get('scalp_score',0)}/100\nSwing Score: {row.get('swing_score',0)}/100\nReasons: {' | '.join(row.get('reasons',[]))}\nEntry: {p.entry_price:.8f}\nStop: {p.stop_loss:.8f}\nPAPER ONLY")
    logger.info("Paper cycle complete: data=%d/%d, SCALP=%d, SWING=%d",len(new),len(TRADING_SYMBOLS),sum(1 for r in new.values() if r.get("scalp_signal")=="BUY"),sum(1 for r in new.values() if r.get("swing_signal")=="BUY"))

async def start_shadow_engine():
    send_telegram_message("🟢 Paper Trading dual-mode strategy engine started on Render\n"+f"Universe: {len(TRADING_SYMBOLS)} Binance Spot USDT pairs\nScalp: 5m reversal + 15m context | threshold {SCALP_SCORE_THRESHOLD}\nSwing: 15m macro + 5m confirmation | threshold {SWING_SCORE_THRESHOLD}\nTrade Manager: Parts 1-8\nNo real exchange orders are submitted.")
    while True:
        started=time.monotonic()
        try:await asyncio.to_thread(process_market_cycle)
        except Exception:logger.exception("Paper market cycle failed")
        await asyncio.sleep(max(1.0,LOOP_SECONDS-(time.monotonic()-started)))

def run_flask():app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")),debug=False,use_reloader=False)

if __name__=="__main__":
    threading.Thread(target=_daily_loop,daemon=True,name="paper-daily-report").start(); threading.Thread(target=lambda:asyncio.run(start_shadow_engine()),daemon=True,name="shadow-market-engine").start(); run_flask()
