"""Automatic DEMO entries (experimental forward test). Never REAL.
Runs only while control is RUNNING, environment is DEMO and the separate auto switch is on. STOP and restart
turn the switch off and it never re-enables itself. Every candidate first goes through a dry engine.preview()
(identical preflight, no order, no STOP) and is submitted through the normal engine.submit() only if that passes,
so all guards, idempotency, protection verification and STOP-on-uncertainty behaviour are unchanged.
"""
import asyncio, hashlib, time
from collections import deque
from datetime import datetime, timezone
from fastapi import HTTPException
from app.config import SYMBOLS
from app.execution.binance import Binance
from app.filters.guards import news_guard
from app.risk.engine import Setup, RiskRejected
from app.strategies.auto import checklist_setup, retest_setup
from app.notifications.telegram import alert
from app.whales.service import whales

INTERVAL=20; COOLDOWN=900; FILTER_TTL=3600
# Account-level blocks that a manual review must clear; auto switches itself off instead of retrying.
REVIEW_BLOCKS=("Two consecutive losing closes",)

class AutoTrader:
    def __init__(self,engine,market,db,whale=whales):
        self.engine,self.market,self.db,self.whale=engine,market,db,whale
        self.cooldown={};self.ticks={};self.ticks_at=0.;self.events=deque(maxlen=50)
    def log(self,event,detail):
        self.events.appendleft({"time":datetime.now(timezone.utc).isoformat(),"event":event,"detail":detail})
    def active(self):
        c=self.engine.control()
        return not c["stopped"] and c.get("auto") is True and c["environment"]=="DEMO"
    async def disable(self,reason):
        c=self.engine.control();c.update(auto=False);self.db.put("control",c)
        self.db.audit("AUTO_OFF",reason);self.log("AUTO_OFF",reason);await alert("FlowPilot AUTO OFF: "+reason)
    async def load_ticks(self):
        if self.ticks and time.monotonic()-self.ticks_at<FILTER_TTL:return
        c=Binance()
        try:info=await c.request("GET","/fapi/v1/exchangeInfo")
        finally:await c.close()
        self.ticks={x["symbol"]:next(f["tickSize"] for f in x["filters"] if f["filterType"]=="PRICE_FILTER") for x in info["symbols"] if x["symbol"] in SYMBOLS}
        self.ticks_at=time.monotonic()
    def candidates(self):
        btc=self.market.summary()
        for symbol in SYMBOLS:
            if symbol not in self.ticks:continue
            coin=self.market.summary(symbol);c15=self.market.candles.get((symbol,"15m"),[])
            for rule in (checklist_setup,retest_setup):
                found=rule(btc,coin,c15,self.ticks[symbol])
                if found:yield symbol,found
    async def step(self):
        if not self.active():return None
        # One managed trade at a time; preflight also blocks on any open position or pending order.
        if any(r["state"] not in {"EXITED","REJECTED"} for r in self.engine.rows()):return None
        if news_guard(self.db.get("news:DEMO")):return None
        await self.load_ticks()
        now=time.monotonic()
        # Whale bias only re-orders setups that already qualified on trend/structure/order flow; it never creates,
        # resizes or re-prices one. Stable sort keeps rule order (A before B, watchlist order) on ties.
        ranked=sorted(((s,c,self.whale.confirmation(s,c["side"])) for s,c in self.candidates()),key=lambda x:-x[2]["conviction"])
        for symbol,cand,whale in ranked:
            # Stable per signal: the same setup can never be submitted twice.
            rid="auto_"+hashlib.sha256(f'{cand["strategy"]}|{symbol}|{cand["side"]}|{cand["signal_ms"]}'.encode()).hexdigest()[:20]
            if self.db.get("order:DEMO:"+rid) or self.cooldown.get(rid,0)>now:continue
            setup=Setup(symbol=symbol,side=cand["side"],ideal=cand["ideal"],stop=cand["stop"],target=cand["target"],request_id=rid,strategy=cand["strategy"])
            label=f'{cand["strategy"]} {symbol} {cand["side"]} entry~{cand["ideal"]:g} SL {cand["stop"]:g} TP {cand["target"]:g} | whale {whale["effect"]}'
            try:await self.engine.preview(setup)
            except Exception as e:
                reason=e.detail if isinstance(e,HTTPException) else str(e) if isinstance(e,RiskRejected) else type(e).__name__
                self.cooldown[rid]=now+COOLDOWN;self.log("AUTO_SKIP",label+" | "+str(reason))
                if any(str(reason).startswith(b) for b in REVIEW_BLOCKS):
                    await self.disable(str(reason)+"; review losses, clear the streak, then re-enable AUTO");return None
                continue
            if not self.active():return None
            self.db.audit("AUTO_SIGNAL",label);self.log("AUTO_SIGNAL",label)
            try:row=await self.engine.submit(setup.model_copy(update={"confirm":True}))
            except (RiskRejected,HTTPException) as e:
                # submit() has already STOPPED with its own reason where required; keep that reason.
                self.log("AUTO_REJECTED",label+" | "+str(e.detail if isinstance(e,HTTPException) else e));return None
            self.log("AUTO_ENTRY",label+" | state "+row["state"])
            return row
        return None
    async def run(self):
        while True:
            await asyncio.sleep(INTERVAL)
            try:await self.step()
            except Exception as e:
                # Fail closed: unexpected errors stop the bot (which also turns auto off).
                self.log("AUTO_ERROR",type(e).__name__);await self.engine.stop("Auto trader error: "+type(e).__name__)
