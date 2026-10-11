import os
# TEST_DATABASE_URL lets the suite run against a disposable PostgreSQL server; default is in-memory SQLite.
os.environ["DATABASE_URL"]=os.environ.get("TEST_DATABASE_URL","sqlite:///:memory:")
os.environ["ENABLE_MARKET_FEED"]="false"
os.environ["ADMIN_PASSWORD"]="testing-password-123"
os.environ["SESSION_KEY"]="a"*64
from cryptography.fernet import Fernet
os.environ["ENCRYPTION_KEY"]=Fernet.generate_key().decode()
