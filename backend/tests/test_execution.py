import pytest
from unittest.mock import AsyncMock
from app.execution.engine import Engine
from app.execution.binance import Binance,ExchangeError
from app.database.store import Store
from app.risk.engine import Setup,RiskConfig,RiskRejected
from app.market_data.service import market
from test_risk import F
class Fake:
    env="DEMO"
    def __init__(self,sl_bad=False,timeout=False,partial=False):self.entries=0;self.qty="0.066";self.protection={};self.sl_bad=sl_bad;self.timeout=timeout;self.partial=partial;self.open=True
    async def close(self):pass
    async def sync_clock(self):pass
    async def market(self,symbol,side,qty,cid,reduce=False):
        if reduce:self.open=False
        else:
            self.entries+=1;self.qty=qty
            if self.timeout:raise TimeoutError()
        return {}
    async def order(self,symbol,cid):return {"status":"PARTIALLY_FILLED" if self.partial else "FILLED","avgPrice":"1000","executedQty":self.qty}
    async def protective(self,symbol,side,price,cid,tp=False):
        self.protection[cid]={"algoStatus":"NEW","symbol":symbol,"side":side,"positionSide":"BOTH","closePosition":True,"workingType":"MARK_PRICE","orderType":"TAKE_PROFIT_MARKET" if tp else "STOP_MARKET","triggerPrice":price,"clientAlgoId":cid}
    async def algo(self,cid):
        if self.sl_bad and cid.endswith('_sl'):raise RuntimeError("SL unavailable")
        return self.protection[cid]
    async def positions(self):return [{"symbol":"BTCUSDT","positionAmt":self.qty if self.open else "0","updateTime":1}]
    async def request(self,method,path,params=None,signed=False):
        if path.endswith('/dual'):return {"dualSidePosition":False}
        if method=='DELETE' and path.endswith('algoOrder'):
            self.protection[params['clientAlgoId']]['algoStatus']='CANCELED';return {}
        return []
@pytest.fixture
def case(monkeypatch):
    db=Store("sqlite:///:memory:");db.put("control",{"stopped":False,"environment":"DEMO"})
    fake=Fake();e=Engine(db,lambda _:fake)
    e.preflight=AsyncMock(return_value=({"quantity":"0.066","entry":1000,"risk_usdt":.85},F,RiskConfig()))
    monkeypatch.setattr(market,"summary",lambda *a:{"regimes":{"5m":{"atr":5}}})
    s=Setup(symbol="BTCUSDT",side="LONG",ideal=1000,stop=990,target=1040,request_id="request01",confirm=True)
    return e,fake,s
async def test_entry_timeout_is_reconciled_no_retry(case):
    e,f,s=case;f.timeout=True
    r=await e.submit(s);assert r["state"]=="PROTECTED" and f.entries==1
async def test_idempotency(case):
    e,f,s=case;await e.submit(s);await e.submit(s);assert f.entries==1
async def test_idempotency_payload_conflict(case):
    e,f,s=case;await e.submit(s)
    with pytest.raises(Exception,match="different setup"):await e.submit(s.model_copy(update={"target":1050}))
async def test_protection_failure_stops(case):
    e,f,s=case;f.sl_bad=True;r=await e.submit(s)
    assert r["state"]=="UNPROTECTED_OR_UNKNOWN" and e.control()["stopped"] and f.entries==1
async def test_partial_fill_blocks(case):
    e,f,s=case;f.partial=True;r=await e.submit(s)
    assert r["state"]=="PARTIAL_OR_PENDING" and e.control()["stopped"]
async def test_stop_during_preflight(case):
    e,f,s=case
    async def pre(*args):await e.stop();return ({"quantity":"0.066","entry":1000},F,RiskConfig())
    e.preflight=pre
    with pytest.raises(RiskRejected):await e.submit(s)
    assert f.entries==0
async def test_stopped_rejects_new_entry(case):
    e,f,s=case;await e.stop()
    with pytest.raises(Exception):await e.submit(s)
    assert f.entries==0
async def test_real_selected_rejects(case):
    e,f,s=case;e.db.put('control',{'stopped':False,'environment':'REAL'})
    with pytest.raises(Exception):await e.submit(s)
    assert f.entries==0
async def test_missing_confirmation(case):
    e,f,s=case
    with pytest.raises(Exception):await e.submit(s.model_copy(update={'confirm':False}))
async def test_flatten_verified_then_cancel(case):
    e,f,s=case;await e.submit(s);result=await e.flatten()
    assert result['flat_verified'] and not f.open and e.control()['stopped']
    assert all(x['algoStatus']=='CANCELED' for x in f.protection.values())
async def test_recovery_no_duplicate_entry(case):
    e,f,s=case;await e.submit(s);await e.stop('restart');await e.reconcile()
    assert e.control()['stopped'] and f.entries==1 and e.rows()[0]['state']=='PROTECTED'
async def test_real_client_mutation_locked():
    c=Binance('REAL')
    try:
        with pytest.raises(ExchangeError,match='REAL_LOCKED'):await c.market('BTCUSDT','BUY','1','test')
        with pytest.raises(ExchangeError):await c.request('DELETE','/fapi/v1/algoOrder')
    finally:await c.close()
def test_protection_attribute_mismatch():
    with pytest.raises(RiskRejected):Engine.validate_protection({}, {'setup':{'symbol':'BTCUSDT','side':'LONG','stop':990},'sl_cid':'x'},'SL')
async def test_terminal_zero_fill_rejected_safely(case):
    e,f,s=case
    f.order=AsyncMock(return_value={'status':'CANCELED','executedQty':'0'})
    r=await e.submit(s)
    assert r['state']=='REJECTED' and e.control()['stopped'] and not f.protection
