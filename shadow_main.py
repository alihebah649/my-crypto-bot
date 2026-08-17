from __future__ import annotations
import asyncio, concurrent.futures, json, logging, os, threading, time
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd, requests
from flask import Flask, jsonify
from trade_manager.shadow_integration import ShadowTradeManagerRuntime
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO")); logger=logging.getLogger("ShadowMain")
INITIAL_CASH=float(os.getenv("PAPER_INITIAL_CASH","1000")); FEE_RATE=float(os.getenv("PAPER_FEE_RATE","0.001")); PAPER_STATE_DIR=os.getenv("PAPER_STATE_DIR","data/paper"); LOOP_SECONDS=float(os.getenv("PAPER_LOOP_SECONDS","30")); REPORT_TIMEZONE=ZoneInfo(os.getenv("PAPER_REPORT_TIMEZONE","Asia/Aden")); BINANCE_REST=os.getenv("BINANCE_REST_URL","https://api.binance.com")
TRADING_SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT","LINKUSDT","ADAUSDT","DOTUSDT","NEARUSDT","ARBUSDT","OPUSDT","RENDERUSDT","BNBUSDT","AVAXUSDT","ALGOUSDT","ATOMUSDT","FETUSDT","LTCUSDT"]
SWING_SCORE_THRESHOLD=80; BUY_SCORE_THRESHOLD=80; SCALP_SCORE_THRESHOLD=int(os.getenv("PAPER_SCALP_SCORE_THRESHOLD","65"))
app=Flask(__name__); runtime=ShadowTradeManagerRuntime(initial_cash=INITIAL_CASH,fee_rate=FEE_RATE,persistence_dir=PAPER_STATE_DIR); latest_scores={}; TELEGRAM_TOKEN=os.getenv("TOKEN") or os.getenv("TELEGRAM_TOKEN"); TELEGRAM_CHAT_ID=os.getenv("TELEGRAMID") or os.getenv("TELEGRAM_CHAT_ID"); _last_report_date=None; _lock=threading.RLock()
def send_telegram_message(m):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:return False
    try:
        r=requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",json={"chat_id":TELEGRAM_CHAT_ID,"text":m},timeout=10);return r.status_code==200 and bool(r.json().get("ok",True))
    except Exception:logger.exception("telegram");return False
def _get(p,params=None):
    r=requests.get(BINANCE_REST+p,params=params,headers={"User-Agent":"ShadowTradingBot/Paper"},timeout=12);r.raise_for_status();return r.json()
def fetch_24h_tickers():
    raw=_get("/api/v3/ticker/24hr",{"symbols":json.dumps(TRADING_SYMBOLS,separators=(",",":"))});return{x["symbol"]:x for x in raw if x.get("symbol") in TRADING_SYMBOLS}
