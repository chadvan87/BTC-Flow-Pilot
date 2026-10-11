import time
import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from app.strategies.auto import checklist_setup, retest_setup, bracket
from app.execution.auto import AutoTrader
from app.execution.engine import Engine
from app.database.store import Store
from app.risk.engine import RiskRejected

def candles(n=62,pivot_high=None,pivot_low=None,breakout=False):
    rows=[[i*900000,1000,1002,998,1000] for i in range(n)]
    if pivot_high:rows[pivot_high][2]=1010
    if pivot_low:rows[pivot_low][3]=990
    if breakout:rows[60]=[60*900000,1000,1016,1000,1015];rows[61]=[61*900000,1015,1015,1010,1012]
    return rows

def market(side="BULLISH",delta=5,mid=1000,atr=8,liquidity=100):
    other="BEARISH" if side=="BULLISH" else "BULLISH"
    return {"regimes":{"4h":{"regime":side},"1h":{"regime":side},"15m":{"regime":side,"atr":atr},"5m":{"regime":side}},
            "flow":{"stale":False,"delta_5m":delta},"book":{"synced":True,"stale":False,"persistent_notional":{"bids":liquidity,"asks":liquidity},
            "bids":[[mid-.1,1]],"asks":[[mid+.1,1]]},"_other":other}

def test_checklist_long_uses_swing_stop_and_2_5r():
    m=market();c=checklist_setup(m,m,candles(pivot_low=50),"0.1")
    assert c["strategy"]=="A_CHECKLIST" and c["side"]=="LONG" and c["stop"]==990 and c["target"]==1025

def test_checklist_stop_at_least_one_atr():
    m=market(atr=20);c=checklist_setup(m,m,candles(pivot_low=50),"0.1")
    assert c["stop"]==980 and c["target"]==1050

@pytest.mark.parametrize("change",[{"delta":-1},{"liquidity":0}])
def test_checklist_requires_every_row(change):
    m=market(**change);assert checklist_setup(m,m,candles(pivot_low=50),"0.1") is None

def test_checklist_requires_btc_agreement():
    m=market();m["regimes"]["1h"]["regime"]="BEARISH"
    assert checklist_setup(m,m,candles(pivot_low=50),"0.1") is None

def test_retest_long_after_breakout():
    m=market(mid=1011,atr=10);c=retest_setup(m,m,candles(pivot_high=55,breakout=True),"0.1")
    assert c["strategy"]=="B_RETEST" and c["side"]=="LONG" and c["stop"]==1005 and c["target"]==1026 and c["signal_ms"]==60*900000

@pytest.mark.parametrize("mid,delta",[(1020,5),(1011,-5)])
def test_retest_needs_price_at_level_and_delta(mid,delta):
    m=market(mid=mid,atr=10,delta=delta);assert retest_setup(m,m,candles(pivot_high=55,breakout=True),"0.1") is None

def test_retest_failed_breakout_cancelled():
    rows=candles(pivot_high=55,breakout=True);rows[61][4]=1004 # closed >0.5 ATR back below level
    m=market(mid=1011,atr=10);assert retest_setup(m,m,rows,"0.1") is None

def test_retest_without_breakout_is_none():
    m=market(mid=1011,atr=10);assert retest_setup(m,m,candles(pivot_high=55),"0.1") is None

def test_bracket_rounds_conservatively():
    assert bracket("LONG",100.05,99.03,"0.1")==(99.0,102.6)
    assert bracket("SHORT",100.05,101.07,"0.1")==(101.1,97.5)
    assert bracket("LONG",100,101,"0.1") is None

class FakeEngine:
    def __init__(self,db,auto=True):
        self.db=db;db.put("control",{"stopped":False,"environment":"DEMO","auto":auto})
        self.preview=AsyncMock(return_value={});self.submit=AsyncMock(return_value={"state":"PROTECTED"});self.stop=AsyncMock()
    def control(self):return self.db.get("control")
    def rows(self):return []
class FakeMarket:
    def __init__(self):self.data=market();self.candles={("BTCUSDT","15m"):candles(pivot_low=50)}
    def summary(self,symbol="BTCUSDT"):return self.data

@pytest.fixture
def trader():
    db=Store("sqlite:///:memory:");db.put("news:DEMO",{"valid_until":"2099-01-01T00:00:00+00:00","events":[]})
    t=AutoTrader(FakeEngine(db),FakeMarket(),db);t.ticks={"BTCUSDT":"0.1"};t.ticks_at=time.monotonic()
    return t

async def test_auto_off_never_previews(trader):
    trader.db.put("control",{"stopped":False,"environment":"DEMO","auto":False})
    assert await trader.step() is None;trader.engine.preview.assert_not_called()

async def test_stopped_never_previews(trader):
    trader.db.put("control",{"stopped":True,"environment":"DEMO","auto":True})
    assert await trader.step() is None;trader.engine.preview.assert_not_called()

async def test_news_guard_blocks_auto(trader):
    trader.db.put("news:DEMO",None)
    assert await trader.step() is None;trader.engine.preview.assert_not_called()

async def test_auto_previews_then_submits_tagged_setup(trader):
    assert (await trader.step())["state"]=="PROTECTED"
    s=trader.engine.submit.call_args.args[0]
    assert s.confirm is True and s.strategy=="A_CHECKLIST" and s.request_id.startswith("auto_") and s.stop==990
    trader.engine.preview.assert_awaited_once()

async def test_rejected_preview_does_not_stop_or_submit_and_cools_down(trader):
    trader.engine.preview.side_effect=RiskRejected("Net R:R below 2 after fee/funding/slippage reserves")
    await trader.step();await trader.step()
    trader.engine.submit.assert_not_called();trader.engine.stop.assert_not_called()
    assert trader.engine.preview.await_count==1 and trader.events[0]["event"]=="AUTO_SKIP"

async def test_loss_streak_turns_auto_off(trader):
    trader.engine.preview.side_effect=RiskRejected("Two consecutive losing closes: manual review required")
    await trader.step()
    assert trader.engine.control()["auto"] is False and trader.engine.control()["stopped"] is False
    trader.engine.submit.assert_not_called()

async def test_submitted_signal_never_resubmitted(trader):
    await trader.step();rid=trader.engine.submit.call_args.args[0].request_id
    trader.db.put("order:DEMO:"+rid,{"state":"EXITED"});trader.engine.submit.reset_mock()
    await trader.step()
    assert all(c.args[0].request_id!=rid for c in trader.engine.submit.call_args_list)

async def test_stop_turns_auto_off():
    db=Store("sqlite:///:memory:");db.put("control",{"stopped":False,"environment":"DEMO","auto":True})
    await Engine(db,lambda _:None).stop("test")
    assert db.get("control")["auto"] is False and db.get("control")["stopped"] is True

def test_auto_api_requires_confirm_and_running():
    from app.main import app
    from app.config import settings
    h={"X-Flowpilot-Request":"1"}
    with TestClient(app) as c:
        c.post("/api/login",json={"password":settings.admin_password})
        assert c.get("/api/status").json()["control"]["auto"] is False # startup STOP turns AUTO off
        assert c.post("/api/control/auto",headers=h,json={"enabled":True}).status_code==400
        assert c.post("/api/control/auto",headers=h,json={"enabled":True,"confirm":True}).status_code==409 # STOPPED
        assert c.post("/api/control/auto",headers=h,json={"enabled":False}).status_code==200
        assert c.post("/api/control/review",headers=h,json={"confirm":False}).status_code==400
        assert c.post("/api/control/review",headers=h,json={"confirm":True}).json()["review_ack_ms"]>0
