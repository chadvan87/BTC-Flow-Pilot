import asyncio, hmac, time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from app.config import settings
from app.database.store import store
from app.security.auth import admin, issue_session, save_credentials
from app.execution.engine import engine
from app.execution.binance import ExchangeError
from app.market_data.service import market
from app.risk.engine import Setup, RiskConfig, RiskRejected
from app.filters.guards import news_guard, crash_guard
from app.strategies.signals import evaluate
from app.whales.service import whales
from app.whales.config import WhaleConfig
from app.execution.auto import AutoTrader
autotrader=AutoTrader(engine,market,store)

async def supervisor():
    while True:
        await asyncio.sleep(15)
        try:
            await engine.reconcile()
            if not engine.control()["stopped"]:
                data=market.summary()
                err=news_guard(store.get("news:DEMO")) or ("Market REST stale" if data["rest_stale"] else crash_guard(data["book"],data["flow"],market.candles.get(("BTCUSDT","5m"),[])))
                if err:await engine.stop(err)
        except Exception as e:
            await engine.stop("Supervisor: "+type(e).__name__)

@asynccontextmanager
async def lifespan(app):
    await engine.stop("Restart: manual RESUME required")
    if settings.enable_market_feed:await market.start();await whales.start()
    tasks=[asyncio.create_task(supervisor()),asyncio.create_task(autotrader.run())]
    try:yield
    finally:
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True);await market.close();await whales.close()
app=FastAPI(title="BTC FlowPilot V5 • DEMO foundation",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=settings.cors_origins.split(","),allow_credentials=True,allow_methods=["GET","POST","PUT"],allow_headers=["Content-Type","X-Flowpilot-Request"])
@app.exception_handler(RequestValidationError)
async def validation_error(request,e):
    return JSONResponse(status_code=422,content={"detail":[{"loc":list(x["loc"]),"msg":x["msg"],"type":x["type"]} for x in e.errors()]})
@app.exception_handler(RiskRejected)
async def risk_error(request,e):return JSONResponse(status_code=409,content={"detail":str(e)})
@app.exception_handler(ExchangeError)
async def exchange_error(request,e):return JSONResponse(status_code=502,content={"detail":str(e)})
@app.exception_handler(Exception)
async def internal_error(request,e):
    # No upstream URLs or secret payloads returned.
    return JSONResponse(status_code=503,content={"detail":"Operation failed: "+type(e).__name__+". Check feed/account and reconcile."})
# HEAD too: uptime monitors (e.g. UptimeRobot free) probe with HEAD; otherwise the static mount answers 404.
@app.api_route("/health",methods=["GET","HEAD"])
def health():return {"status":"ok","real_trading":False,"auto_trading":"DEMO" if engine.control().get("auto") else False}
class Login(BaseModel):password:str=Field(min_length=1,max_length=256)
attempts={}
@app.post("/api/login")
async def login(payload:Login,request:Request,response:Response):
    host=request.client.host if request.client else "unknown"
    if not settings.allow_local_http and request.url.scheme!="https":raise HTTPException(403,"HTTPS required; configure trusted proxy headers")
    if settings.allow_local_http and request.url.scheme!="https" and host not in {"127.0.0.1","::1","testclient"}:raise HTTPException(403,"Plain HTTP allowed only on loopback")
    origin=request.headers.get("origin")
    if origin and origin not in settings.cors_origins.split(","):raise HTTPException(403,"Origin blocked")
    if len(settings.admin_password)<12:raise HTTPException(503,"Set a strong ADMIN_PASSWORD (at least 12 characters)")
    recent=[t for t in attempts.get(host,[]) if time.monotonic()-t<300]
    if len(recent)>=5:raise HTTPException(429,"Too many login attempts; wait 5 minutes")
    attempts[host]=recent+[time.monotonic()]
    if not hmac.compare_digest(payload.password,settings.admin_password):raise HTTPException(401,"Invalid login")
    token=issue_session();attempts.pop(host,None)
    response.set_cookie("flowpilot",token,httponly=True,secure=settings.cookie_secure,samesite="none" if settings.cookie_secure else "lax",max_age=3600)
    return {"authenticated":True}
@app.post("/api/logout",dependencies=[Depends(admin)])
def logout(response:Response):response.delete_cookie("flowpilot");return {"ok":True}
@app.get("/api/status",dependencies=[Depends(admin)])
def status():
    return {"control":engine.control(),"risk":RiskConfig(**store.get("risk:DEMO",{})).model_dump(),"orders":sorted(engine.rows(),key=lambda r:r["created_ms"],reverse=True),"credentials":{e:bool(store.get("credentials:"+e)) for e in ("DEMO","REAL")},"audit":sorted(store.prefix("audit:"),key=lambda r:r["time"],reverse=True)[:100],"auto":{"enabled":engine.control().get("auto") is True,"events":list(autotrader.events),"review_ack_ms":store.get("review_ack_ms",0)},"capabilities":{"real_trading":False,"auto_trading":"DEMO_FORWARD_TEST_UNVALIDATED","historical_DOM_backtest":False}}
