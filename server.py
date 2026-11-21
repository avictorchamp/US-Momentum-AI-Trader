from datetime import datetime, timezone
from functools import lru_cache
import time
import math
import yfinance as yf
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="US Momentum Market Data API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

# Curated liquid US leaders across broad market, AI, semiconductors, cloud,
# cybersecurity, networking, healthcare and consumer growth. Revisit quarterly.
UNIVERSE = [
 "SPY","QQQ","IWM","DIA","NVDA","AMD","AVGO","TSM","ASML","MU",
 "AMAT","LRCX","KLAC","QCOM","ARM","SMCI","ANET","VRT","DELL","HPE",
 "MSFT","AMZN","GOOGL","META","ORCL","CRM","NOW","PLTR","SNOW","CRWD",
 "PANW","FTNT","NET","DDOG","ZS","TSLA","NFLX","UBER","APP","HOOD",
 "JPM","GS","LLY","NVO","ISRG","VRTX","REGN","COST","WMT","XOM",
 "GE","CAT","ETN","CEG","CEG","COIN","MSTR","SHOP","MELI","ADBE"
]
CACHE = {"at": 0, "payload": None}
CACHE_SECONDS = 300

@app.get("/health")
def health():
    return {"status":"ok","service":"us-momentum-market-data","utc":datetime.now(timezone.utc).isoformat()}

def scan_data():
    now=time.time()
    if CACHE["payload"] and now-CACHE["at"] < CACHE_SECONDS:
        return {**CACHE["payload"], "cache":"HIT"}
    try:
        raw=yf.download(list(dict.fromkeys(UNIVERSE)), period="1y", interval="1d",
                        auto_adjust=True, group_by="ticker", threads=False,
                        progress=False, timeout=25)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Market data provider error: {str(e)[:180]}")
    if raw is None or raw.empty:
        raise HTTPException(status_code=502, detail="No market data returned. Provider may be throttling requests.")
    results=[]
    for symbol in dict.fromkeys(UNIVERSE):
        try:
            d=raw[symbol].dropna(subset=["Close"])
            if d.empty or len(d)<60: continue
            c=d["Close"].astype(float); v=d["Volume"].fillna(0).astype(float)
            last=float(c.iloc[-1]); prev=float(c.iloc[-2])
            sma50=float(c.tail(50).mean()) if len(c)>=50 else None
            sma200=float(c.tail(200).mean()) if len(c)>=200 else None
            rs=float((last/float(c.iloc[-64])-1)*100) if len(c)>=64 else None
            avg_dollar=float((c*v).tail(20).mean())
            avg_vol=float(v.tail(20).mean())
            vol_ratio=float(v.iloc[-1]/avg_vol) if avg_vol>0 else 0
            high52=float(c.tail(252).max())
            high20=float(c.tail(20).max())
            # ATR(14) from true range, used only to define a reference stop.
            h=d["High"].astype(float); lo=d["Low"].astype(float)
            prevc=c.shift(1)
            tr=pd.concat([h-lo,(h-prevc).abs(),(lo-prevc).abs()],axis=1).max(axis=1)
            atr=float(tr.tail(14).mean())
            entry=max(last,high20*1.001)
            stop=max(0.01, min(last-0.5*atr, entry-1.5*atr))
            risk=entry-stop
            target=entry+5*risk
            rr=5.0
            above50=bool(sma50 and last>sma50)
            above200=bool(sma200 and last>sma200)
            near_high=last>=high52*0.90
            liquid=avg_dollar>=10_000_000 and last>5
            score=0
            score+=25 if above50 else 0
            score+=15 if above200 else 0
            score+=20 if rs is not None and rs>0 else 0
            score+=15 if rs is not None and rs>=10 else 0
            score+=10 if vol_ratio>=1.2 else 0
            score+=10 if near_high else 0
            score+=5 if liquid else 0
            status="ENTRY READY" if liquid and above50 and above200 and rs is not None and rs>0 and vol_ratio>=1.2 and rr>=4 else ("APPROACHING" if liquid and score>=55 else ("WATCH" if liquid else "NO TRADE"))
            results.append({
                "symbol":symbol,"price":round(last,2),"changePct":round((last/prev-1)*100,2),
                "rs3m":round(rs,2) if rs is not None else None,
                "avgDollarVolume":round(avg_dollar),"volumeRatio":round(vol_ratio,2),
                "sma50":round(sma50,2) if sma50 else None,"sma200":round(sma200,2) if sma200 else None,
                "above50":above50,"above200":above200,"near52wHigh":near_high,
                "entry":round(entry,2),"stop":round(stop,2),"target5R":round(target,2),
                "rr":rr,"score":score,"status":status,"bars":len(d),
                "lastBarDate":str(d.index[-1].date())
            })
        except Exception:
            continue
    results.sort(key=lambda x:(x["score"],x["rs3m"] or -999),reverse=True)
    payload={"source":"Yahoo Finance via yfinance (unofficial; may be delayed/throttled)",
             "dataMode":"DELAYED_OR_UNVERIFIED","fetchedAt":datetime.now(timezone.utc).isoformat(),
             "universeCount":len(set(UNIVERSE)),"returnedCount":len(results),"cache":"MISS","stocks":results}
    CACHE.update(at=now,payload=payload)
    return payload

@app.get("/api/scan")
def api_scan():
    return scan_data()

@app.get("/api/quote/{symbol}")
def quote(symbol: str):
    s=symbol.upper().strip()
    if s not in set(UNIVERSE): raise HTTPException(status_code=404,detail="Symbol not in configured universe")
    data=scan_data()
    item=next((x for x in data["stocks"] if x["symbol"]==s),None)
    if not item: raise HTTPException(status_code=404,detail="No quote available")
    return item
