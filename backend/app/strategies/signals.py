def evaluate(btc4,btc1,coin15,coin5,flow,book):
    direction=btc4.get("regime")
    agreed=direction in {"BULLISH","BEARISH"} and btc1.get("regime")==direction
    checks={"BTC 4H/1H agreement":agreed,"Coin 15m structure":agreed and coin15.get("regime")==direction,"Coin 5m structure":agreed and coin5.get("regime")==direction,"Fresh executed trades":not flow.get("stale",True),"Synchronized DOM":book.get("synced",False) and not book.get("stale",True),"Delta alignment":agreed and flow.get("delta_5m",0)*(1 if direction=="BULLISH" else -1)>0,"Persistent directional liquidity":agreed and book.get("persistent_notional",{}).get("bids" if direction=="BULLISH" else "asks",0)>0}
    # Deliberately fail closed: automated zone/test lifecycle is not yet validated.
    return {"status":"RESEARCH_ONLY","direction":direction if agreed else "NO_TRADE","checks":checks,"strategy_A":{"absorption_candidate":flow.get("absorption_candidate",False),"secondary_test":"NOT_IMPLEMENTED"},"strategy_B":{"breakout_retest":"NOT_IMPLEMENTED"},"auto_trading":False}