def fetch_klines(s,i,n):
    return[{"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),"close":float(x[4]),"volume":float(x[5]),"open_time":int(x[0]),"close_time":int(x[6])}for x in _get("/api/v3/klines",{"symbol":s,"interval":i,"limit":n})]
def fetch_strategy_data():
    t={};a={};b={};jobs={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12)as e:
        for s in TRADING_SYMBOLS:jobs[e.submit(fetch_klines,s,"15m",150)]=(s,a);jobs[e.submit(fetch_klines,s,"5m",60)]=(s,b)
        for f in concurrent.futures.as_completed(jobs):
            s,d=jobs[f]
            try:d[s]=f.result()
            except Exception as x:logger.warning("kline %s: %s",s,x)
    return fetch_24h_tickers(),a,b
def calculate_ema(p,n=100):return float(pd.Series(p).ewm(span=n,adjust=False).mean().iloc[-1]) if len(p)>=n else 0.
def calculate_rsi(p,n=14):
    if len(p)<n+1:return 0.
    s=pd.Series(p);d=s.diff();g=d.clip(lower=0);l=-d.clip(upper=0);ag=g.ewm(alpha=1/n,adjust=False).mean();al=l.ewm(alpha=1/n,adjust=False).mean()
    if float(al.iloc[-1])==0:return 100. if float(ag.iloc[-1])>0 else 50.
    return float((100-100/(1+ag/al)).iloc[-1])
def calculate_atr(c,n=14):
    if len(c)<n+1:return 0.
    h=pd.Series([x["high"]for x in c]);l=pd.Series([x["low"]for x in c]);q=pd.Series([x["close"]for x in c]);p=q.shift(1);tr=pd.concat([h-l,(h-p).abs(),(l-p).abs()],axis=1).max(axis=1);return float(tr.ewm(alpha=1/n,adjust=False).mean().iloc[-1])
def calculate_bollinger(c,n=20):
    if len(c)<n:return 0.,0.,0.
    s=pd.Series([x["close"]for x in c]);m=float(s.rolling(n).mean().iloc[-1]);d=float(s.rolling(n).std(ddof=0).iloc[-1]);return m-2*d,m,m+2*d
def bullish_pattern(c):
    if len(c)<4:return False,"NEUTRAL",False
    a,b,d=c[-1],c[-2],c[-3];ba=abs(a["close"]-a["open"]);bb=abs(b["close"]-b["open"]);bd=abs(d["close"]-d["open"]);bull=a["close"]>a["open"];bbull=b["close"]>b["open"];bearb=b["close"]<b["open"];beard=d["close"]<d["open"];ls=min(a["open"],a["close"])-a["low"];us=a["high"]-max(a["open"],a["close"]);n=""
    if beard and bbull and b["close"]>=d["open"] and b["open"]<=d["close"] and bb>bd:n="BULLISH_OUTSIDE"
    elif beard and bb<=bd*.3 and bull and b["low"]<d["low"] and b["low"]<a["low"]:n="MORNING_STAR"
    elif bearb and bull and a["close"]>=b["open"] and a["open"]<=b["close"] and ba>bb:n="BULLISH_ENGULFING"
    elif ls>=2*ba and us<.4*max(ba,1e-12) and ba>0:n="HAMMER"
    elif bull and bbull and a["close"]>b["high"]:n="BULLISH_BREAKOUT"
    return(bool(n),n,bool(n and bull and a["close"]>b["high"]))
def _vr(c):
    if len(c)<21:return 0.
    m=sum(x["volume"]for x in c[-21:-1])/20;return c[-1]["volume"]/m if m else 0.
def score_symbol(symbol,ticker,candles_15m,candles_5m):
    c15=candles_15m[:-1] if len(candles_15m)>1 else[];c5=candles_5m[:-1] if len(candles_5m)>1 else[];price=float(ticker.get("lastPrice",0))
    if len(c15)<100 or len(c5)<4 or price<=0:return{"symbol":symbol,"score":0,"signal":"HOLD","swing_score":0,"scalp_score":0,"swing_signal":"HOLD","scalp_signal":"HOLD","trade_mode":"NONE","reasons":["INSUFFICIENT_DATA"],"price":price,"ema100":0.,"rsi":0.,"rsi5m":0.,"atr":0.}
    p15=[x["close"]for x in c15];p5=[x["close"]for x in c5];e=calculate_ema(p15);r15=calculate_rsi(p15);r5=calculate_rsi(p5);a=calculate_atr(c15);a5=calculate_atr(c5);lo,mid,up=calculate_bollinger(c15);lo5,mid5,up5=calculate_bollinger(c5);v15=_vr(c15);v5=_vr(c5);found,name,conf=bullish_pattern(c5)
    sw=0;swr=[]
    if price>e:sw+=20;swr+=['EMA100_TREND']
    if r15<=30:sw+=20;swr+=['RSI_DEEP_OVERSOLD']
    elif r15<40:sw+=15;swr+=['RSI_OVERSOLD']
    elif r15<50:sw+=8;swr+=['RSI_RECOVERY_ZONE']
    if lo:
        d=(price-lo)/price
        if price<=lo:sw+=25;swr+=['BOLLINGER_LOWER_SUPPORT']
        elif d<=.005:sw+=18;swr+=['BOLLINGER_NEAR_SUPPORT']
        elif price<=mid:sw+=8;swr+=['BOLLINGER_LOWER_HALF']
    if v15>=1.2:sw+=15;swr+=['VOLUME_CONFIRMATION']
    elif v15>=1.05:sw+=8;swr+=['VOLUME_RISING']
    if found and conf:sw+=20;swr+=[f'5M_{name}_CONFIRMED']
    elif found:sw+=8;swr+=[f'5M_{name}']
    mp=15 if lo and price<=lo else 12 if lo and (price-lo)/price<=.005 else 6 if price<=mid else 0;mr='15M_BOLLINGER_LOWER_SUPPORT' if mp==15 else '15M_BOLLINGER_NEAR_SUPPORT' if mp==12 else '15M_BOLLINGER_LOWER_HALF' if mp==6 else ''
    sc=mp;scr=[mr]if mr else[]
    if r5<=25:sc+=20;scr+=['5M_RSI_DEEP_OVERSOLD']
    elif r5<=35:sc+=16;scr+=['5M_RSI_OVERSOLD']
    elif r5<=45:sc+=10;scr+=['5M_RSI_RECOVERY_ZONE']
    if lo5:
        d=(price-lo5)/price
        if price<=lo5:sc+=20;scr+=['5M_BOLLINGER_LOWER_SUPPORT']
        elif d<=.005:sc+=16;scr+=['5M_BOLLINGER_NEAR_SUPPORT']
        elif price<=mid5:sc+=8;scr+=['5M_BOLLINGER_LOWER_HALF']
    if v5>=1.2:sc+=15;scr+=['5M_VOLUME_CONFIRMATION']
    elif v5>=1.05:sc+=8;scr+=['5M_VOLUME_RISING']
    if found and conf:sc+=30;scr+=[f'5M_{name}_CONFIRMED']
    elif found:sc+=8;scr+=[f'5M_{name}']
    gate=bool(found and conf and r5<=45 and v5>=1.05 and mp>0);ss='BUY' if sw>=80 else'HOLD';cs='BUY' if sc>=SCALP_SCORE_THRESHOLD and gate else'HOLD';mode='SCALP' if cs=='BUY' else'SWING' if ss=='BUY' else'NONE';sel=sc if mode=='SCALP' else sw if mode=='SWING' else max(sc,sw)
    return{'symbol':symbol,'score':sel,'signal':'BUY' if mode!='NONE' else'HOLD','trade_mode':mode,'swing_score':min(sw,100),'scalp_score':min(sc,100),'swing_signal':ss,'scalp_signal':cs,'scalp_gate':gate,'reasons':scr if mode=='SCALP' else swr if mode=='SWING' else scr if sc>=sw else swr,'swing_reasons':swr,'scalp_reasons':scr,'price':price,'ema100':e,'rsi':r15,'rsi5m':r5,'atr':a,'atr5m':a5,'pattern':name,'pattern_confirmed':conf,'volume_ratio':v15,'volume_ratio_5m':v5}
def btc_crash_guard(c):
    c=c[:-1] if len(c)>1 else c
    if len(c)<3:return False,0.
    cur=c[-1]['close'];hi=max(x['close']for x in c[-3:]);drop=(cur-hi)/hi if hi else 0;return drop<=-.03,drop*100
def build_daily_report(date_key=None):
    d=date_key or datetime.now(REPORT_TIMEZONE).strftime('%Y-%m-%d');ps=[p for p in runtime.repository.get_closed_positions()if datetime.fromtimestamp(p.closed_at or p.opened_at,REPORT_TIMEZONE).strftime('%Y-%m-%d')==d];rows={}
    for p in ps:
        c=p.symbol.replace('USDT','');r=rows.setdefault(c,[0,0,0.]);v=float(p.realized_pnl);r[0 if v>0 else 1]+=1;r[2]+=v
    lines=['📊 حصاد اليوم الشامل (PAPER TRADING)',f'📅 التاريخ المنتهي: {d}','','```','COIN | WIN | LOSS | NET (FEES)','---------------------------------'];w=l=n=0.
    for c,r in sorted(rows.items()):w+=r[0];l+=r[1];n+=r[2];lines.append(f'{c:<8} | {r[0]:<3} | {r[1]:<4} | {r[2]:+.2f}$')
    lines+=['---------------------------------',f'TOTAL    | {w:<3} | {l:<4} | {n:+.2f}$','```','📄 Paper Trading — لا توجد أوامر حقيقية' if not ps else '📄 Paper Trading — أوامر محاكاة فقط',f'💵 Paper cash: ${runtime.execution_adapter.balance.cash:.2f}',f'📦 Open positions: {len(runtime.repository.get_open_positions())}'];return'\n'.join(lines)
def build_score_diagnostic():
    r=sorted(latest_scores.values(),key=lambda x:x.get('score',0),reverse=True);return'\n'.join(['🔎 Dual Strategy Diagnostic',f'Data: {len(r)}/{len(TRADING_SYMBOLS)}',f'Scalp BUY: {sum(x.get("scalp_signal")=="BUY"for x in r)}',f'Swing BUY: {sum(x.get("swing_signal")=="BUY"for x in r)}']+[f'• {x["symbol"]}: S{x.get("scalp_score",0)} W{x.get("swing_score",0)} {x.get("trade_mode","NONE")} RSI5={x.get("rsi5m",0):.1f}'for x in r[:8]])
def _daily_loop():
    global _last_report_date
    while True:
        try:
            d=datetime.now(REPORT_TIMEZONE).strftime('%Y-%m-%d')
            with _lock:
                if _last_report_date is None:_last_report_date=d
                elif d!=_last_report_date and send_telegram_message(build_daily_report(_last_report_date)):_last_report_date=d
            time.sleep(30)
        except Exception:logger.exception('daily report');time.sleep(30)
@app.get('/')
def home():return jsonify({'status':'healthy','mode':'PAPER','trade_manager':'modular_parts_1_8','symbols':TRADING_SYMBOLS,'open_positions':len(runtime.repository.get_open_positions()),'scalp_score_threshold':SCALP_SCORE_THRESHOLD,'swing_score_threshold':80}),200
@app.get('/trade-manager/positions')
def positions():return jsonify([{'position_id':p.position_id,'symbol':p.symbol,'status':p.status.name,'quantity':p.quantity,'entry_price':p.entry_price,'current_price':p.current_price,'stop_loss':p.stop_loss,'take_profit':p.take_profit,'realized_pnl':p.realized_pnl,'fees':p.total_fees}for p in runtime.repository.get_all()]),200
@app.get('/paper/daily-report')
def daily_report():return jsonify({'mode':'PAPER','date':datetime.now(REPORT_TIMEZONE).strftime('%Y-%m-%d'),'report':build_daily_report()}),200
@app.get('/paper/diagnostics')
def diagnostics():
    r=sorted(latest_scores.values(),key=lambda x:x.get('score',0),reverse=True);return jsonify({'mode':'PAPER','symbol_count':len(TRADING_SYMBOLS),'data_count':len(r),'buy_count':sum(x.get('signal')=='BUY'for x in r),'scalp_buy_count':sum(x.get('scalp_signal')=='BUY'for x in r),'swing_buy_count':sum(x.get('swing_signal')=='BUY'for x in r),'scalp_score_threshold':SCALP_SCORE_THRESHOLD,'swing_score_threshold':80,'scores':r}),200
def process_market_cycle():
    global latest_scores
    tick,c15,c5=fetch_strategy_data();new={};crash,_=btc_crash_guard(fetch_klines('BTCUSDT','1h',6))
    for s in TRADING_SYMBOLS:
        if s not in tick:continue
        row=score_symbol(s,tick[s],c15.get(s,[]),c5.get(s,[]));new[s]=row;price=row['price'];runtime.update_market(s,price=price,bid=float(tick[s].get('bidPrice',price)or price),ask=float(tick[s].get('askPrice',price)or price),spread_percent=0,atr=row.get('atr',0),volume_usdt=float(tick[s].get('quoteVolume',0)or 0),volatility=0,ema100=row.get('ema100',0));runtime.evaluate_position(s)
    latest_scores=new
    for s,row in sorted(new.items(),key=lambda z:z[1]['score'],reverse=True):
        if row['signal']!='BUY' or crash or runtime.controller.has_position(s):continue
        mult=1.25 if row['trade_mode']=='SCALP' else 2.;stop=row['price']-mult*row['atr']
        if stop<=0:continue
        p=runtime.open_position(s,row['price'],stop)
        if p:send_telegram_message(f'=== PAPER {row["trade_mode"]} BUY ===\nSymbol: {s}\nScalp Score: {row["scalp_score"]}/100\nSwing Score: {row["swing_score"]}/100\nEntry: {p.entry_price:.8f}\nStop: {p.stop_loss:.8f}\nPAPER ONLY')
    logger.info('Paper cycle: data=%d/16 scalp=%d swing=%d',len(new),sum(x.get('scalp_signal')=='BUY'for x in new.values()),sum(x.get('swing_signal')=='BUY'for x in new.values()))
async def start_shadow_engine():
    send_telegram_message(f'🟢 Paper Trading dual-mode strategy engine started on Render\nUniverse: 16 Binance Spot USDT pairs\nScalp: 5m reversal + 15m context | threshold {SCALP_SCORE_THRESHOLD}\nSwing: 15m macro + 5m confirmation | threshold 80\nTrade Manager: Parts 1-8\nNo real exchange orders are submitted.')
    while True:
        t=time.monotonic()
        try:await asyncio.to_thread(process_market_cycle)
        except Exception:logger.exception('Paper market cycle failed')
        await asyncio.sleep(max(1.,LOOP_SECONDS-(time.monotonic()-t)))
if __name__=='__main__':
    threading.Thread(target=_daily_loop,daemon=True,name='paper-daily-report').start();threading.Thread(target=lambda:asyncio.run(start_shadow_engine()),daemon=True,name='shadow-market-engine').start();app.run(host='0.0.0.0',port=int(os.getenv('PORT','10000')),debug=False,use_reloader=False)
