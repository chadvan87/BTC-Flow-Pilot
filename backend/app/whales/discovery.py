"""Coin discovery: coins outside the watchlist where several INDEPENDENT monitored wallets recently opened/added
on the same side. Suggestions are verified against Binance USDT-M (exact mapping, liquidity, spread, funding, price
consistency, own candle history) and can only be approved into a RESEARCH watchlist, never into trading.
"""
import time
from app.whales.actions import to_binance
from app.whales.bias import ADDS

MAX_SUGGESTIONS=5; LOOKBACK_MS=60*60_000; MAX_PRICE_GAP=.02; MIN_CANDLES=220

def candidates(acts,wallets,cfg,exclude,now):
    cluster={w["address"]:(w.get("cluster") or w["address"]) for w in wallets if w["fresh"]}
    sides={}
    for a in acts:
        if a["action"] not in ADDS or now-a["time"]>LOOKBACK_MS or a["user"] not in cluster or a["coin"] in exclude:continue
        s=sides.setdefault((a["coin"],a["side"]),{"clusters":set(),"notional":0.})
        s["clusters"].add(cluster[a["user"]]);s["notional"]+=a["notional"]
    out=[]
    for (coin,side),s in sides.items():
        opposite=sides.get((coin,"SHORT" if side=="LONG" else "LONG"),{"clusters":set()})["clusters"]
        if len(s["clusters"])>=cfg.discovery_min_wallets and len(opposite)<cfg.discovery_min_wallets:
            out.append({"coin":coin,"side":side,"independent_wallets":len(s["clusters"]),"opposing_wallets":len(opposite),"notional":s["notional"]})
    return sorted(out,key=lambda x:(-x["independent_wallets"],-x["notional"]))[:MAX_SUGGESTIONS]

async def verify(cand,binance,cfg,hl_mark):
    """Read-only public Binance checks. Every check must pass before the coin can be approved for research."""
    checks=[];ok=lambda name,passed,detail:checks.append({"name":name,"ok":bool(passed),"detail":detail})
    symbol,mult=to_binance(cand["coin"])
    if not symbol:
        ok("Binance mapping",False,"No USDT-M mapping for this Hyperliquid market");return {**cand,"symbol":None,"checks":checks,"passed":False}
    info=await binance.request("GET","/fapi/v1/exchangeInfo")
    s=next((x for x in info["symbols"] if x["symbol"]==symbol),None)
    ok("Binance mapping",s and s.get("status")=="TRADING" and s.get("contractType")=="PERPETUAL" and s.get("quoteAsset")=="USDT",
       f"{symbol} ({'x'+str(mult)+' units' if mult!=1 else '1:1'}) "+("TRADING perpetual" if s else "not listed"))
    if not checks[-1]["ok"]:return {**cand,"symbol":symbol,"checks":checks,"passed":False}
    t=await binance.request("GET","/fapi/v1/ticker/24hr",{"symbol":symbol})
    ok("24h liquidity",float(t["quoteVolume"])>=cfg.discovery_min_quote_volume,f'{float(t["quoteVolume"]):,.0f} USDT (min {cfg.discovery_min_quote_volume:,.0f})')
    b=await binance.request("GET","/fapi/v1/ticker/bookTicker",{"symbol":symbol})
    bid,ask=float(b["bidPrice"]),float(b["askPrice"]);spread=(ask-bid)/((ask+bid)/2)*100 if bid and ask else None
    ok("Spread",spread is not None and spread<=cfg.discovery_max_spread_pct,f'{spread:.4f}% (max {cfg.discovery_max_spread_pct}%)' if spread is not None else "No quote")
    p=await binance.request("GET","/fapi/v1/premiumIndex",{"symbol":symbol})
    fr=float(p["lastFundingRate"]);ok("Funding",abs(fr)<=cfg.discovery_max_abs_funding,f'{fr*100:.4f}% (max ±{cfg.discovery_max_abs_funding*100:.3f}%)')
    mark=float(p["markPrice"])
    gap=abs(mark/(hl_mark*mult)-1) if hl_mark else None
    ok("Same asset (price match)",gap is not None and gap<=MAX_PRICE_GAP,f'Binance {mark:g} vs Hyperliquid {hl_mark}x{mult}'+(f' gap {gap*100:.2f}%' if gap is not None else ' (no Hyperliquid mark)'))
    k=await binance.request("GET","/fapi/v1/klines",{"symbol":symbol,"interval":"15m","limit":300})
    closed=[r for r in k if r[6]<int(time.time()*1000)]
    ok("Own candle history",len(closed)>=MIN_CANDLES,f'{len(closed)} closed 15m candles (need {MIN_CANDLES})')
    return {**cand,"symbol":symbol,"checks":checks,"passed":all(c["ok"] for c in checks)}