class Environment(BaseModel):environment:str=Field(pattern="^(DEMO|REAL)$")
@app.post("/api/environment",dependencies=[Depends(admin)])
async def environment(p:Environment):
    await engine.stop("Environment switch requested")
    await engine.reconcile()
    if any(r["state"] not in {"EXITED","REJECTED"} for r in engine.rows()):raise HTTPException(409,"Resolve managed DEMO positions/orders before switching")
    c=engine.control();c["environment"]=p.environment;store.put("control",c);store.audit("ENVIRONMENT",p.environment)
    return c
class Credentials(Environment):
    key:str=Field(min_length=8,max_length=256)
    secret:str=Field(min_length=8,max_length=256)
@app.put("/api/credentials",dependencies=[Depends(admin)])
async def keys(p:Credentials,request:Request):
    host=request.client.host if request.client else ""
    if request.url.scheme!="https" and (not settings.allow_local_http or host not in {"127.0.0.1","::1","testclient"}):raise HTTPException(403,"Secrets require HTTPS (loopback development exception only)")
    await engine.stop("Credentials update")
    async with engine.lock:
        if p.environment=="DEMO" and any(r["state"] not in {"EXITED","REJECTED"} for r in engine.rows()):raise HTTPException(409,"Cannot replace DEMO credentials while managed orders are unresolved")
        save_credentials(p.environment,p.key,p.secret);store.audit("CREDENTIALS_SAVED",p.environment)
    return {"configured":True,"environment":p.environment}
@app.post("/api/connection",dependencies=[Depends(admin)])
async def connection(p:Environment):
    c=engine.client(p.environment)
    try:
        await c.sync_clock();a=await c.account()
        return {"environment":p.environment,"equity":a["totalMarginBalance"],"available":a["availableBalance"],"unrealized_pnl":a.get("totalUnrealizedProfit"),"positions":await c.positions(),"real_trading":False,"time":datetime.now(timezone.utc).isoformat()}
    finally:await c.close()
@app.post("/api/control/stop",dependencies=[Depends(admin)])
async def stop():await engine.stop();return engine.control()
@app.post("/api/control/resume",dependencies=[Depends(admin)])
async def resume():
    reconciled=await engine.reconcile()
    async with engine.lock:
        if reconciled.get("positions"):raise HTTPException(409,"Open account position blocks RESUME")
        if engine.control()["environment"]!="DEMO":raise HTTPException(403,"REAL read-only")
        if not store.get("credentials:DEMO"):raise HTTPException(409,"Configure DEMO credentials")
        if any(r["state"] not in {"EXITED","REJECTED"} for r in engine.rows()):raise HTTPException(409,"Resolve managed orders before RESUME")
        err=news_guard(store.get("news:DEMO"));data=market.summary()
        err=err or ("REST stale" if data["rest_stale"] else crash_guard(data["book"],data["flow"],market.candles.get(("BTCUSDT","5m"),[])))
        if err:raise HTTPException(409,err)
        c=engine.control();c.update(stopped=False,auto=False,reason="Manual DEMO test entries enabled; AUTO off");store.put("control",c);store.audit("RESUME",c["reason"])
        return c
class Confirm(BaseModel):confirm:bool=False
class AutoSwitch(Confirm):enabled:bool
@app.post("/api/control/auto",dependencies=[Depends(admin)])
async def auto_switch(p:AutoSwitch):
    c=engine.control()
    if p.enabled:
        if not p.confirm:raise HTTPException(400,"Confirm AUTO DEMO forward test")
        if c["environment"]!="DEMO":raise HTTPException(403,"AUTO is DEMO only")
        if c["stopped"]:raise HTTPException(409,"RESUME before enabling AUTO")
        if not store.get("credentials:DEMO"):raise HTTPException(409,"Configure DEMO credentials")
        err=news_guard(store.get("news:DEMO"))
        if err:raise HTTPException(409,err)
    c.update(auto=p.enabled,reason="AUTO DEMO forward test ON (unvalidated strategies)" if p.enabled else "Manual DEMO test entries enabled; AUTO off")
    store.put("control",c);store.audit("AUTO_ON" if p.enabled else "AUTO_OFF","Operator");autotrader.log("AUTO_ON" if p.enabled else "AUTO_OFF","Operator")
    return c
@app.post("/api/control/review",dependencies=[Depends(admin)])
async def review_losses(p:Confirm):
    if not p.confirm:raise HTTPException(400,"Confirm you reviewed the recent losing trades")
    now=int(time.time()*1000);store.put("review_ack_ms",now);store.audit("LOSS_REVIEW_ACK","Loss streak cleared by operator after review")
    return {"review_ack_ms":now}
