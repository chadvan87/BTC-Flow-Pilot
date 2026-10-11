from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    database_url: str = "sqlite:///./flowpilot.db"
    admin_password: str = ""
    encryption_key: str = ""
    session_key: str = ""
    cors_origins: str = "http://localhost:5173"
    cookie_secure: bool = False
    allow_local_http: bool = True
    enable_market_feed: bool = True
    telegram_token: str = ""
    telegram_chat_id: str = ""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
settings = Settings()
# Supported USD-M symbols. Volume-profile bin (price units) is roughly 0.01-0.05% of price, a multiple of tick size.
SYMBOLS = ("BTCUSDT","ETHUSDT","LINKUSDT","SOLUSDT","XRPUSDT","TRXUSDT","DOGEUSDT","NEARUSDT","AAVEUSDT")
FLOW_BIN = {"BTCUSDT":10,"ETHUSDT":1,"LINKUSDT":.005,"SOLUSDT":.05,"XRPUSDT":.0005,"TRXUSDT":.0001,"DOGEUSDT":.00002,"NEARUSDT":.002,"AAVEUSDT":.05}
