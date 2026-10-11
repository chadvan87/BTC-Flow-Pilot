import asyncio, json, time
from collections import deque
import websockets
from app.market_data.book import Book, SequenceGap
from app.features.flow import Flow
from app.strategies.indicators import indicators
from app.execution.binance import Binance
from app.config import SYMBOLS, FLOW_BIN
class MarketData:
    def __init__(self):
        self.books={s:Book() for s in SYMBOLS}
        self.flows={s:Flow() for s in self.books};self.candles={};self.meta={};self.errors={};self.tasks=[];self.refreshed=0
    async def start(self):
        self.tasks=[asyncio.create_task(self.stream(s)) for s in self.books]+[asyncio.create_task(self.refresh())]
    async def close(self):
        for task in self.tasks:task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
    async def stream(self,symbol):
        backoff=1
        while True:
            self.books[symbol].reset();self.flows[symbol]=Flow()
            c=Binance()
            try:
                s=symbol.lower()
                url=f"wss://demo-fstream.binance.com/stream?streams={s}@depth@100ms/{s}@aggTrade"
                async with websockets.connect(url,ping_interval=20,ping_timeout=20,max_queue=2048) as ws:
                    # Buffer depth while snapshot REST request is in flight.
                    snapshot=asyncio.create_task(c.request("GET","/fapi/v1/depth",{"symbol":symbol,"limit":1000}))
                    pending=deque(maxlen=10000)
                    try:
                        while not snapshot.done():
                            try: msg=await asyncio.wait_for(ws.recv(),.2)
                            except asyncio.TimeoutError: continue
                            event=json.loads(msg)["data"]
                            if event["e"]=="depthUpdate":
                                if len(pending)==pending.maxlen:raise SequenceGap("Bootstrap buffer overflow")
                                pending.append(event)
                            else:self.flows[symbol].trade(event)
                        self.books[symbol].snapshot(await snapshot)
                        for event in pending:self.books[symbol].apply(event)
                        backoff=1;self.errors.pop(symbol,None)
                        async for msg in ws:
                            event=json.loads(msg)["data"]
                            if time.time()*1000-event.get("E",0)>3000:raise SequenceGap("Delayed exchange event")
                            if event["e"]=="depthUpdate":self.books[symbol].apply(event)
                            else:self.flows[symbol].trade(event)
                    finally:
                        if not snapshot.done():snapshot.cancel()
                        await asyncio.gather(snapshot,return_exceptions=True)
            except asyncio.CancelledError: raise
            except Exception as e:
                self.books[symbol].reset();self.errors[symbol]=type(e).__name__
                await asyncio.sleep(backoff);backoff=min(backoff*2,30)
            finally:await c.close()
    async def refresh(self):
        c=Binance()
        try:
            while True:
                try:
                    for symbol in self.books:
                        for tf in ("4h","1h","15m","5m"):
                            rows=await c.request("GET","/fapi/v1/klines",{"symbol":symbol,"interval":tf,"limit":300})
                            self.candles[(symbol,tf)]=[r for r in rows if r[6]<int(time.time()*1000)]
                        self.meta[symbol]={"funding":await c.request("GET","/fapi/v1/premiumIndex",{"symbol":symbol}),"open_interest":await c.request("GET","/fapi/v1/openInterest",{"symbol":symbol})}
                    self.refreshed=time.monotonic();self.errors.pop("rest",None)
                except Exception as e:self.errors["rest"]=type(e).__name__
                await asyncio.sleep(30)
        finally:await c.close()
    def summary(self,symbol="BTCUSDT"):
        return {"environment":"DEMO","symbol":symbol,"book":self.books[symbol].summary(),"flow":self.flows[symbol].summary(FLOW_BIN[symbol]),"regimes":{tf:indicators(self.candles.get((symbol,tf),[])) for tf in ("4h","1h","15m","5m")},"meta":self.meta.get(symbol),"rest_stale":time.monotonic()-self.refreshed>90,"errors":self.errors}
market=MarketData()
