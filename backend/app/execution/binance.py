import hashlib, hmac, time
from urllib.parse import urlencode
import httpx
class ExchangeError(Exception):
    def __init__(self,code,message="Exchange request rejected"):
        self.code=code
        super().__init__(f"Exchange error {code}: {message}")
class Binance:
    BASE={"DEMO":"https://demo-fapi.binance.com","REAL":"https://fapi.binance.com"}
    def __init__(self,env="DEMO",key="",secret="",transport=None):
        if env not in self.BASE: raise ValueError("Invalid environment")
        self.env,self.key,self.secret=env,key,secret
        self.http=httpx.AsyncClient(base_url=self.BASE[env],timeout=12,transport=transport)
        self.offset=0
    async def close(self): await self.http.aclose()
    async def request(self,method,path,params=None,signed=False):
        if self.env=="REAL" and method!="GET": raise ExchangeError("REAL_LOCKED","REAL trading is disabled in code")
        p=dict(params or {})
        if signed:
            if not self.key or not self.secret: raise ExchangeError("KEY_MISSING")
            p.update(timestamp=int(time.time()*1000)+self.offset,recvWindow=5000)
        query=urlencode(p)
        if signed: query+="&signature="+hmac.new(self.secret.encode(),query.encode(),hashlib.sha256).hexdigest()
        # Never log URLs, signatures, headers or credential payloads.
        r=await self.http.request(method,path+('?' +query if query else ''),headers={"X-MBX-APIKEY":self.key} if signed else {})
        try: data=r.json()
        except ValueError: raise ExchangeError(r.status_code,"Non-JSON response")
        if r.is_error or (isinstance(data,dict) and isinstance(data.get("code"),int) and data["code"]<0):
            raise ExchangeError(data.get("code",r.status_code),"Request failed; inspect code in Binance docs")
        return data
    async def sync_clock(self):
        start=int(time.time()*1000)
        r=await self.request("GET","/fapi/v1/time")
        self.offset=r["serverTime"]-(start+int(time.time()*1000))//2
    async def account(self): return await self.request("GET","/fapi/v3/account",signed=True)
    async def positions(self): return await self.request("GET","/fapi/v3/positionRisk",signed=True)
    async def order(self,symbol,cid): return await self.request("GET","/fapi/v1/order",{"symbol":symbol,"origClientOrderId":cid},True)
    async def algo(self,cid): return await self.request("GET","/fapi/v1/algoOrder",{"clientAlgoId":cid},True)
    async def market(self,symbol,side,qty,cid,reduce=False):
        p=dict(symbol=symbol,side=side,type="MARKET",quantity=qty,newClientOrderId=cid,newOrderRespType="RESULT",positionSide="BOTH")
        if reduce: p["reduceOnly"]="true"
        return await self.request("POST","/fapi/v1/order",p,True)
    async def protective(self,symbol,side,price,cid,tp=False):
        return await self.request("POST","/fapi/v1/algoOrder",dict(algoType="CONDITIONAL",symbol=symbol,side=side,type="TAKE_PROFIT_MARKET" if tp else "STOP_MARKET",triggerPrice=price,closePosition="true",workingType="MARK_PRICE",clientAlgoId=cid,positionSide="BOTH"),True)
