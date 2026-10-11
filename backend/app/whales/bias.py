"""Per-coin whale bias, Long/Short cohort and setup confirmation over MONITORED wallets only.
Long and short support are accumulated separately: OPEN/ADD add support to their own side, REDUCE/CLOSE only
remove support from their own side (closing shorts is not buying long). Recent actions decay exponentially;
existing positions count with a lower weight. Missing equity, prices or stale wallets contribute nothing.
Weights and thresholds are hypotheses (see WhaleConfig); scores are not win probabilities.
"""
from app.whales.config import WINDOWS, MAX_WINDOW_MS

ADDS={"OPEN","ADD"}

def ratio(a,b):return a/(a+b) if a+b>0 else None
def net(a,b):return (a-b)/(a+b) if a+b>0 else None

def wallet_weight(w,cfg):
    return w.get("quality",1.0)*(w.get("history",1.0) if cfg.history_factor else 1.0)

def size_factor(notional,equity,cfg):
    if not equity or equity<=0 or notional is None:return 0.0
    return min(1.0,abs(notional)/(equity*cfg.full_size_equity_frac))

def cap_shares(contrib,share):
    """No cluster may exceed `share` of a side: c_i <= share/(1-share) * sum(others). A lone cluster caps to 0."""
    if share>=1:return dict(contrib)
    k=share/(1-share);total=sum(contrib.values())
    return {c:min(v,k*(total-v)) for c,v in contrib.items()}

def window_flow(coin,acts,now):
    out={}
    for name,span in WINDOWS.items():
        rows=[a for a in acts if a["coin"]==coin and now-a["time"]<=span]
        out[name]={"actions":len(rows),"wallets":len({a["user"] for a in rows}),
                   **{f'{a}_{s}':sum(x["notional"] for x in rows if x["action"]==a and x["side"]==s) for a in ("OPEN","ADD","REDUCE","CLOSE") for s in ("LONG","SHORT")}}
    return out

def coin_bias(coin,wallets,acts,cfg,now,running=True):
    fresh=[w for w in wallets if w["fresh"]];stale=len(wallets)-len(fresh)
    base={"coin":coin,"fresh_wallets":len(fresh),"stale_wallets":stale,"long_support":0.,"short_support":0.,"net":None,
          "supporting_long":0,"supporting_short":0,"last_action_ms":None,"freshness_s":None,"windows":window_flow(coin,acts,now),"label":"monitored wallets"}
    if not running:return {**base,"state":"unavailable","reasons":["Whale collector not running"]}
    if len(fresh)<cfg.min_fresh_wallets:
        return {**base,"state":"unavailable","reasons":[f"Only {len(fresh)} fresh monitored wallet(s); need {cfg.min_fresh_wallets}"+(f" ({stale} stale)" if stale else "")]}
    longs,shorts={},{}
    for w in fresh:
        eq=w.get("account_value");wt=wallet_weight(w,cfg);L=S=0.
        pos=w.get("positions",{}).get(coin)
        if pos and pos["szi"]:
            f=cfg.position_weight*size_factor(pos["value"],eq,cfg)
            if pos["szi"]>0:L+=f
            else:S+=f
        for a in acts:
            if a["user"]!=w["address"] or a["coin"]!=coin or not 0<=now-a["time"]<=MAX_WINDOW_MS:continue
            s=size_factor(a["notional"],eq,cfg)*0.5**((now-a["time"])/60000/cfg.half_life_min)
            delta=s if a["action"] in ADDS else -cfg.reduce_weight*s
            if a["side"]=="LONG":L+=delta
            else:S+=delta
        cluster=w.get("cluster") or w["address"]
        # Related wallets do not stack: a cluster contributes its strongest member only.
        longs[cluster]=max(longs.get(cluster,0.),min(max(L,0.),1.)*wt)
        shorts[cluster]=max(shorts.get(cluster,0.),min(max(S,0.),1.)*wt)
    n_long=sum(1 for v in longs.values() if v>=cfg.min_contribution);n_short=sum(1 for v in shorts.values() if v>=cfg.min_contribution)
    L=sum(cap_shares(longs,cfg.max_wallet_share).values());S=sum(cap_shares(shorts,cfg.max_wallet_share).values())
    mine=[a for a in acts if a["coin"]==coin and now-a["time"]<=MAX_WINDOW_MS]
    ages=[(now-w["snapshot_ms"])/1000 for w in fresh if w.get("snapshot_ms")]
    out={**base,"long_support":round(L,4),"short_support":round(S,4),"net":None if L+S==0 else round((L-S)/(L+S),4),
         "supporting_long":n_long,"supporting_short":n_short,"last_action_ms":max((a["time"] for a in mine),default=None),"freshness_s":round(max(ages),1) if ages else None}
    reasons=[f"Long support {L:.2f} from {n_long} independent wallet(s); short support {S:.2f} from {n_short}"]
    if L+S<cfg.min_total_support:return {**out,"state":"neutral","reasons":reasons+[f"Total support below {cfg.min_total_support} (no meaningful activity or dominance-capped)"]}
    th,need=cfg.bias_threshold,cfg.min_independent
    if out["net"]>=th and n_long>=need:state="bullish"
    elif out["net"]<=-th and n_short>=need:state="bearish"
    elif n_long>=need and n_short>=need:state="conflicting";reasons.append("Independent wallets on both sides")
    else:
        state="neutral"
        if abs(out["net"])>=th:reasons.append(f"Bias present but fewer than {need} independent wallets support it")
        else:reasons.append(f"Net bias {out['net']:+.2f} inside ±{th}")
    return {**out,"state":state,"reasons":reasons}

