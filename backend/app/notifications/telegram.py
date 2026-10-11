import httpx
from app.config import settings
async def alert(text):
    if not settings.telegram_token or not settings.telegram_chat_id:return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post("https://api.telegram.org/bot"+settings.telegram_token+"/sendMessage",json={"chat_id":settings.telegram_chat_id,"text":text})
    except httpx.HTTPError: pass # notifications never replace exchange protection
