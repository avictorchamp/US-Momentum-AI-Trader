from datetime import datetime, timezone, timedelta
import time, io, os
import requests
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
# Provider fallback: Yahoo throttling is frequent on hosted IPs. Recover missing symbols from Stooq.
DOWNLOAD_PAUSE=0.25

def _stooq_symbol(symbol):
 return symbol.lower()+'.us'

def stooq_history(symbol, period='5y'):
 try:
  url='https://stooq.com/q/d/l/?s='+_stooq_symbol(symbol)+'&i=d'
  response=requests.get(url,timeout=20,headers={'User-Agent':'Mozilla/5.0'})
  response.raise_for_status()
  df=pd.read_csv(io.StringIO(response.text))
  if df.empty or 'Date' not in df.columns:return pd.DataFrame()
  df['Date']=pd.to_datetime(df['Date'],errors='coerce');df=df.dropna(subset=['Date']).set_index('Date').sort_index()
  if period=='5y':df=df[df.index>=pd.Timestamp.now().normalize()-pd.Timedelta(days=1900)]
  return df
 except Exception:return pd.DataFrame()

def download_prices(symbols, period='1y', batch_size=20):
 parts=[];received=set()
 for start in range(0,len(symbols),batch_size):
  batch=symbols[start:start+batch_size]
  try:
   data=yf.download(batch,period=period,interval='1d',auto_adjust=True,group_by='ticker',threads=False,progress=False,timeout=25)
   if data is not None and not data.empty:
    if isinstance(data.columns,pd.MultiIndex):
     for s in batch:
      if s in data.columns.get_level_values(0) and data[s].dropna(subset=["Close"]).shape[0]>=(300 if period=="5y" else 60):received.add(s)
    elif len(batch)==1 and data.dropna(subset=["Close"]).shape[0]>=(300 if period=="5y" else 60):received.add(batch[0]);data=pd.concat({batch[0]:data},axis=1)
    parts.append(data)
  except Exception:pass
  time.sleep(DOWNLOAD_PAUSE)
 raw=pd.concat(parts,axis=1) if parts else pd.DataFrame()
 # A symbol with a partial Yahoo response is still incomplete. Fill it from Stooq
 # rather than incorrectly treating any non-empty response as full history.
 required_rows=300 if period=="5y" else 60
 for s in [x for x in symbols if x not in received]:
  st=stooq_history(s,period)
  if not st.empty:
   st=st.rename(columns={c:c.title() for c in st.columns})
   if st.dropna(subset=["Close"]).shape[0]>=required_rows:
    one=pd.concat({s:st},axis=1)
    if not raw.empty and isinstance(raw.columns,pd.MultiIndex) and s in raw.columns.get_level_values(0):
     raw[s]=raw[s].combine_first(st)
    else:
     raw=pd.concat([raw,one],axis=1) if not raw.empty else one
    received.add(s)
  time.sleep(DOWNLOAD_PAUSE)
 return raw,received

def download_benchmark(period='5y'):
 try:
  d=yf.download('SPY',period=period,interval='1d',auto_adjust=True,threads=False,progress=False,timeout=25)
  if d is not None and not d.empty:return d
 except Exception:pass
 return stooq_history('SPY',period)

CACHE={"at":0,"payload":None};CACHE_SECONDS=600
@app.head("/")
@app.get("/")
def root():return {"service":"US Momentum AI Trader Market API","status":"online","endpoints":["/health","/api/scan","/api/quote/{symbol}","/docs"],"message":"This is the API, not the web dashboard."}
@app.head("/health")
@app.get("/health")
def health():return {"status":"ok","utc":datetime.now(timezone.utc).isoformat(),"commit":os.getenv("RENDER_GIT_COMMIT"),"symbols":len(UNIVERSE),"sectors":len(SECTORS)}
def scan_data():
 now=time.time()
 if CACHE["payload"] and now-CACHE["at"]<CACHE_SECONDS:return {**CACHE["payload"],"cache":"HIT"}
 try:
  raw,received=download_prices(UNIVERSE,period="1y",batch_size=20)
  bench=download_benchmark("1y")
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
   ret3=float((price/float(c.iloc[-64])-1)*100) if len(c)>=64 else None
   rs3=round(ret3-spy3,2) if ret3 is not None else None
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
 breadth50=round(sum(1 for x in out if x["above50"])/len(out)*100,1) if out else 0
 breadth200=round(sum(1 for x in out if x["above200"])/len(out)*100,1) if out else 0
 spy_close=bc.astype(float);spy_price=float(spy_close.iloc[-1]);spy_sma50=float(spy_close.tail(50).mean());spy_sma200=float(spy_close.tail(200).mean()) if len(spy_close)>=200 else None
 if spy_sma200 and spy_price<spy_sma200 and breadth50<40:regime="RED"
 elif spy_price>spy_sma50 and spy_sma200 and spy_price>spy_sma200 and breadth50>=60:regime="GREEN"
 else:regime="YELLOW"
 payload={"source":"Yahoo Finance via yfinance (unofficial; RS is 3-month excess return vs SPY)","dataMode":"DELAYED_OR_UNVERIFIED","fetchedAt":datetime.now(timezone.utc).isoformat(),"universeCount":len(UNIVERSE),"returnedCount":len(out),"sectorCount":len(SECTORS),"cache":"MISS","stocks":out,"marketRegime":{"state":regime,"spyPrice":round(spy_price,2),"spySMA50":round(spy_sma50,2),"spySMA200":round(spy_sma200,2) if spy_sma200 else None,"aboveSMA50Pct":breadth50,"aboveSMA200Pct":breadth200,"rule":"GREEN: SPY above SMA50+SMA200 and breadth50>=60%; RED: SPY below SMA200 and breadth50<40%; otherwise YELLOW"}}
 CACHE.update(at=now,payload=payload);return payload