@app.post("/api/control/flatten",dependencies=[Depends(admin)])
async def flatten(p:Confirm):
    if not p.confirm:raise HTTPException(400,"Confirm FLATTEN DEMO")
    return await engine.flatten()
@app.post("/api/reconcile",dependencies=[Depends(admin)])
async def reconcile():return await engine.reconcile()
@app.post("/api/orders/preview",dependencies=[Depends(admin)])
async def preview(p:Setup):return await engine.preview(p)
@app.post("/api/orders/demo",dependencies=[Depends(admin)])
async def submit(p:Setup):return await engine.submit(p)
@app.get("/api/market",dependencies=[Depends(admin)])
def market_data(symbol:str="BTCUSDT"):
    if symbol not in market.books:raise HTTPException(400,"Unsupported symbol")
    return market.summary(symbol)
@app.get("/api/signals",dependencies=[Depends(admin)])
def signals(symbol:str="BTCUSDT"):
    if symbol not in market.books:raise HTTPException(400,"Unsupported symbol")
    btc=market.summary();coin=market.summary(symbol)
    return {"symbol":symbol,"whale":{s:whales.confirmation(symbol,s) for s in ("LONG","SHORT")},**evaluate(btc["regimes"]["4h"],btc["regimes"]["1h"],coin["regimes"]["15m"],coin["regimes"]["5m"],coin["flow"],coin["book"])}
@app.put("/api/risk",dependencies=[Depends(admin)])
async def risk(p:RiskConfig):
    await engine.stop("Risk configuration changed")
    async with engine.lock:store.put("risk:DEMO",p.model_dump());store.audit("RISK_UPDATED",p.model_dump())
    return p
class Event(BaseModel):name:str=Field(min_length=1,max_length=100);time:datetime
class Calendar(BaseModel):valid_until:datetime;events:list[Event]=Field(max_length=1000)
@app.put("/api/news",dependencies=[Depends(admin)])
async def news(p:Calendar):
    if p.valid_until.tzinfo is None or any(e.time.tzinfo is None for e in p.events):raise HTTPException(400,"UTC offsets required")
    await engine.stop("News calendar update")
    store.put("news:DEMO",p.model_dump(mode="json"));store.audit("NEWS_UPDATED",p.model_dump(mode="json"));return {"guard":news_guard(store.get("news:DEMO"))}
@app.get("/api/whales",dependencies=[Depends(admin)])
def whale_dashboard():return whales.dashboard()
@app.put("/api/whales/config",dependencies=[Depends(admin)])
async def whale_config(p:WhaleConfig):
    if len({w.address.lower() for w in p.wallets})!=len(p.wallets):raise HTTPException(400,"Duplicate wallet address")
    old=whales.config()
    # Requiring confirmation changes which entries are allowed, so treat it like a risk change.
    if p.require_confirmation!=old.require_confirmation:await engine.stop("Whale confirmation mode changed")
    whales.save_config(p);store.audit("WHALE_CONFIG",{"wallets":len(p.wallets),"require_confirmation":p.require_confirmation})
    return whales.config()
class Research(BaseModel):symbol:str=Field(pattern="^[A-Z0-9]{2,20}USDT$");approve:bool
@app.post("/api/whales/research",dependencies=[Depends(admin)])
def whale_research(p:Research):
    current=[r for r in whales.research() if r["symbol"]!=p.symbol]
    if p.approve:
        s=next((x for x in whales.suggestions if x.get("symbol")==p.symbol),None)
        if not s or not s["passed"]:raise HTTPException(409,"Only a current suggestion that passed every Binance check can be approved")
        current.append({"symbol":p.symbol,"coin":s["coin"],"side":s["side"],"approved_ms":int(time.time()*1000),"checks":s["checks"]})
    store.put("whale:research",current);store.audit("WHALE_RESEARCH_"+("ADD" if p.approve else "REMOVE"),p.symbol)
    # Research watchlist only: trading symbols remain app.config.SYMBOLS and need a reviewed code change.
    return current
@app.get("/api/analytics",dependencies=[Depends(admin)])
def analytics():return {"status":"NO_VALIDATED_DATA","metrics":None,"reason":"Use backend/research scripts with recorded data; no invented ROI or win rate."}

# Same-origin dashboard avoids third-party cookie limitations on hosted deployments.
from pathlib import Path
from fastapi.staticfiles import StaticFiles
frontend_dist=Path(__file__).resolve().parents[2]/"frontend"/"dist"
if frontend_dist.is_dir():app.mount("/",StaticFiles(directory=frontend_dist,html=True),name="dashboard")
