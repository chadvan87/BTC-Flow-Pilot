from decimal import Decimal, ROUND_DOWN
from pydantic import BaseModel, Field
from app.config import SYMBOLS
D=lambda x: Decimal(str(x))
class RiskConfig(BaseModel):
    capital: float = Field(175,gt=0,le=100000)
    risk_pct: float = Field(.5,gt=0,le=.5)
    daily_loss_pct: float = Field(1.5,gt=0,le=1.5)
    max_entries: int = Field(3,ge=1,le=3)
    leverage: int = Field(2,ge=1,le=2)
    tolerance_pct: float = Field(.15,gt=0,le=.3)
    slippage_pct: float = Field(.04,gt=0,le=.05)
    fee_rate: float = Field(.0005,ge=0,le=.01)
    funding_reserve: float = Field(.001,ge=0,le=.05)
class Setup(BaseModel):
    symbol: str = Field(pattern="^("+"|".join(SYMBOLS)+")$")
    side: str = Field(pattern="^(LONG|SHORT)$")
    ideal: float = Field(gt=0,allow_inf_nan=False)
    stop: float = Field(gt=0,allow_inf_nan=False)
    target: float = Field(gt=0,allow_inf_nan=False)
    tolerance_pct: float = Field(.15,gt=0,le=.3)
    request_id: str = Field(pattern="^[a-zA-Z0-9_-]{8,32}$")
    strategy: str = Field("MANUAL",pattern="^(MANUAL|A_CHECKLIST|B_RETEST)$")
    confirm: bool = False
class RiskRejected(ValueError): pass

def plan(setup,entry,atr,filters,available,equity,config,mark=None):
    entry,stop,target,ideal,atr=map(D,(entry,setup.stop,setup.target,setup.ideal,atr))
    if min(entry,atr,ideal,D(equity),D(available))<=0: raise RiskRejected("Invalid account or market data")
    sign=D(1 if setup.side=="LONG" else -1)
    if (entry-stop)*sign<=0 or (target-entry)*sign<=0: raise RiskRejected("Stop/target are on the wrong side")
    if mark is not None and ((D(mark)-stop)*sign<=0 or (target-D(mark))*sign<=0): raise RiskRejected("Protection would trigger immediately at mark price")
    tick=D(filters["PRICE_FILTER"]["tickSize"])
    if any(x%tick!=0 for x in (stop,target)): raise RiskRejected("SL/TP must align with tick size")
    cap=D(.20 if setup.symbol=="BTCUSDT" else .30)
    tol=min(cap,D(setup.tolerance_pct),D(config.tolerance_pct),D('.5')*atr/ideal*100,D('.2')*abs(ideal-stop)/ideal*100)
    if abs(entry-ideal)/ideal*100>tol: raise RiskRejected("Entry outside adaptive tolerance")
    f=D(config.fee_rate); slip=D(config.slippage_pct)/100; funding=D(config.funding_reserve)
    loss=abs(entry-stop)+f*(entry+stop)+entry*(2*slip+funding)
    gain=abs(target-entry)-f*(entry+target)-entry*(2*slip+funding)
    rr=gain/loss
    if rr<2: raise RiskRejected("Net R:R below 2 after fee/funding/slippage reserves")
    budget=min(D(equity),D(config.capital))*D(config.risk_pct)/100
    lot=filters["LOT_SIZE"]; market=filters.get("MARKET_LOT_SIZE",lot)
    steps=[D(x["stepSize"]) for x in (lot,market) if D(x["stepSize"])>0]
    step=max(steps)
    spendable=min(D(available),D(equity),D(config.capital))
    quantity=min(budget/loss,spendable/(entry/D(config.leverage)+entry*f))
    quantity=(quantity/step).to_integral_value(rounding=ROUND_DOWN)*step
    for fl in (lot,market):
        if quantity<D(fl["minQty"]) or quantity>D(fl["maxQty"]) or (D(fl["stepSize"]) and quantity%D(fl["stepSize"])): raise RiskRejected("Quantity violates exchange lot filters")
    minimum=D(filters.get("MIN_NOTIONAL",{}).get("notional",filters.get("NOTIONAL",{}).get("minNotional",0)))
    if quantity<=0 or quantity*entry<minimum: raise RiskRejected("Risk budget cannot satisfy minimum notional")
    required=quantity*entry/D(config.leverage)+quantity*entry*f
    if required>spendable: raise RiskRejected("Insufficient margin including entry fee")
    return dict(quantity=format(quantity,'f'),entry=float(entry),stop=float(stop),target=float(target),net_rr=float(rr),risk_usdt=float(quantity*loss),risk_budget=float(budget),tolerance_pct=float(tol),margin_usdt=float(required),slippage_pct=config.slippage_pct)