@app.head("/api/scan")
@app.get("/api/scan")
def scan():return scan_data()

BACKTEST_CACHE={"at":0,"payload":None}
@app.head("/api/backtest")
@app.get("/api/backtest")
def backtest():
 now=time.time()
 if BACKTEST_CACHE["payload"] and now-BACKTEST_CACHE["at"]<3600:return BACKTEST_CACHE["payload"]
 # Fixed, liquid large-cap sample; monthly top-5 momentum, 12-month lookback,
 # long-only, equal-weight, 10 bps one-way turnover cost. SPY is benchmark.
 symbols=["AAPL","MSFT","NVDA","AMZN","META","GOOGL","AVGO","LLY","JPM","XOM","COST","WMT","NFLX","AMD","CRM","ORCL","GE","CAT","V","MA","UNH","HD","PG","KO","TSLA"]
 try:
  raw,received=download_prices(symbols,period="5y",batch_size=10)
  spydata=download_benchmark("5y")
  close=pd.DataFrame({s:raw[s]["Close"] for s in symbols if s in raw.columns.get_level_values(0)}).dropna(how="all")
  spy=spydata["Close"].dropna()
  if close.empty or len(close)<300 or len(spy)<300:raise ValueError("Insufficient 5-year daily price history")
  # Use only completed calendar months to avoid treating the current partial month as a full return.
  monthly=close.resample("ME").last()
  current_month=pd.Timestamp.now().to_period("M")
  monthly=monthly[monthly.index.to_period("M")<current_month]
  valid_symbols=[s for s in symbols if s in close.columns and close[s].notna().sum()>=300]
  missing_symbols=[s for s in symbols if s not in valid_symbols]
  if len(valid_symbols)<15:raise ValueError(f"Insufficient symbol coverage: {len(valid_symbols)}/25; missing/short: "+", ".join(missing_symbols))
  close=close[valid_symbols].copy()
  mom=monthly/monthly.shift(12)-1
  rets=monthly.pct_change(fill_method=None)
  dates=monthly.index
  equity=1.0;curve=[];bench=1.0;prev=set();trades=0;months=0
  for i in range(13,len(dates)-1):
   ranked=mom.iloc[i].dropna().sort_values(ascending=False)
   selected=set(ranked.head(5).index)
   if not selected:continue
   nextret=rets.iloc[i+1].reindex(list(selected)).dropna()
   if nextret.empty:continue
   turnover=sum(abs((1/5 if s in selected else 0)-(1/5 if s in prev else 0)) for s in selected.union(prev))
   period=float(nextret.mean())-0.001*turnover
   equity*=1+period
   p0=spy.reindex([dates[i]]).ffill().iloc[0] if dates[i] in spy.index else spy.loc[:dates[i]].iloc[-1]
   p1=spy.reindex([dates[i+1]]).ffill().iloc[0] if dates[i+1] in spy.index else spy.loc[:dates[i+1]].iloc[-1]
   bench*=float(p1/p0)
   curve.append({"date":str(dates[i+1].date()),"strategy":round(equity*100,2),"spy":round(bench*100,2),"monthlyReturnPct":round(period*100,2),"holdings":sorted(selected)})
   prev=selected;months+=1
  vals=[x["strategy"] for x in curve]
  if not vals:raise ValueError("No valid monthly observations")
  peak=100.0;maxdd=0.0
  for v in vals:
   peak=max(peak,v);maxdd=min(maxdd,(v/peak-1)*100)
  total=(equity-1)*100;spyret=(bench-1)*100
  years=months/12
  payload={"status":"ok","strategy":"12-month momentum, monthly rebalance, top 5 equal-weight","universe":symbols,"universeSize":len(symbols),"dataSymbolsCount":len(valid_symbols),"dataSymbols":valid_symbols,"excludedSymbols":missing_symbols,"coverageNote":"Backtest uses symbols with >=300 daily observations; excludes missing data; results are not survivorship-bias adjusted.","periodStart":curve[0]["date"],"periodEnd":curve[-1]["date"],"months":months,"initialIndex":100,"finalIndex":round(equity*100,2),"totalReturnPct":round(total,2),"cagrPct":round(((equity)**(1/years)-1)*100,2) if years else None,"spyReturnPct":round(spyret,2),"maxDrawdownPct":round(maxdd,2),"transactionCost":"10 bps per one-way turnover","dataSource":"Yahoo Finance adjusted daily prices; historical backtest, not live performance","curve":curve}
  BACKTEST_CACHE.update(at=now,payload=payload);return payload
 except Exception as e:raise HTTPException(502,detail="Backtest data/calculation failed: "+str(e)[:180])

@app.head("/api/quote/{symbol}")
@app.get("/api/quote/{symbol}")
def quote(symbol:str):
 s=symbol.upper()
 if s not in UNIVERSE:raise HTTPException(404,"Symbol not in universe")
 data=scan_data();item=next((x for x in data["stocks"] if x["symbol"]==s),None)
 if not item:raise HTTPException(404,"Quote unavailable")
 return item
