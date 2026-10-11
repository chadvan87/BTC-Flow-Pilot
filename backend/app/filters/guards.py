from datetime import datetime, timezone, timedelta

def news_guard(calendar):
    now=datetime.now(timezone.utc)
    if not calendar or not calendar.get("valid_until"):return "News calendar missing"
    try:
        expiry=datetime.fromisoformat(calendar["valid_until"])
        if expiry.tzinfo is None or expiry<=now:return "News calendar expired or timezone missing"
        for event in calendar.get("events",[]):
            t=datetime.fromisoformat(event["time"])
            if t.tzinfo is None:return "Event timezone missing"
            if t-timedelta(minutes=60)<=now<=t+timedelta(minutes=60):return "News blackout: "+event["name"]
    except (ValueError,KeyError,TypeError):return "Invalid news calendar"
    return None

def crash_guard(book,flow,candles):
    if not book.get("synced") or book.get("stale"):return "Depth stale or unsynchronized"
    if flow.get("stale"):return "Executed trades stale"
    if book.get("spread_pct") is None or book["spread_pct"]>.08:return "Spread too wide"
    if len(candles)<31:return "Insufficient crash history"
    latest=float(candles[-1][4]);past=float(candles[-4][4])
    if abs(latest/past-1)>=.03:return "BTC moved >=3% across recent 15-minute closes"
    ranges=[float(x[2])-float(x[3]) for x in candles[-31:]]
    baseline=sum(ranges[:-1])/30
    if baseline and ranges[-1]>baseline*4:return "ATR/range spike candidate"
    return None
