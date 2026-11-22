from datetime import datetime, timezone
import time
import yfinance as yf
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
app=FastAPI(title="US Momentum AI Trader Market API",version="0.2.0")
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["GET"],allow_headers=["*"])
SECTORS={
"Technology":["AAPL","MSFT","NVDA","AMD","AVGO","ORCL","CRM","ADBE","CSCO","IBM","INTU","ACN","NOW","PLTR","SNOW","PANW","CRWD","FTNT","ZS","NET","DDOG","MDB","TEAM","WDAY","SHOP","SQ","PYPL","ADSK","ANET","DELL","HPE","SMCI","ARM","QCOM","TXN","ADI","AMAT","LRCX","KLAC","MU","TSM","ASML","MRVL","ON","MPWR","NXPI","TER","CDNS","SNPS","APH","KEYS"],
"Communication Services":["GOOGL","GOOG","META","NFLX","DIS","TMUS","T","VZ","CMCSA","CHTR","SPOT","RDDT","TTD"],
"Consumer Discretionary":["AMZN","TSLA","HD","MCD","NKE","COST","WMT","TGT","LOW","BKNG","ABNB","UBER","DASH","MELI","RBLX","GM","F","LULU","TJX","ROST","MAR","HLT","YUM","SBUX","CMG","CVNA"],
"Consumer Staples":["PG","KO","PEP","CL","MDLZ","KHC","PM","MO","EL","CAG","GIS","KR","WMT","COST"],
"Financials":["JPM","BAC","WFC","C","GS","MS","SCHW","BLK","AXP","V","MA","COIN","HOOD","MSTR","ICE","CME","SPGI","CB","PGR","BRK-B"],
"Healthcare":["LLY","NVO","ABBV","UNH","JNJ","MRK","PFE","AMGN","GILD","VRTX","REGN","ISRG","SYK","BSX","MDT","TMO","DHR","ABT","CI","CVS","HUM","ZTS","MCK","ELV","HCA"],
"Industrials":["GE","CAT","DE","ETN","PH","HON","RTX","LMT","NOC","GD","BA","TDG","EMR","CARR","JCI","VRT","PWR","URI","UPS","FDX","WM","RSG","AXON","CROX"],
"Energy":["XOM","CVX","COP","SLB","EOG","OXY","FANG","MPC","PSX","VLO","OKE","KMI","WMB","CEG","NRG","FSLR","ENPH"],
"Materials":["LIN","APD","SHW","FCX","NEM","AA","NUE","STLD","CRH","VMC","MLM","ALB"],
"Real Estate":["PLD","AMT","EQIX","DLR","O","SPG","WELL","PSA","CBRE","CCI"],
"Utilities":["NEE","DUK","SO","AEP","EXC","XEL","ED","AES"]
}
UNIVERSE=list(dict.fromkeys(s for vals in SECTORS.values() for s in vals))
CACHE={"at":0,"payload":None};CACHE_SECONDS=600
@app.get("/")
def root():return {"service":"US Momentum AI Trader Market API","status":"online","endpoints":["/health","/api/scan","/api/quote/{symbol}","/docs"],"message":"This is the API, not the web dashboard."}
@app.get("/health")
def health():return {"status":"ok","utc":datetime.now(timezone.utc).isoformat(),"symbols":len(UNIVERSE),"sectors":len(SECTORS)}
def scan_data():
 now=time.time()
 if CACHE["payload"] and now-CACHE["at"]<CACHE_SECONDS:return {**CACHE["payload"],"cache":"HIT"}
 try:
  raw=yf.download(UNIVERSE,period="1y",interval="1d",auto_adjust=True,group_by="ticker",threads=True,progress=False,timeout=35)
  bench=yf.download("SPY",period="1y",interval="1d",auto_adjust=True,progress=False,timeout=20)
  bc=bench["Close"].dropna() if isinstance(bench.columns,pd.MultiIndex) else bench["Close"].dropna()
  spy3=(float(bc.iloc[-1]/bc.iloc[-64])-1)*100 if len(bc)>=64 else 0
 except Exception as e:raise HTTPException(502,detail=f"Provider error: {str(e)[:160]}")
 if raw is None or raw.empty:raise HTTPException(502,detail="Provider returned no quotes; possible throttling.")
 out=[]
 for symbol in UNIVERSE:
  try:
   d=raw[symbol].dropna(subset=["Close"]);c=d.Close.astype(float);v=d.Volume.fillna(0).astype(float)
   if len(c)<60:continue
   price=float(c.iloc[-1]);sma50=float(c.tail(50).mean());sma200=float(c.tail(200).mean()) if len(c)>=200 else None
   ret3=float((price/float(c.iloc[-64])-1)*100) if len(c)>=64 else None\n   rs3=round(ret3-spy3,2) if ret3 is not None else None
   avg_dvol=float((c*v).tail(20).mean());vavg=float(v.tail(20).mean());vr=float(v.iloc[-1]/vavg) if vavg else 0
   h=d.High.astype(float);lo=d.Low.astype(float);pc=c.shift(1)
   atr=float(pd.concat([h-lo,(h-pc).abs(),(lo-pc).abs()],axis=1).max(axis=1).tail(14).mean())
   hi52=float(c.tail(252).max());hi20=float(c.tail(20).max())
   entry=max(price,hi20*1.001);stop=max(.01,min(price-.5*atr,entry-1.5*atr));target=entry+5*(entry-stop)
   a50=price>sma50;a200=bool(sma200 and price>sma200);near=price>=hi52*.90;liquid=price>5 and avg_dvol>=10_000_000
   score=(25 if a50 else 0)+(15 if a200 else 0)+(20 if rs3 is not None and rs3>0 else 0)+(15 if rs3 is not None and rs3>=10 else 0)+(10 if vr>=1.2 else 0)+(10 if near else 0)+(5 if liquid else 0)
   status="ENTRY READY" if liquid and a50 and a200 and rs3 is not None and rs3>0 and vr>=1.2 else "APPROACHING" if liquid and score>=55 else "WATCH" if liquid else "NO TRADE"
   sector=next((k for k,vals in SECTORS.items() if symbol in vals),"Other")
   out.append({"symbol":symbol,"sector":sector,"price":round(price,2),"changePct":round((price/float(c.iloc[-2])-1)*100,2),"rs3m":round(rs3,2) if rs3 is not None else None,"return3m":round(ret3,2) if ret3 is not None else None,"spyReturn3m":round(spy3,2),"avgDollarVolume":round(avg_dvol),"volumeRatio":round(vr,2),"sma50":round(sma50,2),"sma200":round(sma200,2) if sma200 else None,"above50":a50,"above200":a200,"near52wHigh":near,"entry":round(entry,2),"stop":round(stop,2),"target5R":round(target,2),"rr":5,"score":score,"status":status,"lastBarDate":str(d.index[-1].date())})
  except Exception:continue
 out.sort(key=lambda x:(x["score"],x["rs3m"] or -999),reverse=True)
 payload={"source":"Yahoo Finance via yfinance (unofficial; RS is 3-month excess return vs SPY)","dataMode":"DELAYED_OR_UNVERIFIED","fetchedAt":datetime.now(timezone.utc).isoformat(),"universeCount":len(UNIVERSE),"returnedCount":len(out),"sectorCount":len(SECTORS),"cache":"MISS","stocks":out}
 CACHE.update(at=now,payload=payload);return payload
@app.get("/api/scan")
def scan():return scan_data()
@app.get("/api/quote/{symbol}")
def quote(symbol:str):
 s=symbol.upper()
 if s not in UNIVERSE:raise HTTPException(404,"Symbol not in universe")
 data=scan_data();item=next((x for x in data["stocks"] if x["symbol"]==s),None)
 if not item:raise HTTPException(404,"Quote unavailable")
 return item
