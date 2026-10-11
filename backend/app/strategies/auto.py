"""Automatic DEMO entry rules. EXPERIMENTAL forward test: these rules are NOT validated.
A_CHECKLIST: every research checklist row passes; stop beyond the last confirmed 15m swing, at least 1 x ATR(15m).
B_RETEST: within the last 8 closed 15m candles, a close breaks the last confirmed swing in the BTC 4H/1H trend
direction; price is back within 0.25 x ATR of that level, has not closed 0.5 x ATR through it, and 5m
executed-trade delta agrees. Stop 0.5 x ATR beyond the level.
Both target 2.5 x stop distance; the Risk Engine still requires net R:R >= 2 after costs.
Pure functions over market.summary() dicts and closed klines so they can be replayed on recorded data.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from app.strategies.signals import evaluate

RR=Decimal("2.5"); B_LOOKBACK=8; B_RETEST_ATR=.25; B_STOP_ATR=.5; MIN_CANDLES=60
STRATEGIES=("A_CHECKLIST","B_RETEST")

def pivots(rows,end):
    """Confirmed 2-bar fractal swings (same definition as indicators) using candles before index `end` only."""
    h=[float(r[2]) for r in rows[:end]];l=[float(r[3]) for r in rows[:end]]
    highs=[h[i] for i in range(2,len(h)-2) if h[i]>max(h[i-2:i]+h[i+1:i+3])]
    lows=[l[i] for i in range(2,len(l)-2) if l[i]<min(l[i-2:i]+l[i+1:i+3])]
    return highs,lows

def mid_price(book):
    bids,asks=book.get("bids") or [],book.get("asks") or []
    return (bids[0][0]+asks[0][0])/2 if bids and asks else None

def trend(btc):
    d=btc["regimes"]["4h"].get("regime")
    return d if d in {"BULLISH","BEARISH"} and btc["regimes"]["1h"].get("regime")==d else None

def bracket(side,entry,stop,tick):
    """Snap stop away from entry and target toward entry (conservative), target = entry +/- 2.5R."""
    e,s,t=Decimal(str(entry)),Decimal(str(stop)),Decimal(str(tick))
    snap=lambda x,mode:(x/t).to_integral_value(rounding=mode)*t
    if side=="LONG":s=snap(s,ROUND_FLOOR);target=snap(e+(e-s)*RR,ROUND_FLOOR)
    else:s=snap(s,ROUND_CEILING);target=snap(e-(s-e)*RR,ROUND_CEILING)
    sign=1 if side=="LONG" else -1
    if (e-s)*sign<=0 or (target-e)*sign<=0 or s<=0 or target<=0:return None
    return float(s),float(target)

def candidate(strategy,side,ideal,stop,tick,signal_ms):
    b=bracket(side,ideal,stop,tick)
    return None if b is None else {"strategy":strategy,"side":side,"ideal":ideal,"stop":b[0],"target":b[1],"signal_ms":int(signal_ms)}

def checklist_setup(btc,coin,c15,tick):
    if len(c15)<MIN_CANDLES or "atr" not in coin["regimes"]["15m"]:return None
    s=evaluate(btc["regimes"]["4h"],btc["regimes"]["1h"],coin["regimes"]["15m"],coin["regimes"]["5m"],coin["flow"],coin["book"])
    mid=mid_price(coin["book"])
    if s["direction"] not in {"BULLISH","BEARISH"} or not all(s["checks"].values()) or not mid:return None
    atr=coin["regimes"]["15m"]["atr"];highs,lows=pivots(c15,len(c15))
    if s["direction"]=="BULLISH":return candidate("A_CHECKLIST","LONG",mid,min(lows[-1] if lows else mid,mid-atr),tick,c15[-1][0])
    return candidate("A_CHECKLIST","SHORT",mid,max(highs[-1] if highs else mid,mid+atr),tick,c15[-1][0])

def retest_setup(btc,coin,c15,tick):
    direction=trend(btc);mid=mid_price(coin["book"])
    if not direction or not mid or len(c15)<MIN_CANDLES or "atr" not in coin["regimes"]["15m"]:return None
    atr=coin["regimes"]["15m"]["atr"];sign=1 if direction=="BULLISH" else -1
    closes=[float(r[4]) for r in c15];n=len(c15);level=None
    for k in range(n-1,n-1-B_LOOKBACK,-1):
        highs,lows=pivots(c15,k);levels=highs if sign==1 else lows
        if levels and (closes[k]-levels[-1])*sign>0 and (closes[k-1]-levels[-1])*sign<=0:level=levels[-1];break
    if level is None:return None
    if any((c-level)*sign<-B_STOP_ATR*atr for c in closes[k+1:]):return None # closed back through the level: failed breakout
    if abs(mid-level)>B_RETEST_ATR*atr or coin["flow"].get("delta_5m",0)*sign<=0:return None
    return candidate("B_RETEST","LONG" if sign==1 else "SHORT",mid,level-sign*B_STOP_ATR*atr,tick,c15[k][0])
