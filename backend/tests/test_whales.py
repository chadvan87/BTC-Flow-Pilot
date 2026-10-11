import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.database.store import Store
from app.whales.config import WhaleConfig, WalletConfig
from app.whales.actions import classify, aggregate, actions, normalize, to_binance, from_binance
from app.whales.bias import coin_bias, cohort, confirmation, cap_shares
from app.whales.service import WhaleService, WeightLimiter
from app.whales import discovery
from app.risk.engine import RiskRejected, Setup

NOW=1_800_000_000_000;MIN=60_000
A1="0x"+"a"*40;A2="0x"+"b"*40;A3="0x"+"c"*40;A4="0x"+"d"*40

def fill(coin="BTC",side="B",sz="1",start="0",t=NOW-MIN,tid=1,oid=1,twap=None,px="100"):
    return {"coin":coin,"side":side,"sz":sz,"startPosition":start,"time":t,"tid":tid,"oid":oid,"twapId":twap,"px":px,"closedPnl":"0","fee":"0"}
def kinds(acts):return [(a["action"],a["side"],a["qty"]) for a in acts]
def acts_of(fills,window=300_000):return [a for e in aggregate([normalize(A1,f) for f in fills],window) for a in actions(e)]

# ---------- classification ----------
@pytest.mark.parametrize("start,end,expected",[
    (0,2,[("OPEN","LONG",2)]),(2,3,[("ADD","LONG",1)]),(3,1,[("REDUCE","LONG",2)]),(1,0,[("CLOSE","LONG",1)]),
    (0,-2,[("OPEN","SHORT",2)]),(-2,-1,[("REDUCE","SHORT",1)]),(-1,0,[("CLOSE","SHORT",1)]),(2,2,[])])
def test_classify_transitions(start,end,expected):
    assert [(a,s,float(q)) for a,s,q in classify(start,end)]==expected

def test_flip_splits_into_close_and_open():
    assert kinds(acts_of([fill(side="A",sz="1.5",start="0.5")]))==[("CLOSE","LONG",.5),("OPEN","SHORT",1.0)]
    assert kinds(acts_of([fill(side="B",sz="3",start="-1")]))==[("CLOSE","SHORT",1.0),("OPEN","LONG",2.0)]

def test_partial_fills_of_one_order_are_one_action():
    fs=[fill(sz="0.4",start="0",tid=1),fill(sz="0.3",start="0.4",tid=2,t=NOW-MIN+5),fill(sz="0.3",start="0.7",tid=3,t=NOW-MIN+9)]
    a=acts_of(fs);assert kinds(a)==[("OPEN","LONG",1.0)] and a[0]["fills"]==3

def test_twap_slices_merge_even_beyond_window():
    fs=[fill(sz="1",start=str(i),tid=i+1,oid=100+i,twap=7,t=NOW-60*MIN+i*20*MIN) for i in range(3)]
    assert kinds(acts_of(fs,window=60_000))==[("OPEN","LONG",3.0)]

def test_opposite_direction_fills_are_separate_actions():
    fs=[fill(sz="1",start="0",tid=1,oid=1),fill(side="A",sz="1",start="1",tid=2,oid=2,t=NOW-MIN+1000)]
    assert kinds(acts_of(fs))==[("OPEN","LONG",1.0),("CLOSE","LONG",1.0)]

def test_action_notional_is_traded_size_times_traded_price():
    a=acts_of([fill(sz="2",px="50")])[0];assert a["notional"]==100 and a["px"]==50

# ---------- service: baseline, dedupe, reconcile ----------
def snapshot(t,positions,acct="1000"):
    return {"time":t,"marginSummary":{"accountValue":acct},"assetPositions":[{"position":{"coin":c,"szi":str(s),"positionValue":str(v),"entryPx":"100"}} for c,s,v in positions]}

@pytest.fixture
def svc():
    s=WhaleService(db=Store("sqlite:///:memory:"),clock=lambda:NOW);s.running=True
    s.save_config(WhaleConfig(wallets=[WalletConfig(address=A1)],history_factor=False));return s

def test_no_fill_counts_before_baseline_snapshot(svc):
    assert svc.ingest(A1,[fill()],"ws")==0

