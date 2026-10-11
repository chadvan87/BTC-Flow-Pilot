import hashlib,hmac
from urllib.parse import parse_qs
import httpx
from app.execution.binance import Binance
async def test_signed_payload_algo_endpoint():
    captured=[]
    def handle(request):captured.append(request);return httpx.Response(200,json={'algoStatus':'NEW'})
    c=Binance('DEMO','key','secret',httpx.MockTransport(handle))
    try:await c.protective('BTCUSDT','SELL','990','fp_request_sl')
    finally:await c.close()
    r=captured[0];query=r.url.query.decode();body,sig=query.rsplit('&signature=',1)
    assert hmac.compare_digest(sig,hmac.new(b'secret',body.encode(),hashlib.sha256).hexdigest())
    p=parse_qs(body)
    assert r.url.path=='/fapi/v1/algoOrder' and p['closePosition']==['true'] and 'quantity' not in p and 'reduceOnly' not in p
    assert p['triggerPrice']==['990'] and r.headers['X-MBX-APIKEY']=='key'
