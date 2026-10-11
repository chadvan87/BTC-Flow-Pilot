import time
import pytest
from app.execution.engine import Engine
from app.database.store import Store
from app.market_data.service import market
from app.risk.engine import Setup,RiskRejected
from test_risk import F
class AccountFake:
    env='DEMO'
    def __init__(self,fail=''):self.fail=fail
    async def sync_clock(self):pass
    async def positions(self):return [{'symbol':'ETHUSDT','positionAmt':'1'}] if self.fail=='position' else []
    async def account(self):return {'canTrade':True,'totalMarginBalance':'10000','availableBalance':'.01' if self.fail=='margin' else '10000'}
    async def request(self,method,path,p=None,signed=False):
        if path.endswith('/dual'):return {'dualSidePosition':self.fail=='hedge'}
        if path.endswith('multiAssetsMargin'):return {'multiAssetsMargin':False}
        if path.endswith('openOrders') or path.endswith('openAlgoOrders'):return [{}] if self.fail=='orders' else []
        if path.endswith('symbolConfig'):return [{'symbol':'BTCUSDT','marginType':'CROSSED' if self.fail=='cross' else 'ISOLATED','leverage':10 if self.fail=='leverage' else 2}]
        if path.endswith('/income'):return [{'incomeType':'REALIZED_PNL','income':'-3'}] if self.fail=='daily_loss' else []
        if path.endswith('/userTrades'):return [{'orderId':1,'time':2,'realizedPnl':'-1','commission':'.01'},{'orderId':2,'time':3,'realizedPnl':'-1','commission':'.01'}] if self.fail=='streak' else []
        if path.endswith('exchangeInfo'):return {'symbols':[{'symbol':'BTCUSDT','status':'TRADING','filters':[{'filterType':k,**v} for k,v in F.items()]}]}
        if path.endswith('bookTicker'):return {'askPrice':'1000','bidPrice':'999.9','time':0 if self.fail=='quote' else int(time.time()*1000)}
        if path.endswith('premiumIndex'):return {'markPrice':'1000'}
        raise AssertionError(path)
@pytest.fixture
def fixture(monkeypatch):
    db=Store('sqlite:///:memory:');db.put('news:DEMO',{'valid_until':'2099-01-01T00:00:00+00:00','events':[]})
    e=Engine(db)
    monkeypatch.setattr(market,'summary',lambda *a:{'rest_stale':False,'book':{'synced':True,'stale':False,'spread_pct':.01},'flow':{'stale':False},'regimes':{'5m':{'atr':5}}})
    monkeypatch.setattr(market,'candles',{('BTCUSDT','5m'):[[0,1000,1001,999,1000,1]]*31})
    s=Setup(symbol='BTCUSDT',side='LONG',ideal=1000,stop=990,target=1040,request_id='preflight1')
    return e,s
async def test_full_preflight_simulated_capital(fixture):
    e,s=fixture;p,_,_=await e.preflight(AccountFake(),s)
    assert p['risk_budget']==.875 and p['margin_usdt']<=175
@pytest.mark.parametrize('fail',['position','hedge','orders','cross','leverage','daily_loss','streak','quote','margin'])
async def test_preflight_account_guard(fixture,fail):
    e,s=fixture
    with pytest.raises(RiskRejected):await e.preflight(AccountFake(fail),s)
async def test_missing_news_blocks(fixture):
    e,s=fixture;e.db.put('news:DEMO',{})
    with pytest.raises(RiskRejected):await e.preflight(AccountFake(),s)
