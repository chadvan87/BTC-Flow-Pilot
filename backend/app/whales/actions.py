"""Fill normalisation, aggregation and OPEN/ADD/REDUCE/CLOSE classification.
Direction comes ONLY from signed quantity (startPosition + signed fill size); USD notional changes caused by price
moves never create an action. Hyperliquid side "B" = buy (+), "A" = sell (-), verified on live fills 2026-10-11.
"""
from decimal import Decimal
import hashlib

D=lambda x:Decimal(str(x))

def normalize(user,fill):
    return {"user":user.lower(),"coin":fill["coin"],"px":float(fill["px"]),"sz":float(fill["sz"]),"side":fill["side"],
            "time":int(fill["time"]),"start":str(fill["startPosition"]),"tid":int(fill["tid"]),"oid":fill.get("oid"),
            "twap":fill.get("twapId"),"closed_pnl":float(fill.get("closedPnl") or 0),"fee":float(fill.get("fee") or 0)}

def signed(fill):
    if fill["side"] not in {"B","A"}:raise ValueError("Unknown fill side")
    return D(fill["sz"])*(1 if fill["side"]=="B" else -1)

def side_of(x):return "LONG" if x>0 else "SHORT"

def classify(start,end):
    """Position transition -> actions. A flip is split into CLOSE old side + OPEN new side."""
    start,end=D(start),D(end)
    if start==end:return []
    if start==0:return [("OPEN",side_of(end),abs(end))]
    if end==0:return [("CLOSE",side_of(start),abs(start))]
    if (start>0)==(end>0):
        return [("ADD",side_of(end),abs(end)-abs(start))] if abs(end)>abs(start) else [("REDUCE",side_of(start),abs(start)-abs(end))]
    return [("CLOSE",side_of(start),abs(start)),("OPEN",side_of(end),abs(end))]

def aggregate(fills,merge_window_ms):
    """Merge partial fills, TWAP slices and same-direction bursts of one wallet/coin into single events."""
    events=[];current={}
    for f in sorted(fills,key=lambda f:(f["user"],f["coin"],f["time"],f["tid"])):
        k=(f["user"],f["coin"]);delta=signed(f);sign=delta>0;cur=current.get(k)
        same_order=cur and ((f["twap"] is not None and f["twap"]==cur["twap"]) or f["oid"]==cur["oid"])
        if cur and cur["sign"]==sign and (same_order or f["time"]-cur["time"]<=merge_window_ms):
            cur.update(end=D(f["start"])+delta,time=f["time"],notional=cur["notional"]+abs(delta)*D(f["px"]),qty=cur["qty"]+abs(delta),tids=cur["tids"]+[f["tid"]],oid=f["oid"],twap=f["twap"])
        else:
            if cur:events.append(cur)
            current[k]={"user":f["user"],"coin":f["coin"],"sign":sign,"start":D(f["start"]),"end":D(f["start"])+delta,"first":f["time"],"time":f["time"],
                        "qty":abs(delta),"notional":abs(delta)*D(f["px"]),"tids":[f["tid"]],"oid":f["oid"],"twap":f["twap"],"source":"fills"}
    events.extend(current.values())
    return events

def actions(event):
    """Expand one event into classified actions. Notional uses the event VWAP, i.e. traded size x traded price."""
    vwap=event["notional"]/event["qty"] if event.get("qty") else D(event.get("px",0))
    base=hashlib.sha256(f'{event["user"]}|{event["coin"]}|{event["tids"][0] if event.get("tids") else event["time"]}'.encode()).hexdigest()[:16]
    return [{"id":f"{base}-{i}","user":event["user"],"coin":event["coin"],"time":event["time"],"action":a,"side":s,"qty":float(q),
             "px":float(vwap),"notional":float(q*vwap),"fills":len(event.get("tids") or []),"source":event["source"]}
            for i,(a,s,q) in enumerate(classify(event["start"],event["end"]))]

# Hyperliquid perp name <-> Binance USDT-M symbol. "k" prefix = 1000 units (kPEPE -> 1000PEPEUSDT).
def to_binance(coin):
    if not coin or ":" in coin or coin.startswith("@") or not coin.replace("k","",1).isalnum():return None,1
    if coin.startswith("k") and len(coin)>1 and coin[1:].isupper():return "1000"+coin[1:]+"USDT",1000
    return coin.upper()+"USDT",1

def from_binance(symbol):
    base=symbol.removesuffix("USDT")
    return "k"+base[4:] if base.startswith("1000") and len(base)>4 else base
