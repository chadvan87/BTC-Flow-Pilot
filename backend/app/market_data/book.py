import time
from decimal import Decimal
class SequenceGap(ValueError): pass
class Book:
    def __init__(self): self.reset()
    def reset(self):
        self.bids={};self.asks={};self.last=None;self.synced=False;self.updated=0.;self.since={}
    def snapshot(self,s):
        self.reset();self.last=int(s["lastUpdateId"])
        self.bids={Decimal(p):Decimal(q) for p,q in s["bids"] if Decimal(q)>0}
        self.asks={Decimal(p):Decimal(q) for p,q in s["asks"] if Decimal(q)>0}
        self.since={(name,p):time.monotonic() for name in ("bids","asks") for p in getattr(self,name)}
    def apply(self,e):
        if self.last is None: raise SequenceGap("Snapshot missing")
        if e["u"]<self.last or (self.synced and e["u"]==self.last): return False
        if not self.synced:
            if not e["U"]<=self.last<=e["u"]:
                self.reset();raise SequenceGap("First update does not span snapshot")
        elif e["pu"]!=self.last:
            self.reset();raise SequenceGap("Depth gap; resnapshot required")
        for name,key in (("bids","b"),("asks","a")):
            side=getattr(self,name)
            for p,q in e[key]:
                p,q=Decimal(p),Decimal(q)
                if q==0: side.pop(p,None);self.since.pop((name,p),None)
                else:
                    if p not in side:self.since[(name,p)]=time.monotonic()
                    side[p]=q
        self.last=e["u"];self.synced=True;self.updated=time.monotonic()
        if self.bids and self.asks and max(self.bids)>=min(self.asks):
            self.reset();raise SequenceGap("Crossed book")
        return True
    def summary(self):
        bids=sorted(self.bids.items(),reverse=True)[:20];asks=sorted(self.asks.items())[:20]
        b=sum(p*q for p,q in bids);a=sum(p*q for p,q in asks)
        mid=(bids[0][0]+asks[0][0])/2 if bids and asks else 0
        persistent={name:float(sum(p*q for p,q in levels if time.monotonic()-self.since.get((name,p),time.monotonic())>=5)) for name,levels in (("bids",bids),("asks",asks))}
        return dict(synced=self.synced,stale=not self.synced or time.monotonic()-self.updated>3,imbalance=float((b-a)/(b+a)) if b+a else 0,spread_pct=float((asks[0][0]-bids[0][0])/mid*100) if mid else None,bids=[[float(p),float(q)] for p,q in bids],asks=[[float(p),float(q)] for p,q in asks],persistent_notional=persistent)
