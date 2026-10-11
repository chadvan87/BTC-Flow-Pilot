from fastapi.testclient import TestClient
from app.main import app
from app.database.store import store
from app.config import settings
from app.security.auth import save_credentials,credentials

def test_auth_csrf_and_real_lock():
    with TestClient(app) as c:
        assert c.get('/health').json()['real_trading'] is False
        assert c.get('/api/status').status_code==401
        assert c.post('/api/login',json={'password':settings.admin_password}).status_code==200
        assert c.get('/api/status').json()['control']['stopped'] is True
        assert c.post('/api/control/stop').status_code==403
        assert c.post('/api/control/stop',headers={'X-Flowpilot-Request':'1'}).status_code==200
        assert c.post('/api/control/flatten',headers={'X-Flowpilot-Request':'1'},json={'confirm':False}).status_code==400
        assert c.post('/api/control/resume',headers={'X-Flowpilot-Request':'1'}).status_code==409

def test_secrets_encrypted_not_returned():
    save_credentials('REAL','key-for-test','secret-for-test')
    encrypted=store.get('credentials:REAL');assert 'secret-for-test' not in str(encrypted)
    assert credentials('REAL')==('key-for-test','secret-for-test')
    with TestClient(app) as c:
        c.post('/api/login',json={'password':settings.admin_password})
        assert 'secret-for-test' not in c.get('/api/status').text

def test_origin_blocked():
    with TestClient(app) as c:
        c.post('/api/login',json={'password':settings.admin_password})
        assert c.post('/api/control/stop',headers={'X-Flowpilot-Request':'1','Origin':'https://attacker.invalid'}).status_code==403

def test_sqlite_persistence(tmp_path):
    from app.database.store import Store
    url='sqlite:///'+str(tmp_path/'test.db');s=Store(url);s.put('control',{'stopped':True})
    assert Store(url).get('control')['stopped']

def test_built_dashboard_served_same_origin():
    from pathlib import Path
    import re
    dist=Path(__file__).resolve().parents[2]/'frontend'/'dist'
    if not dist.exists():
        import pytest
        pytest.skip('Run frontend build to verify static dashboard assets')
    with TestClient(app) as c:
        r=c.get('/');assert r.status_code==200
        asset=re.search(r'src="([^"]+\.js)"',r.text).group(1)
        assert c.get(asset).status_code==200

def test_health_answers_head_for_uptime_monitors():
    with TestClient(app) as c:
        assert c.head('/health').status_code==200 and c.get('/health').status_code==200