def cohort(coin,wallets,acts,cfg,now,mark):
    fresh=[w for w in wallets if w["fresh"]]
    held=[(w,w["positions"][coin]) for w in fresh if w.get("positions",{}).get(coin,{}).get("szi")]
    long_w=[(w,p) for w,p in held if p["szi"]>0];short_w=[(w,p) for w,p in held if p["szi"]<0]
    gl=sum(abs(p["value"]) for _,p in long_w);gs=sum(abs(p["value"]) for _,p in short_w)
    wl=sum(wallet_weight(w,cfg) for w,_ in long_w);ws=sum(wallet_weight(w,cfg) for w,_ in short_w)
    change={}
    for name,span in WINDOWS.items():
        rows=[a for a in acts if a["coin"]==coin and now-a["time"]<=span]
        # Size change valued at the CURRENT mark: price moves alone never show up as exposure change.
        q=lambda side:sum(a["qty"]*(1 if a["action"] in ADDS else -1) for a in rows if a["side"]==side)
        change[name]=None if mark is None else {"long_usd":q("LONG")*mark,"short_usd":q("SHORT")*mark}
    return {"coin":coin,"label":"monitored wallets","wallets_long":len(long_w),"wallets_short":len(short_w),"gross_long_usd":gl,"gross_short_usd":gs,
            "long_pct_wallets":ratio(len(long_w),len(short_w)),"net_bias_wallets":net(len(long_w),len(short_w)),
            "long_pct_exposure":ratio(gl,gs),"net_bias_exposure":net(gl,gs),"long_pct_weighted":ratio(wl,ws),"exposure_change":change}

def confirmation(bias,side):
    """How whale bias relates to an ALREADY QUALIFIED setup. Only ranking/conviction; never sizing, SL or entries."""
    state=bias["state"];want="bullish" if side=="LONG" else "bearish"
    effect=("UNAVAILABLE" if state=="unavailable" else "SUPPORTS" if state==want else "CONFLICTING" if state=="conflicting"
            else "NEUTRAL" if state=="neutral" else "OPPOSES")
    conviction={"SUPPORTS":1.,"NEUTRAL":0.,"UNAVAILABLE":0.,"CONFLICTING":-.5,"OPPOSES":-1.}[effect]
    return {"state":state,"effect":effect,"conviction":conviction,"reasons":bias["reasons"],"freshness_s":bias["freshness_s"],
            "supporting_wallets":bias["supporting_long" if side=="LONG" else "supporting_short"],
            "opposing_wallets":bias["supporting_short" if side=="LONG" else "supporting_long"],"label":"monitored wallets"}
