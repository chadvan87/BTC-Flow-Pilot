"""Whale data collection (Hyperliquid) and Whale Confirmation views.
Sources (official docs, checked 2026-10-11): POST https://api.hyperliquid.xyz/info clearinghouseState (weight 2),
userFillsByTime (weight 20 + per-item), metaAndAssetCtxs (20); REST budget 1200/min/IP, we self-limit to 600.
WebSocket wss://api.hyperliquid.xyz/ws userFills: first message isSnapshot=true; max 10 unique users per IP, so
only the first 10 configured wallets stream and the rest use REST polling. Server drops connections silent for
60s, so we ping every 30s. All timestamps are UTC epoch ms.
Rules: the first clearinghouseState of a wallet is its BASELINE; fills at or before it are never new actions.
Fills are deduplicated by trade id. Every poll reconciles signed position size against fills; if fills are
missing even after a REST backfill, the size difference (never a USD-value difference) becomes a
'snapshot_reconcile' action.
"""
import asyncio, json, time
from collections import deque
from decimal import Decimal
import httpx, websockets
from app.database.store import store
from app.execution.binance import Binance
from app.config import SYMBOLS
from app.whales.config import WhaleConfig, MAX_WINDOW_MS
from app.whales.actions import normalize, signed, aggregate, actions, from_binance, to_binance
from app.whales.bias import coin_bias, cohort, confirmation, wallet_weight
from app.whales import discovery

API="https://api.hyperliquid.xyz";WS_URL="wss://api.hyperliquid.xyz/ws"
WS_MAX_USERS=10;FLUSH_EVERY_S=30;RETENTION_MS=24*3600_000;MAX_FILLS=4000;HISTORY_EVERY_MS=6*3600_000;DISCOVERY_EVERY_S=600;PAGE_LIMIT=5

class WeightLimiter:
    def __init__(self,per_minute=600,clock=time.monotonic,sleep=asyncio.sleep):
        self.cap,self.clock,self.sleep,self.used=per_minute,clock,sleep,deque()
    async def acquire(self,weight):
        weight=min(weight,self.cap)
        while True:
            now=self.clock()
            while self.used and now-self.used[0][0]>=60:self.used.popleft()
            if sum(w for _,w in self.used)+weight<=self.cap:self.used.append((now,weight));return
            await self.sleep(max(.5,60-(now-self.used[0][0])))

