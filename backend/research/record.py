"""Record one DEMO symbol, buffered snapshot/depth plus executed aggTrades.
Run: python -m research.record BTCUSDT recordings/btc.jsonl
On sequence gap appends a new snapshot; no continuity claimed across sessions.
"""
import asyncio,json,sys,time
from pathlib import Path
import websockets
from app.execution.binance import Binance
from app.market_data.book import Book,SequenceGap
async def record(symbol,path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    c=Binance();book=Book()
    with open(path,"a",buffering=1) as f:
        def write(kind,data):f.write(json.dumps({"received":time.time(),"kind":kind,"data":data})+"\n")
        try:
            while True:
                try:
                    s=symbol.lower()
                    async with websockets.connect(f"wss://demo-fstream.binance.com/stream?streams={s}@depth@100ms/{s}@aggTrade") as ws:
                        pending=[];task=asyncio.create_task(c.request("GET","/fapi/v1/depth",{"symbol":symbol,"limit":1000}))
                        try:
                            while not task.done():
                                try:pending.append(json.loads(await asyncio.wait_for(ws.recv(),.2))["data"])
                                except asyncio.TimeoutError:continue
                                if len(pending)>10000:raise SequenceGap("Recorder buffer overflow")
                            snapshot=await task;book.snapshot(snapshot);write("snapshot",snapshot)
                            for e in pending:
                                if e["e"]=="aggTrade":write("trade",e)
                                elif book.apply(e):write("depth",e)
                            async for message in ws:
                                e=json.loads(message)["data"]
                                if e["e"]=="aggTrade":write("trade",e)
                                elif book.apply(e):write("depth",e)
                        finally:
                            if not task.done():task.cancel()
                            await asyncio.gather(task,return_exceptions=True)
                except (SequenceGap,websockets.ConnectionClosed):await asyncio.sleep(2)
        finally:await c.close()
if __name__=="__main__":asyncio.run(record(sys.argv[1],sys.argv[2]))
