"""Generate local .env without printing secrets or installing API credentials."""
from pathlib import Path
import getpass,secrets
from cryptography.fernet import Fernet
p=Path('.env')
if p.exists():raise SystemExit('.env exists; edit it manually. No overwrite performed.')
password=getpass.getpass('New admin password (12+ characters): ')
if len(password)<12 or any(x in password for x in ('\n','\r','"')):raise SystemExit('Use 12+ characters without line breaks or double quotes.')
url=input('Database URL [sqlite:///./flowpilot.db]: ').strip() or 'sqlite:///./flowpilot.db'
if '\n' in url or '\r' in url:raise SystemExit('Invalid URL')
p.write_text('DATABASE_URL='+url+'\nADMIN_PASSWORD="'+password+'"\nENCRYPTION_KEY='+Fernet.generate_key().decode()+'\nSESSION_KEY='+secrets.token_urlsafe(48)+'\nCORS_ORIGINS=http://localhost:5173,http://127.0.0.1:8000\nCOOKIE_SECURE=false\nALLOW_LOCAL_HTTP=true\nENABLE_MARKET_FEED=true\nTELEGRAM_TOKEN=\nTELEGRAM_CHAT_ID=\n')
try:p.chmod(0o600)
except OSError:pass
print('Created .env. Keep it private and back up ENCRYPTION_KEY separately.')