class WhaleService:
    def __init__(self,db=store,transport=None,clock=lambda:int(time.time()*1000)):
        self.db,self.transport,self.now=db,transport,clock
        self.limiter=WeightLimiter();self.http=None;self.tasks=[];self.running=False
        self.ws_connected=False;self.ws_users=[];self.ws_last_ms=None
        self.context={};self.context_ms=None;self.suggestions=[];self.discovery_at=0.;self.errors={}
        # Fill histories live in memory and are flushed periodically: re-reading/re-writing a ~1 MB blob per
        # incoming fill would cost gigabytes of database transfer per day on a hosted database.
        self.cache={};self.dirty=set();self.flushed=time.monotonic()
    # ---------- persistence ----------
    def config(self):return WhaleConfig(**self.db.get("whale:config",{}))
    def save_config(self,cfg):self.db.put("whale:config",cfg.model_dump())
    def state(self,user):return self.db.get("whale:wallet:"+user,{})
    def put_state(self,user,st):self.db.put("whale:wallet:"+user,st)
    def fills(self,user):
        if user not in self.cache:self.cache[user]=self.db.get("whale:fills:"+user,[])
        return self.cache[user]
    def flush(self,force=False):
        if not self.dirty or (not force and time.monotonic()-self.flushed<FLUSH_EVERY_S):return
        for user in list(self.dirty):
            rows=self.cache.get(user,[]);self.db.put("whale:fills:"+user,rows)
            # last_fill_ms only advances with persisted fills, so a crash before flush is recovered by REST backfill.
            st=self.state(user);st["last_fill_ms"]=max([st.get("last_fill_ms") or 0]+[f["time"] for f in rows]);self.put_state(user,st)
        self.dirty.clear();self.flushed=time.monotonic()
    def synthetic(self,user):return self.db.get("whale:synthetic:"+user,[])
    def research(self):return self.db.get("whale:research",[])
    # ---------- ingestion ----------
    def ingest(self,user,raw,source):
        user=user.lower();st=self.state(user);baseline=st.get("baseline_ms")
        if baseline is None:return 0 # no baseline snapshot yet: nothing can count as a new trade
        keep=self.now()-RETENTION_MS;existing=self.fills(user);seen={f["tid"] for f in existing};new=[]
        for f in raw:
            if ":" in f.get("coin","") or f.get("coin","").startswith("@"):continue # spot / HIP-3: outside default perp dex snapshot
            n=normalize(user,f)
            if n["time"]<=baseline or n["time"]<keep or n["tid"] in seen or n["side"] not in {"B","A"}:continue
            seen.add(n["tid"]);n["source"]=source;new.append(n)
        if new:
            self.cache[user]=([f for f in existing if f["time"]>=keep]+new)[-MAX_FILLS:];self.dirty.add(user);self.flush()
        return len(new)
    @staticmethod
    def positions(snapshot):
        out={}
        for item in snapshot.get("assetPositions",[]):
            p=item["position"];szi=float(p["szi"])
            if szi:out[p["coin"]]={"szi":szi,"value":abs(float(p["positionValue"])),"entry":float(p.get("entryPx") or 0)}
        return out
    def mismatches(self,user,snapshot):
        """Coins whose signed size moved differently from the fills seen since the previous snapshot."""
        st=self.state(user);prev=st.get("snapshot") or {};t0,t1=st.get("snapshot_time",0),int(snapshot["time"])
        expected={c:Decimal(str(p["szi"])) for c,p in prev.items()}
        for f in self.fills(user):
            if t0<f["time"]<=t1:expected[f["coin"]]=expected.get(f["coin"],Decimal(0))+signed(f)
        actual={c:Decimal(str(p["szi"])) for c,p in self.positions(snapshot).items()}
        out={}
        for c in set(expected)|set(actual):
            e,a=expected.get(c,Decimal(0)),actual.get(c,Decimal(0))
            if abs(e-a)>Decimal("1e-9")+abs(a)*Decimal("1e-6"):out[c]=(e,a)
        return out
    def apply_snapshot(self,user,snapshot,missing):
        st=self.state(user);now=self.now();pos=self.positions(snapshot)
        if st.get("baseline_ms") is None:
            # Initial snapshot = baseline only; existing positions are context, not new trades.
            st.update(baseline_ms=int(snapshot["time"]))
        elif missing:
            syn=[e for e in self.synthetic(user) if e["time"]>=now-RETENTION_MS]
            for coin,(e,a) in missing.items():
                mark=self.context.get(coin,{}).get("mark") or (pos.get(coin,{}).get("value",0)/abs(float(a)) if a else None)
                syn.append({"user":user,"coin":coin,"start":str(e),"end":str(a),"time":int(snapshot["time"]),"qty":str(abs(a-e)),
                            "notional":str(abs(a-e)*Decimal(str(mark or 0))),"tids":[],"source":"snapshot_reconcile"})
            self.db.put("whale:synthetic:"+user,syn)
        acct=float(snapshot.get("marginSummary",{}).get("accountValue") or 0)
        st.update(snapshot=pos,snapshot_time=int(snapshot["time"]),snapshot_ms=now,account_value=acct or None,error=None)
        self.put_state(user,st)
    # ---------- REST ----------
    async def info(self,body,weight):
        await self.limiter.acquire(weight)
        if self.http is None:self.http=httpx.AsyncClient(base_url=API,timeout=10,transport=self.transport)
        for attempt in range(3):
            r=await self.http.post("/info",json=body)
            if r.status_code==429:await asyncio.sleep(5*2**attempt);continue
            r.raise_for_status();data=r.json()
            if isinstance(data,list) and len(data)>=20:await self.limiter.acquire(len(data)//20) # per-item weight (amount undocumented: 1 per 20 assumed)
            return data
        raise RuntimeError("Hyperliquid rate limited")
    async def backfill(self,user,start):
        for _ in range(PAGE_LIMIT):
            rows=await self.info({"type":"userFillsByTime","user":user,"startTime":int(start)},20)
            self.ingest(user,rows,"rest")
            # Page limit is documented inconsistently (500 vs 2000); page whenever a page might be truncated.
            if len(rows)<500:break
            start=max(int(f["time"]) for f in rows)
        st=self.state(user);st["fills_poll_ms"]=self.now();self.put_state(user,st)
    async def refresh_wallet(self,user,rest_fills):
        snap=await self.info({"type":"clearinghouseState","user":user},2)
        st=self.state(user)
        if st.get("baseline_ms") is not None:
            if rest_fills:await self.backfill(user,st.get("last_fill_ms") or st["baseline_ms"]+1)
            missing=self.mismatches(user,snap)
            if missing:
                await self.backfill(user,st.get("snapshot_time",st["baseline_ms"])+1);missing=self.mismatches(user,snap)
        else:missing={}
        self.apply_snapshot(user,snap,missing)
        st=self.state(user)
        if self.config().history_factor and self.now()-st.get("history_ms",0)>=HISTORY_EVERY_MS and st.get("account_value"):
            rows=await self.info({"type":"userFills","user":user},20)
            realized=sum(float(f.get("closedPnl") or 0)-float(f.get("fee") or 0) for f in rows)
            # Heuristic quality factor from recent realised PnL vs equity. NOT a win probability.
            st.update(history=max(.5,min(1.5,1+2*realized/st["account_value"])),history_realized=realized,history_fills=len(rows),history_ms=self.now())
            self.put_state(user,st)
    async def refresh_context(self):
        meta,ctxs=await self.info({"type":"metaAndAssetCtxs"},20)
        self.context={u["name"]:{"mark":float(c["markPx"]) if c.get("markPx") else None,"funding":float(c["funding"]) if c.get("funding") else None,
                                 "open_interest":float(c["openInterest"]) if c.get("openInterest") else None} for u,c in zip(meta["universe"],ctxs)}
        self.context_ms=self.now()
    async def refresh_discovery(self,cfg):
        if time.monotonic()-self.discovery_at<DISCOVERY_EVERY_S:return
        self.discovery_at=time.monotonic();rows=self.wallet_rows(cfg)
        exclude={from_binance(s) for s in SYMBOLS}|{r["coin"] for r in self.research()}
        found=discovery.candidates(self.all_actions(cfg),rows,cfg,exclude,self.now());out=[]
        b=Binance()
        try:
            for c in found:
                try:out.append(await discovery.verify(c,b,cfg,self.context.get(c["coin"],{}).get("mark")))
                except Exception as e:out.append({**c,"symbol":to_binance(c["coin"])[0],"checks":[{"name":"Verification","ok":False,"detail":type(e).__name__}],"passed":False})
        finally:await b.close()
        self.suggestions=out
    # ---------- loops ----------
    async def poll_loop(self):
        while True:
            cfg=self.config();started=time.monotonic()
            try:await self.refresh_context();self.errors.pop("context",None)
            except Exception as e:self.errors["context"]=type(e).__name__
            streamed=set(self.ws_users) if self.ws_connected else set()
            for w in cfg.wallets:
                user=w.address.lower()
                try:await self.refresh_wallet(user,rest_fills=user not in streamed)
                except asyncio.CancelledError:raise
                except Exception as e:st=self.state(user);st["error"]=type(e).__name__;self.put_state(user,st)
            try:await self.refresh_discovery(cfg);self.errors.pop("discovery",None)
            except Exception as e:self.errors["discovery"]=type(e).__name__
            self.flush(force=True)
            await asyncio.sleep(max(5,cfg.poll_seconds-(time.monotonic()-started)))
    def ws_targets(self):return [w.address.lower() for w in self.config().wallets][:WS_MAX_USERS]
    def handle_ws(self,msg):
        data=json.loads(msg);self.ws_last_ms=self.now()
        if data.get("channel")=="userFills":
            # Snapshot messages (isSnapshot=true) go through the same baseline + tid dedupe, which recovers fills
            # missed while disconnected without double counting.
            d=data["data"];return self.ingest(d["user"],d.get("fills",[]),"ws")
        return 0
    async def ws_loop(self):
        backoff=1
        while True:
            users=self.ws_targets()
            if not users:await asyncio.sleep(10);continue
            try:
                async with websockets.connect(WS_URL,ping_interval=None,max_queue=1024) as ws:
                    for u in users:await ws.send(json.dumps({"method":"subscribe","subscription":{"type":"userFills","user":u}}))
                    self.ws_users,self.ws_connected,backoff=users,True,1;self.errors.pop("ws",None)
                    while self.ws_targets()==users:
                        try:msg=await asyncio.wait_for(ws.recv(),30)
                        except asyncio.TimeoutError:await ws.send(json.dumps({"method":"ping"}));continue
                        self.handle_ws(msg)
            except asyncio.CancelledError:raise
            except Exception as e:self.errors["ws"]=type(e).__name__
            finally:self.ws_connected=False
            await asyncio.sleep(backoff);backoff=min(backoff*2,60)
    async def start(self):
        self.running=True;self.tasks=[asyncio.create_task(self.poll_loop()),asyncio.create_task(self.ws_loop())]
    async def close(self):
        self.flush(force=True)
        for t in self.tasks:t.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True);self.running=False
        if self.http:await self.http.aclose();self.http=None
    # ---------- views ----------
    def wallet_rows(self,cfg):
        now=self.now();stale=cfg.stale_after_s*1000;streamed=set(self.ws_users) if self.ws_connected else set();rows=[]
        for w in cfg.wallets:
            user=w.address.lower();st=self.state(user)
            fills_ok=user in streamed or (st.get("fills_poll_ms") is not None and now-st["fills_poll_ms"]<=stale)
            snap_ok=st.get("snapshot_ms") is not None and now-st["snapshot_ms"]<=stale
            pos=st.get("snapshot") or {}
            rows.append({"address":user,"label":w.label,"cluster":w.cluster,"quality":w.quality,"history":st.get("history",1.0),
                         "fresh":bool(self.running and snap_ok and fills_ok and st.get("baseline_ms") is not None),"source":"websocket" if user in streamed else "rest",
                         "snapshot_ms":st.get("snapshot_ms"),"age_s":round((now-st["snapshot_ms"])/1000,1) if st.get("snapshot_ms") else None,
                         "account_value":st.get("account_value"),"positions":pos,"gross_usd":sum(p["value"] for p in pos.values()),
                         "error":st.get("error"),"baseline_ms":st.get("baseline_ms"),"history_realized":st.get("history_realized")})
            rows[-1]["weight"]=wallet_weight(rows[-1],cfg)
        return rows
    def all_actions(self,cfg,horizon_ms=MAX_WINDOW_MS):
        now=self.now();out=[]
        for w in cfg.wallets:
            user=w.address.lower()
            recent=[f for f in self.fills(user) if now-f["time"]<=horizon_ms+cfg.merge_window_s*1000]
            events=aggregate(recent,cfg.merge_window_s*1000)
            events+=[{**e,"start":Decimal(e["start"]),"end":Decimal(e["end"]),"qty":Decimal(e["qty"]),"notional":Decimal(e["notional"])}
                     for e in self.synthetic(user) if now-e["time"]<=horizon_ms]
            for e in events:out.extend(a for a in actions(e) if now-a["time"]<=horizon_ms)
        return sorted(out,key=lambda a:a["time"],reverse=True)
    def bias(self,coin,cfg=None,rows=None,acts=None):
        cfg=cfg or self.config()
        return coin_bias(coin,rows if rows is not None else self.wallet_rows(cfg),acts if acts is not None else self.all_actions(cfg),cfg,self.now(),self.running)
    def confirmation(self,symbol,side):
        return {**confirmation(self.bias(from_binance(symbol)),side),"coin":from_binance(symbol)}
    def dashboard(self):
        cfg=self.config();rows=self.wallet_rows(cfg);acts=self.all_actions(cfg);now=self.now()
        timeline=self.all_actions(cfg,RETENTION_MS)[:100]
        labels={w["address"]:(w["label"] or w["address"][:8]+"…"+w["address"][-4:]) for w in rows}
        watch={from_binance(s):("TRADING",s) for s in SYMBOLS}|{r["coin"]:("RESEARCH",r["symbol"]) for r in self.research()}
        held={}
        for w in rows:
            for c,p in w["positions"].items():held[c]=held.get(c,0)+p["value"]
        coins=list(watch)+[c for c,_ in sorted(held.items(),key=lambda x:-x[1]) if c not in watch][:15]
        table=[]
        for c in coins:
            b=coin_bias(c,rows,acts,cfg,now,self.running)
            table.append({"coin":c,"symbol":watch.get(c,("OTHER",to_binance(c)[0]))[1],"watch":watch.get(c,("OTHER",))[0],"bias":b,
                          "cohort":cohort(c,rows,acts,cfg,now,self.context.get(c,{}).get("mark")),"context":self.context.get(c)})
        return {"label":"Monitored wallets only — not whole-market positioning","hypothesis":"All thresholds and weights are unvalidated hypotheses. Scores are not win probabilities.",
                "running":self.running,"config":cfg.model_dump(),"ws":{"connected":self.ws_connected,"users":len(self.ws_users),"last_message_ms":self.ws_last_ms,"max_users":WS_MAX_USERS},
                "context_ms":self.context_ms,"errors":self.errors,"wallets":rows,"coins":table,
                "timeline":[{**a,"wallet":labels.get(a["user"],a["user"])} for a in timeline],
                "suggestions":self.suggestions,"research":self.research(),"now_ms":now}

whales=WhaleService()
