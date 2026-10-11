import time
import pytest
from app.market_data.book import Book,SequenceGap
from app.features.flow import Flow
from app.filters.guards import news_guard,crash_guard
from app.strategies.signals import evaluate

def event(U=99,u=101,pu=98):return {"U":U,"u":u,"pu":pu,"b":[["99","2"]],"a":[["101","1"]]}
def book():
    b=Book();b.snapshot({"lastUpdateId":100,"bids":[["99","1"]],"asks":[["101","1"]]});return b

def test_bootstrap_and_gap():
    b=book();assert b.apply(event());assert b.synced
    with pytest.raises(SequenceGap):b.apply(event(102,103,100))
    assert not b.synced and not b.bids

def test_absolute_quantity_and_deletion():
    b=book();b.apply(event());b.apply({"U":102,"u":103,"pu":101,"b":[["99","0"],["98","4"]],"a":[]})
    assert list(b.bids.values())==[4]

def test_snapshot_boundary_required():
    b=book()
    with pytest.raises(SequenceGap):b.apply(event(101,102,100))

def test_old_updates_ignored():
    b=book();assert not b.apply(event(97,99,96))

def test_staleness():
    b=book();b.apply(event());b.updated=time.monotonic()-4;assert b.summary()["stale"]

def test_trade_delta_not_dom():
    f=Flow();t=int(time.time()*1000)
    f.trade({"a":1,"T":t,"p":"100","q":"2","m":True})
    f.trade({"a":2,"T":t,"p":"100","q":"3","m":False})
    f.trade({"a":2,"T":t,"p":"100","q":"100","m":False})
    s=f.summary(1);assert s["cvd_session"]==1 and s["footprint"][0]["buy"]==3 and s["footprint"][0]["sell"]==2

def test_news_fail_closed():
    assert news_guard(None)
    assert news_guard({"valid_until":"2000-01-01T00:00:00+00:00","events":[]})
    assert news_guard({"valid_until":"2099-01-01T00:00:00+00:00","events":[{"name":"FOMC","time":__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()}]})
    assert news_guard({"valid_until":"2099-01-01T00:00:00+00:00","events":[]}) is None

def test_crash_guard_blocks_stale():assert crash_guard({"synced":False},{},[])
def test_strategy_never_auto_trades():
    s=evaluate({"regime":"BULLISH"},{"regime":"BEARISH"},{},{},{},{})
    assert s["direction"]=="NO_TRADE" and s["auto_trading"] is False