def test_initial_snapshot_is_baseline_not_trades(svc):
    svc.apply_snapshot(A1,snapshot(NOW-10*MIN,[("BTC",5,500)]),{})
    assert svc.all_actions(svc.config())==[] and svc.state(A1)["baseline_ms"]==NOW-10*MIN
    assert svc.ingest(A1,[fill(t=NOW-11*MIN)],"rest")==0 # pre-baseline history is ignored

def test_fills_deduplicated_across_ws_and_rest(svc):
    svc.apply_snapshot(A1,snapshot(NOW-10*MIN,[]),{})
    assert svc.ingest(A1,[fill(tid=9)],"ws")==1 and svc.ingest(A1,[fill(tid=9)],"rest")==0
    assert len(svc.all_actions(svc.config()))==1

def test_ws_snapshot_on_reconnect_recovers_missed_fills_once(svc):
    svc.apply_snapshot(A1,snapshot(NOW-10*MIN,[]),{});svc.ingest(A1,[fill(tid=1)],"ws")
    msg={"channel":"userFills","data":{"isSnapshot":True,"user":A1,"fills":[fill(tid=0,t=NOW-20*MIN),fill(tid=1),fill(tid=2,start="1",t=NOW-30_000)]}}
    assert svc.handle_ws(json.dumps(msg))==1 # only the missed post-baseline fill

def test_price_only_notional_change_creates_no_action(svc):
    svc.apply_snapshot(A1,snapshot(NOW-10*MIN,[("BTC",2,200)]),{})
    later=snapshot(NOW-MIN,[("BTC",2,300)]) # price +50%, same signed size
    assert svc.mismatches(A1,later)=={}
    svc.apply_snapshot(A1,later,{})
    assert svc.all_actions(svc.config())==[]
    rows=svc.wallet_rows(svc.config())
    assert cohort("BTC",[{**r,"fresh":True} for r in rows],[],svc.config(),NOW,150)["exposure_change"]["1h"]=={"long_usd":0,"short_usd":0}

def mock_transport(fills):
    def handler(request):
        body=json.loads(request.content)
        if body["type"]=="userFillsByTime":return httpx.Response(200,json=fills)
        return httpx.Response(200,json=snapshot(NOW-MIN,[("BTC",3,300)]))
    return httpx.MockTransport(handler)

async def test_missing_fills_backfilled_by_rest(svc):
    svc.apply_snapshot(A1,snapshot(NOW-10*MIN,[("BTC",2,200)]),{})
    svc.transport=mock_transport([fill(sz="1",start="2",tid=5,t=NOW-5*MIN)])
    await svc.refresh_wallet(A1,rest_fills=False)
    assert kinds(svc.all_actions(svc.config()))==[("ADD","LONG",1.0)] and svc.synthetic(A1)==[]

async def test_unexplained_size_change_becomes_reconcile_action(svc):
    svc.apply_snapshot(A1,snapshot(NOW-10*MIN,[("BTC",2,200)]),{});svc.context={"BTC":{"mark":100}}
    svc.transport=mock_transport([])
    await svc.refresh_wallet(A1,rest_fills=False)
    a=svc.all_actions(svc.config());assert kinds(a)==[("ADD","LONG",1.0)] and a[0]["source"]=="snapshot_reconcile" and a[0]["notional"]==100

async def test_rate_limit_429_retries():
    calls=[]
    def handler(request):
        calls.append(1);return httpx.Response(429) if len(calls)==1 else httpx.Response(200,json={"ok":1})
    s=WhaleService(db=Store("sqlite:///:memory:"),transport=httpx.MockTransport(handler))
    import app.whales.service as mod
    orig=mod.asyncio.sleep
    async def fast(_):pass
    mod.asyncio.sleep=fast
    try:assert await s.info({"type":"x"},2)=={"ok":1} and len(calls)==2
    finally:mod.asyncio.sleep=orig;await s.close()

async def test_weight_limiter_waits_when_budget_used():
    t=[0.];slept=[]
    async def sleep(s):slept.append(s);t[0]+=s
    lim=WeightLimiter(100,clock=lambda:t[0],sleep=sleep)
    await lim.acquire(80);await lim.acquire(30)
    assert slept and t[0]>=60

def test_stale_wallet_is_not_fresh(svc):
    svc.apply_snapshot(A1,snapshot(NOW-10*MIN,[]),{})
    st=svc.state(A1);st["snapshot_ms"]=NOW-3600_000;svc.put_state(A1,st)
    assert svc.wallet_rows(svc.config())[0]["fresh"] is False

