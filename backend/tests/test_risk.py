import pytest
from app.risk.engine import Setup,RiskConfig,plan,RiskRejected
from pydantic import ValidationError
F={"PRICE_FILTER":{"tickSize":"0.1"},"LOT_SIZE":{"stepSize":"0.001","minQty":"0.001","maxQty":"100"},"MARKET_LOT_SIZE":{"stepSize":"0.001","minQty":"0.001","maxQty":"100"},"MIN_NOTIONAL":{"notional":"5"}}
def setup(**kwargs):return Setup(**({"symbol":"BTCUSDT","side":"LONG","ideal":1000,"stop":990,"target":1040,"request_id":"testing01"}|kwargs))
def test_risk_budget_rounding_and_costs():
    p=plan(setup(),1000,5,F,175,5000,RiskConfig())
    assert p["risk_budget"]==.875 and p["risk_usdt"]<=.875 and p["net_rr"]>=2
    assert float(p["quantity"])*1000/2<=175
    assert p["tolerance_pct"]==.15
@pytest.mark.parametrize("changes",[{"stop":1010},{"target":999},{"stop":990.01},{"target":1010}])
def test_invalid_stop_tick_or_rr(changes):
    with pytest.raises(RiskRejected):plan(setup(**changes),1000,5,F,175,175,RiskConfig())
def test_tolerance_rejects_chase():
    with pytest.raises(RiskRejected,match="tolerance"):plan(setup(),1002,5,F,175,175,RiskConfig())
def test_atr_tightens_tolerance():
    p=plan(setup(),1000,.2,F,175,175,RiskConfig());assert p["tolerance_pct"]==.01
@pytest.mark.parametrize("available,equity",[(.01,175),(175,.01)])
def test_too_small_margin_or_risk(available,equity):
    with pytest.raises(RiskRejected):plan(setup(),1000,5,F,available,equity,RiskConfig())
def test_short_symmetric():
    p=plan(setup(side="SHORT",stop=1010,target=960),1000,5,F,175,175,RiskConfig());assert p["net_rr"]>=2
@pytest.mark.parametrize("field,value",[("risk_pct",1),("leverage",10),("max_entries",4),("daily_loss_pct",2)])
def test_cannot_raise_safety_caps(field,value):
    with pytest.raises(ValidationError):RiskConfig(**{field:value})
def test_mark_trigger_validation():
    with pytest.raises(RiskRejected,match="trigger"):plan(setup(),1000,5,F,175,175,RiskConfig(),mark=989)
@pytest.mark.parametrize("symbol",["BTCUSDT","ETHUSDT","LINKUSDT","SOLUSDT","XRPUSDT","TRXUSDT","DOGEUSDT","NEARUSDT","AAVEUSDT"])
def test_supported_symbols_accepted(symbol):assert setup(symbol=symbol).symbol==symbol
@pytest.mark.parametrize("symbol",["PEPEUSDT","BTCUSDTX","btcusdt","ETHUSDT|X"])
def test_unsupported_symbols_rejected(symbol):
    with pytest.raises(ValidationError):setup(symbol=symbol)
def test_every_symbol_has_flow_bin():
    from app.config import SYMBOLS,FLOW_BIN
    assert set(FLOW_BIN)==set(SYMBOLS)
