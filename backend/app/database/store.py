import json
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Text, select
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool
from app.config import settings
Base = declarative_base()
class Record(Base):
    __tablename__ = "records"
    key = Column(String(160), primary_key=True)
    value = Column(Text, nullable=False)
class Store:
    def __init__(self, url):
        self.engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}, pool_pre_ping=True, **({"poolclass":StaticPool} if url.endswith(":memory:") else {}))
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine)
    def get(self, key, default=None):
        with self.sessions() as s:
            r=s.get(Record,key)
            return json.loads(r.value) if r else default
    def put(self, key, value):
        with self.sessions.begin() as s:
            s.merge(Record(key=key,value=json.dumps(value,allow_nan=False)))
    def prefix(self, prefix):
        with self.sessions() as s:
            return [json.loads(r.value) for r in s.scalars(select(Record).where(Record.key.startswith(prefix))).all()]
    def audit(self, event, detail):
        import uuid
        self.put("audit:"+uuid.uuid4().hex, {"time":datetime.now(timezone.utc).isoformat(),"event":event,"detail":detail})
store = Store(settings.database_url)