# ---------- bias ----------
CFG=WhaleConfig(history_factor=False)
def wallet(addr,fresh=True,equity=1000.,positions=None,cluster="",quality=1.):
    return {"address":addr,"fresh":fresh,"account_value":equity,"positions":positions or {},"cluster":cluster,"quality":quality,"history":1.,"snapshot_ms":NOW-30_000}
def act(user,action,side,notional=500.,age=MIN,coin="BTC",qty=1.):
    return {"user":user,"coin":coin,"action":action,"side":side,"notional":notional,"qty":qty,"time":NOW-age}

def test_independent_adds_make_bullish():
    b=coin_bias("BTC",[wallet(A1),wallet(A2)],[act(A1,"ADD","LONG"),act(A2,"OPEN","LONG")],CFG,NOW)
    assert b["state"]=="bullish" and b["supporting_long"]==2 and b["label"]=="monitored wallets"

def test_reduce_long_is_not_a_short_signal():
    ws=[wallet(A1,positions={"BTC":{"szi":1,"value":500}}),wallet(A2,positions={"BTC":{"szi":1,"value":500}})]
    b=coin_bias("BTC",ws,[act(A1,"REDUCE","LONG"),act(A2,"REDUCE","LONG")],CFG,NOW)
    assert b["short_support"]==0 and b["state"]!="bearish"

def test_closing_shorts_is_not_long_support():
    b=coin_bias("BTC",[wallet(A1),wallet(A2)],[act(A1,"CLOSE","SHORT"),act(A2,"CLOSE","SHORT")],CFG,NOW)
    assert b["long_support"]==0 and b["state"]!="bullish"

def test_recent_actions_outweigh_old_ones():
    fresh=coin_bias("BTC",[wallet(A1),wallet(A2)],[act(A1,"ADD","LONG",100),act(A2,"ADD","LONG",100)],CFG,NOW)
    old=coin_bias("BTC",[wallet(A1),wallet(A2)],[act(A1,"ADD","LONG",100,age=200*MIN),act(A2,"ADD","LONG",100,age=200*MIN)],CFG,NOW)
    assert fresh["long_support"]>old["long_support"]>0

def test_existing_position_weighs_less_than_new_action():
    pos=coin_bias("BTC",[wallet(A1,positions={"BTC":{"szi":1,"value":500}}),wallet(A2,positions={"BTC":{"szi":1,"value":500}})],[],CFG,NOW)
    new=coin_bias("BTC",[wallet(A1),wallet(A2)],[act(A1,"OPEN","LONG"),act(A2,"OPEN","LONG")],CFG,NOW)
    assert 0<pos["long_support"]<new["long_support"]

def test_stale_or_missing_data_is_unavailable_and_scores_nothing():
    b=coin_bias("BTC",[wallet(A1,fresh=False),wallet(A2,fresh=False)],[act(A1,"ADD","LONG")],CFG,NOW)
    assert b["state"]=="unavailable" and b["long_support"]==0
    assert coin_bias("BTC",[wallet(A1),wallet(A2)],[],CFG,NOW,running=False)["state"]=="unavailable"
    noeq=coin_bias("BTC",[wallet(A1,equity=None),wallet(A2,equity=None)],[act(A1,"ADD","LONG"),act(A2,"ADD","LONG")],CFG,NOW)
    assert noeq["long_support"]==0 and noeq["state"]=="neutral"

def test_single_dominant_whale_cannot_create_bias():
    ws=[wallet(A1,equity=1e6),wallet(A2),wallet(A3)]
    b=coin_bias("BTC",ws,[act(A1,"OPEN","LONG",1e7)],CFG,NOW)
    assert b["state"]=="neutral" and b["long_support"]==0 # a lone cluster is capped to zero share

def test_dominance_cap_limits_largest_wallet():
    assert cap_shares({"a":10.,"b":1.,"c":1.},.5)=={"a":2.,"b":1.,"c":1.}
    assert cap_shares({"a":10.,"b":1.},1)=={"a":10.,"b":1.}

def test_related_wallets_count_once():
    ws=[wallet(A1,cluster="fund"),wallet(A2,cluster="fund"),wallet(A3)]
    b=coin_bias("BTC",ws,[act(A1,"OPEN","LONG"),act(A2,"OPEN","LONG")],CFG,NOW)
    assert b["supporting_long"]==1 and b["state"]!="bullish"

