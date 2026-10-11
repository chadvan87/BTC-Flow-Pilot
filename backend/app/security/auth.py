import hashlib, hmac, secrets, time
from fastapi import HTTPException, Request
from cryptography.fernet import Fernet
from app.config import settings
from app.database.store import store

def vault():
    if not settings.encryption_key: raise HTTPException(503,"Set ENCRYPTION_KEY first")
    return Fernet(settings.encryption_key.encode())
def save_credentials(env,key,secret):
    store.put("credentials:"+env,{"key":vault().encrypt(key.encode()).decode(),"secret":vault().encrypt(secret.encode()).decode()})
def credentials(env):
    c=store.get("credentials:"+env)
    if not c: raise HTTPException(409,"Configure API credentials for this environment")
    return tuple(vault().decrypt(c[x].encode()).decode() for x in ("key","secret"))
def issue_session():
    if len(settings.session_key)<32: raise HTTPException(503,"SESSION_KEY must contain at least 32 characters")
    body=secrets.token_hex(24)+":"+str(int(time.time())+3600)
    sig=hmac.new(settings.session_key.encode(),body.encode(),hashlib.sha256).hexdigest()
    return body+":"+sig
async def admin(request: Request):
    token=request.cookies.get("flowpilot","")
    try:
        body,sig=token.rsplit(":",1)
        if not settings.session_key or not hmac.compare_digest(sig,hmac.new(settings.session_key.encode(),body.encode(),hashlib.sha256).hexdigest()) or int(body.rsplit(":",1)[1])<time.time(): raise ValueError()
    except (ValueError,IndexError): raise HTTPException(401,"Login required")
    if request.method not in {"GET","HEAD","OPTIONS"}:
        origin=request.headers.get("origin")
        if origin and origin not in settings.cors_origins.split(","): raise HTTPException(403,"Origin blocked")
        if request.headers.get("x-flowpilot-request")!="1": raise HTTPException(403,"CSRF request header required")
    return True
