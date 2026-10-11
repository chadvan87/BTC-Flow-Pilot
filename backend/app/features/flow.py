from collections import deque, defaultdict
import time
class Flow:
    def __init__(self):
        self.trades=deque(maxlen=100000);self.cvd=0.;self.last_id=None;self.updated=0.;self.session=time.time()
    def trade(self,e):
        if self.last_id is not None and e["a"]<=self.last_id:return
        p,q=float(e["p"]),float(e["q"])
        delta=-q if e["m"] else q # buyer is maker => aggressive sell
        self.cvd+=delta;self.last_id=e["a"];self.updated=time.monotonic()
        self.trades.append((e["T"]/1000,p,q,delta))
    def summary(self,bin_size=10):
        cutoff=time.time()-300
        rows=[t for t in self.trades if t[0]>=cutoff]
        footprint=defaultdict(lambda:{"buy":0.,"sell":0.})
        for _,p,q,d in rows:footprint[round(p//bin_size*bin_size,8)]["buy" if d>0 else "sell"]+=q
        profile={p:v["buy"]+v["sell"] for p,v in footprint.items()}
        delta=sum(t[3] for t in rows)
        poc=max(profile,key=profile.get) if profile else None
        selected=[]
        if profile:
            levels=sorted(profile);idx=levels.index(poc);lo=hi=idx;total=profile[poc];goal=sum(profile.values())*.7
            while total<goal and (lo>0 or hi<len(levels)-1):
                left=profile[levels[lo-1]] if lo>0 else -1
                right=profile[levels[hi+1]] if hi<len(levels)-1 else -1
                if left>right:lo-=1;total+=left
                else:hi+=1;total+=right
            selected=levels[lo:hi+1]
        response=(rows[-1][1]-rows[0][1])/rows[0][1] if len(rows)>1 else None
        # Candidate only; no calibrated prediction or secondary-test confirmation.
        absorption=bool(len(rows)>=50 and response is not None and abs(response)<.0003 and abs(delta)>sum(t[2] for t in rows)*.3)
        return dict(delta_5m=delta,cvd_session=self.cvd,session_start=self.session,trade_count_5m=len(rows),stale=time.monotonic()-self.updated>10,absorption_candidate=absorption,poc=poc,val=min(selected) if selected else None,vah=max(selected) if selected else None,footprint=[dict(price=p,**v) for p,v in sorted(footprint.items())],profile=[dict(price=p,volume=v) for p,v in sorted(profile.items())])