def test_conflicting_when_both_sides_have_independent_support():
    ws=[wallet(a) for a in (A1,A2,A3,A4)]
    b=coin_bias("BTC",ws,[act(A1,"OPEN","LONG"),act(A2,"OPEN","LONG"),act(A3,"OPEN","SHORT"),act(A4,"OPEN","SHORT")],CFG,NOW)
    assert b["state"]=="conflicting"

def test_cohort_ratios_and_na():
    ws=[wallet(A1,positions={"BTC":{"szi":1,"value":300}}),wallet(A2,positions={"BTC":{"szi":-1,"value":100}}),wallet(A3,positions={"BTC":{"szi":2,"value":600}})]
    c=cohort("BTC",ws,[],CFG,NOW,100)
    assert (c["wallets_long"],c["wallets_short"])==(2,1) and c["long_pct_wallets"]==2/3 and c["net_bias_wallets"]==1/3 and c["long_pct_exposure"]==.9
    empty=cohort("ETH",ws,[],CFG,NOW,None)
    assert empty["long_pct_wallets"] is None and empty["net_bias_exposure"] is None and empty["exposure_change"]["1h"] is None

def test_confirmation_effects():
    bull={"state":"bullish","reasons":[],"freshness_s":1,"supporting_long":2,"supporting_short":0}
    assert confirmation(bull,"LONG")["effect"]=="SUPPORTS" and confirmation(bull,"SHORT")["effect"]=="OPPOSES"
    u=confirmation({**bull,"state":"unavailable"},"LONG");assert u["effect"]=="UNAVAILABLE" and u["conviction"]==0

# ---------- mapping & discovery ----------
@pytest.mark.parametrize("coin,expected",[("BTC",("BTCUSDT",1)),("kPEPE",("1000PEPEUSDT",1000)),("kBONK",("1000BONKUSDT",1000)),("xyz:TSLA",(None,1)),("@107",(None,1)),("",(None,1))])
def test_symbol_mapping(coin,expected):assert to_binance(coin)==expected
def test_reverse_mapping():
    assert from_binance("BTCUSDT")=="BTC" and from_binance("1000PEPEUSDT")=="kPEPE" and from_binance("AAVEUSDT")=="AAVE"

def test_discovery_needs_independent_wallets_and_skips_watchlist():
    ws=[wallet(A1),wallet(A2),wallet(A3,cluster="x"),wallet(A4,cluster="x")]
    acts=[act(A1,"OPEN","LONG",coin="WIF"),act(A2,"ADD","LONG",coin="WIF"),act(A3,"OPEN","LONG",coin="WIF"),act(A4,"OPEN","LONG",coin="WIF"),
          act(A1,"OPEN","LONG",coin="BTC"),act(A2,"OPEN","LONG",coin="BTC"),act(A3,"OPEN","LONG",coin="BTC"),act(A1,"OPEN","SHORT",coin="ENA"),act(A2,"OPEN","SHORT",coin="ENA")]
    c=discovery.candidates(acts,ws,CFG,{"BTC"},NOW)
    assert [(x["coin"],x["side"],x["independent_wallets"]) for x in c]==[("WIF","LONG",3)]

class FakeBinance:
    def __init__(self,mark=2.0,listed=True,volume=1e8):self.mark,self.listed,self.volume=mark,listed,volume
    async def request(self,method,path,params=None,signed=False):
        assert method=="GET"
        if path.endswith("exchangeInfo"):return {"symbols":[{"symbol":"WIFUSDT","status":"TRADING","contractType":"PERPETUAL","quoteAsset":"USDT"}] if self.listed else []}
        if path.endswith("24hr"):return {"quoteVolume":str(self.volume)}
        if path.endswith("bookTicker"):return {"bidPrice":"1.9999","askPrice":"2.0001"}
        if path.endswith("premiumIndex"):return {"lastFundingRate":"0.0001","markPrice":str(self.mark)}
        if path.endswith("klines"):return [[0,0,0,0,0,0,0]]*299
