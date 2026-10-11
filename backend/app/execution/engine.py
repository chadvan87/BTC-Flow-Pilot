import asyncio, hashlib, time
from datetime import datetime, timezone
from fastapi import HTTPException
from app.database.store import store
from app.security.auth import credentials
from app.execution.binance import Binance
from app.risk.engine import RiskConfig, plan, RiskRejected
from app.market_data.service import market
from app.filters.guards import news_guard, crash_guard
from app.notifications.telegram import alert
from app.config import SYMBOLS
from app.whales.service import whales

class Engine:
    def __init__(self,db=store,client_factory=None):
        self.db=db;self.lock=asyncio.Lock();self.factory=client_factory
    def client(self,env):
        if self.factory:return self.factory(env)
        return Binance(env,*credentials(env))
    def control(self):return self.db.get("control",{"stopped":True,"reason":"Initial STOP","environment":"DEMO"})
    async def stop(self,reason="Manual STOP"):
        c=self.control();c.update(stopped=True,reason=reason,auto=False);self.db.put("control",c)
        self.db.audit("STOP",reason);await alert("FlowPilot STOP: "+reason)
    def rows(self):return self.db.prefix("order:DEMO:")
    def write(self,row,state=None):
        if state:row["state"]=state
        row["updated"]=datetime.now(timezone.utc).isoformat()
        self.db.put("order:DEMO:"+row["id"],row)
    async def preflight(self,c,setup):
        if c.env!="DEMO":raise HTTPException(403,"REAL trading locked")
        cfg=RiskConfig(**self.db.get("risk:DEMO",{}))
        err=news_guard(self.db.get("news:DEMO"))
        if err:raise RiskRejected(err)
        # Whale context never changes size, SL or TP. It can only BLOCK, and only in require-confirmation mode.
        whale=whales.confirmation(setup.symbol,setup.side)
        if whales.config().require_confirmation and whale["effect"]!="SUPPORTS":raise RiskRejected("Whale confirmation required: "+whale["effect"]+" ("+"; ".join(whale["reasons"])+")")
        btc=market.summary();coin=market.summary(setup.symbol)
        for data in (btc,coin):
            if data["rest_stale"]:raise RiskRejected("REST market context stale")
            err=crash_guard(data["book"],data["flow"],market.candles.get(("BTCUSDT","5m"),[]))
            if err:raise RiskRejected(err)
        await c.sync_clock()
        mode=await c.request("GET","/fapi/v1/positionSide/dual",signed=True)
        multi=await c.request("GET","/fapi/v1/multiAssetsMargin",signed=True)
        if mode.get("dualSidePosition") is not False or multi.get("multiAssetsMargin") is not False:raise RiskRejected("Requires one-way, single-asset mode; change it manually on Demo")
        positions=await c.positions()
        if any(float(p["positionAmt"])!=0 for p in positions):raise RiskRejected("Account already has an open position")
        for path in ("/fapi/v1/openOrders","/fapi/v1/openAlgoOrders"):
            pending=await c.request("GET",path,signed=True)
            if isinstance(pending,dict):pending=pending.get("orders",[])
            if pending:raise RiskRejected("Account has pending orders; reconcile them first")
        configurations=await c.request("GET","/fapi/v1/symbolConfig",{"symbol":setup.symbol},True)
        sc=next((x for x in configurations if x["symbol"]==setup.symbol),{})
        if sc.get("marginType","").upper()!="ISOLATED" or int(sc.get("leverage",0))!=cfg.leverage:raise RiskRejected("Set isolated margin and 2x leverage in Binance Demo before entry")
        account=await c.account()
        if account.get("canTrade") is not True:raise RiskRejected("Account cannot trade")
        start=int(datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()*1000)
        income=await c.request("GET","/fapi/v1/income",{"startTime":start,"limit":1000},True)
        if len(income)>=1000:raise RiskRejected("Daily income pagination needed; entry blocked")
        pnl=sum(float(x["income"]) for x in income if x.get("incomeType") in {"REALIZED_PNL","COMMISSION","FUNDING_FEE"})
        equity=min(cfg.capital,float(account["totalMarginBalance"]))
        if pnl<=-equity*cfg.daily_loss_pct/100:raise RiskRejected("Daily loss circuit breaker")
        today=[r for r in self.rows() if r["created_ms"]>=start]
        if len(today)>=cfg.max_entries:raise RiskRejected("Daily entry cap reached (includes uncertain attempts)")
        # Closing-order groups, not individual partial executions; use account's most recent trades.
        outcomes=[]
        for symbol in SYMBOLS:
            trades=await c.request("GET","/fapi/v1/userTrades",{"symbol":symbol,"limit":1000},True)
            if len(trades)>=1000:raise RiskRejected("Trade pagination needed to establish loss streak")
            grouped={}
            for t in trades:
                if float(t.get("realizedPnl",0))==0:continue
                g=grouped.setdefault(t["orderId"],{"time":0,"net":0.})
                g["time"]=max(g["time"],t["time"]);g["net"]+=float(t["realizedPnl"])-float(t.get("commission",0))
            outcomes.extend(grouped.values())
        # Closes up to an operator-confirmed loss review are excluded from the streak (audit-logged in API).
        reviewed=self.db.get("review_ack_ms",0);outcomes=[x for x in outcomes if x["time"]>reviewed]
        outcomes.sort(key=lambda x:x["time"],reverse=True)
        if len(outcomes)>=2 and all(x["net"]<0 for x in outcomes[:2]):raise RiskRejected("Two consecutive losing closes: manual review required")
        info=await c.request("GET","/fapi/v1/exchangeInfo")
        symbol=next(x for x in info["symbols"] if x["symbol"]==setup.symbol)
        if symbol.get("status")!="TRADING":raise RiskRejected("Symbol not trading")
        filters={x["filterType"]:x for x in symbol["filters"]}
        quote=await c.request("GET","/fapi/v1/ticker/bookTicker",{"symbol":setup.symbol})
        if not quote.get("time") or time.time()*1000-quote["time"]>3000:raise RiskRejected("REST quote stale")
        entry=float(quote["askPrice"] if setup.side=="LONG" else quote["bidPrice"])
        mark=await c.request("GET","/fapi/v1/premiumIndex",{"symbol":setup.symbol})
        result=plan(setup,entry,coin["regimes"]["5m"]["atr"],filters,float(account["availableBalance"]),equity,cfg,mark["markPrice"])
        result["whale"]=whale
        return result,filters,cfg
    async def preview(self,setup):
        if self.control()["environment"]!="DEMO":raise HTTPException(403,"Select DEMO")
        c=self.client("DEMO")
        try:return (await self.preflight(c,setup))[0]
        finally:await c.close()
    async def submit(self,setup):
        if not setup.confirm:raise HTTPException(400,"Explicit DEMO confirmation required")
        async with self.lock:
            if self.control()["environment"]!="DEMO":raise HTTPException(403,"Select DEMO")
            prior=self.db.get("order:DEMO:"+setup.request_id)
            digest=hashlib.sha256(setup.model_dump_json(exclude={"confirm"}).encode()).hexdigest()
            if prior:
                if prior["payload_hash"]!=digest:raise HTTPException(409,"Idempotency key reused for a different setup")
                return prior
            if self.control()["stopped"]:raise HTTPException(409,"Bot is STOPPED")
            if any(r["state"] not in {"EXITED","REJECTED"} for r in self.rows()):raise RiskRejected("Unresolved managed order exists")
            c=self.client("DEMO")
            try:
                try:result,filters,cfg=await self.preflight(c,setup)
                except RiskRejected as exc:
                    await self.stop("Preflight rejected: "+str(exc));raise
                if self.control()["stopped"]:raise RiskRejected("STOP activated during preflight")
                cid="fp_"+hashlib.sha256(setup.request_id.encode()).hexdigest()[:24]
                row=dict(id=setup.request_id,payload_hash=digest,setup=setup.model_dump(),plan=result,state="CREATED",created_ms=int(time.time()*1000),entry_cid=cid,sl_cid=cid+"_sl",tp_cid=cid+"_tp",environment="DEMO")
                self.write(row,"ENTRY_PENDING")
                try:await c.market(setup.symbol,"BUY" if setup.side=="LONG" else "SELL",result["quantity"],cid)
                except Exception:
                    # Unknown execution outcome: query once, never repeat entry.
                    self.write(row,"ENTRY_UNKNOWN")
                try:
                    filled=await c.order(setup.symbol,cid)
                    if filled.get("status") in {"CANCELED","EXPIRED","REJECTED"} and float(filled.get("executedQty",0))==0:
                        row["fill"]=filled;self.write(row,"REJECTED");await self.stop("Entry terminal with zero fill");return row
                    if filled.get("status")!="FILLED":
                        # Partial fills are blocked and require explicit flatten/reconciliation.
                        self.write(row,"PARTIAL_OR_PENDING");await self.stop("Entry not completely filled");return row
                    row["fill"]=filled;self.write(row,"ENTRY_FILLED")
                    side="SELL" if setup.side=="LONG" else "BUY"
                    for kind,price,cid,tp in (("SL",setup.stop,row["sl_cid"],False),("TP",setup.target,row["tp_cid"],True)):
                        try:await c.protective(setup.symbol,side,str(price),cid,tp)
                        except Exception:pass # verify outcome by stable algo id
                        verified=await c.algo(cid)
                        self.validate_protection(verified,row,kind)
                        row[kind.lower()]=verified;self.write(row,kind+"_VERIFIED")
                    self.write(row,"PROTECTED")
                    fillprice=float(filled["avgPrice"]);slippage=(fillprice-result["entry"])*(1 if setup.side=="LONG" else -1)/result["entry"]*100
                    actual=plan(setup,fillprice,market.summary(setup.symbol)["regimes"]["5m"]["atr"],filters,1e9,cfg.capital,cfg)
                    # Compare actual filled quantity, not a newly smaller theoretical size.
                    if float(filled["executedQty"])*actual["risk_usdt"]/float(actual["quantity"])>actual["risk_budget"]+1e-8 or slippage>cfg.slippage_pct:raise RiskRejected("Actual fill breaches risk/slippage limits")
                    await alert("DEMO entry protected: "+setup.symbol+" "+setup.side+" ("+setup.strategy+")")
                except Exception as e:
                    row["error"]=type(e).__name__;self.write(row,"UNPROTECTED_OR_UNKNOWN")
                    await self.stop("Protection/fill validation failed: inspect Binance and use FLATTEN DEMO")
                    # Avoid blindly flattening an ambiguous entry; explicit flatten reconciles position first.
                return row
            finally:await c.close()
    @staticmethod
    def validate_protection(order,row,kind):
        s=row["setup"];price=s["stop" if kind=="SL" else "target"]
        expected="STOP_MARKET" if kind=="SL" else "TAKE_PROFIT_MARKET"
        valid=order.get("algoStatus")=="NEW" and order.get("symbol")==s["symbol"] and order.get("side")==("SELL" if s["side"]=="LONG" else "BUY") and order.get("positionSide")=="BOTH" and str(order.get("closePosition")).lower()=="true" and order.get("workingType")=="MARK_PRICE" and order.get("orderType",order.get("type"))==expected and float(order.get("triggerPrice",0))==price and order.get("clientAlgoId")==row[kind.lower()+"_cid"]
        if not valid:raise RiskRejected("Protective order attributes/status not verified")
    async def reconcile(self):
        async with self.lock:
            if not self.db.get("credentials:DEMO") and not self.factory:return {"status":"NO_CREDENTIALS"}
            c=self.client("DEMO")
            try:
                await c.sync_clock();positions=await c.positions()
                active={p["symbol"]:p for p in positions if float(p["positionAmt"])!=0}
                managed=set()
                for row in self.rows():
                    if row["state"] in {"EXITED","REJECTED"}:continue
                    symbol=row["setup"]["symbol"];managed.add(symbol)
                    try:
                        entry=await c.order(symbol,row["entry_cid"])
                        row["fill"]=entry
                        if entry.get("status") in {"CANCELED","EXPIRED","REJECTED"} and float(entry.get("executedQty",0))==0 and symbol not in active:
                            self.write(row,"REJECTED");continue
                        if entry.get("status")!="FILLED":
                            self.write(row,"PARTIAL_OR_PENDING");await self.stop("Unresolved entry after reconciliation");continue
                        if symbol not in active:
                            self.write(row,"EXITED")
                            await self.cleanup(c,row);continue
                        amt=float(active[symbol]["positionAmt"])
                        if (amt>0)!=(row["setup"]["side"]=="LONG") or abs(amt)>float(entry["executedQty"])+1e-9:raise RiskRejected("Position ownership/quantity mismatch")
                        for kind in ("SL","TP"):
                            o=await c.algo(row[kind.lower()+"_cid"]);self.validate_protection(o,row,kind);row[kind.lower()]=o
                        self.write(row,"PROTECTED")
                    except Exception as e:
                        row["error"]=type(e).__name__;self.write(row,"UNPROTECTED_OR_UNKNOWN");await self.stop("Reconciliation requires manual inspection")
                if set(active)-managed:await self.stop("Unmanaged Binance position found")
                return {"status":"RECONCILED","positions":list(active.values())}
            finally:await c.close()
    async def cleanup(self,c,row):
        for cid in (row["sl_cid"],row["tp_cid"]):
            try:
                o=await c.algo(cid)
                if o.get("algoStatus")=="NEW":await c.request("DELETE","/fapi/v1/algoOrder",{"clientAlgoId":cid},True)
                o=await c.algo(cid)
                if o.get("algoStatus")=="NEW":raise RiskRejected("Cancellation not verified")
            except Exception as e:
                row["cleanup_error"]=type(e).__name__;self.write(row,"CLEANUP_REQUIRED");await self.stop("Protective cleanup not verified")
    async def flatten(self):
        await self.stop("FLATTEN DEMO requested")
        async with self.lock:
            c=self.client("DEMO")
            try:
                await c.sync_clock()
                mode=await c.request("GET","/fapi/v1/positionSide/dual",signed=True)
                if mode.get("dualSidePosition") is not False:raise RiskRejected("Cannot flatten hedge-mode account")
                positions=await c.positions()
                managed={r["setup"]["symbol"] for r in self.rows() if r["state"] not in {"EXITED","REJECTED"}}
                for p in positions:
                    qty=float(p["positionAmt"])
                    if p["symbol"] not in managed or not qty:continue
                    cid="fp_flat_"+hashlib.sha256((p["symbol"]+str(p.get("updateTime"))+str(qty)).encode()).hexdigest()[:20]
                    try:await c.market(p["symbol"],"SELL" if qty>0 else "BUY",format(abs(qty),'.12f').rstrip('0').rstrip('.'),cid,True)
                    except Exception:pass # reconcile; no blind retry
                # Cancel any still-pending managed entry before cleanup/flat verification.
                for row in self.rows():
                    if row["state"] in {"EXITED","REJECTED"}:continue
                    try:
                        o=await c.order(row["setup"]["symbol"],row["entry_cid"])
                        if o.get("status") in {"NEW","PARTIALLY_FILLED"}:
                            await c.request("DELETE","/fapi/v1/order",{"symbol":row["setup"]["symbol"],"origClientOrderId":row["entry_cid"]},True)
                            o=await c.order(row["setup"]["symbol"],row["entry_cid"])
                            if o.get("status") in {"NEW","PARTIALLY_FILLED"}:raise RiskRejected("Pending entry cancellation unverified")
                    except Exception:raise RiskRejected("Entry state unresolved; protective orders retained")
                remaining=[p for p in await c.positions() if p["symbol"] in managed and float(p["positionAmt"])!=0]
                if remaining:raise RiskRejected("FLATTEN not verified; protection retained")
                for row in self.rows():
                    if row["state"] not in {"EXITED","REJECTED"}:
                        self.write(row,"EXITED");await self.cleanup(c,row)
                if any(r["state"]=="CLEANUP_REQUIRED" for r in self.rows()):raise RiskRejected("Flat confirmed but cleanup unresolved")
                self.db.audit("FLATTEN_DEMO","Managed positions flat, pending entries canceled and protection cleanup verified")
                return {"flat_verified":True}
            finally:await c.close()
engine=Engine()