cand={"coin":"WIF","side":"LONG","independent_wallets":3,"opposing_wallets":0,"notional":1}
async def test_discovery_verification_passes_and_fails():
    ok=await discovery.verify(cand,FakeBinance(),CFG,2.0);assert ok["passed"] and ok["symbol"]=="WIFUSDT"
    wrong=await discovery.verify(cand,FakeBinance(mark=5.0),CFG,2.0)
    assert not wrong["passed"] and not next(c for c in wrong["checks"] if c["name"].startswith("Same asset"))["ok"]
    assert not (await discovery.verify(cand,FakeBinance(listed=False),CFG,2.0))["passed"]
    assert not (await discovery.verify(cand,FakeBinance(volume=1),CFG,2.0))["passed"]
    assert not (await discovery.verify({**cand,"coin":"xyz:TSLA"},FakeBinance(),CFG,2.0))["passed"]

# ---------- strategy integration ----------
async def test_require_confirmation_blocks_when_unavailable(monkeypatch):
    from app.execution.engine import Engine
    from app.whales import service
    db=Store("sqlite:///:memory:");db.put("news:DEMO",{"valid_until":"2099-01-01T00:00:00+00:00","events":[]})
    monkeypatch.setattr(service.whales,"config",lambda:WhaleConfig(require_confirmation=True))
    class C:env="DEMO"
    s=Setup(symbol="BTCUSDT",side="LONG",ideal=1000,stop=990,target=1040,request_id="whaletest1")
    with pytest.raises(RiskRejected,match="Whale confirmation required: UNAVAILABLE"):await Engine(db,lambda _:C()).preflight(C(),s)

async def test_auto_ranks_by_whale_but_never_changes_setup():
    import time
    from unittest.mock import AsyncMock
    from app.execution.auto import AutoTrader
    from test_auto import FakeEngine,FakeMarket
    db=Store("sqlite:///:memory:");db.put("news:DEMO",{"valid_until":"2099-01-01T00:00:00+00:00","events":[]})
    class Whale:
        def confirmation(self,symbol,side):return {"effect":"SUPPORTS" if symbol=="ETHUSDT" else "OPPOSES","conviction":1. if symbol=="ETHUSDT" else -1.}
    t=AutoTrader(FakeEngine(db),FakeMarket(),db,Whale());t.ticks={"BTCUSDT":"0.1"};t.ticks_at=time.monotonic()
    c={"strategy":"A_CHECKLIST","side":"LONG","ideal":1000.,"stop":990.,"target":1025.,"signal_ms":1}
    t.candidates=lambda:iter([("BTCUSDT",c),("ETHUSDT",dict(c))])
    await t.step()
    s=t.engine.submit.call_args.args[0]
    assert s.symbol=="ETHUSDT" and (s.stop,s.target)==(990.,1025.)

def test_whale_api():
    from app.main import app
    from app.config import settings
    h={"X-Flowpilot-Request":"1"}
    with TestClient(app) as c:
        c.post("/api/login",json={"password":settings.admin_password})
        d=c.get("/api/whales").json();assert d["label"].startswith("Monitored wallets") and d["running"] is False
        assert all(x["bias"]["state"]=="unavailable" for x in d["coins"])
        assert c.put("/api/whales/config",headers=h,json={"wallets":[{"address":A1},{"address":A1.upper().replace("0X","0x")}]}).status_code==400
        assert c.put("/api/whales/config",headers=h,json={"wallets":[{"address":"0x123"}]}).status_code==422
        assert c.put("/api/whales/config",headers=h,json={"wallets":[{"address":A1,"label":"w1"}]}).status_code==200
        assert c.post("/api/whales/research",headers=h,json={"symbol":"WIFUSDT","approve":True}).status_code==409
        assert c.post("/api/whales/research",headers=h,json={"symbol":"WIFUSDT","approve":False}).status_code==200
        assert "whale" in c.get("/api/signals?symbol=BTCUSDT").json()

def test_fills_cached_and_flushed_without_per_fill_db_writes(svc):
    svc.apply_snapshot(A1,snapshot(NOW-10*MIN,[]),{})
    writes=[];orig=svc.db.put
    svc.db.put=lambda k,v:(writes.append(k),orig(k,v))
    svc.flushed=__import__("time").monotonic() # just flushed
    for i in range(5):svc.ingest(A1,[fill(tid=100+i,start=str(i),t=NOW-MIN+i)],"ws")
    assert not [k for k in writes if k.startswith("whale:fills:")] and len(svc.fills(A1))==5
    assert "last_fill_ms" not in svc.state(A1) # not advanced until persisted
    svc.flush(force=True)
    assert len(svc.db.get("whale:fills:"+A1))==5 and svc.state(A1)["last_fill_ms"]==NOW-MIN+4
